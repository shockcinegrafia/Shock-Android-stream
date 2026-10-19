#import "StreamConnection.h"
#import "RemoteTLS.h"
#import <CommonCrypto/CommonHMAC.h>
#import <CommonCrypto/CommonDigest.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <arpa/inet.h>
#include <unistd.h>
#include <errno.h>
#include <fcntl.h>
#include <sys/select.h>
#include <netdb.h>

@interface StreamConnection ()
@property(nonatomic) int fd;
@property(nonatomic) int listenFD;
@property(atomic) BOOL closed;
@property(nonatomic) BOOL writing;
@property(nonatomic,strong) NSMutableArray *outgoing;
@property(nonatomic,strong) dispatch_queue_t writer;
@property(nonatomic,strong) RemoteTLS *tls;
@end
@implementation StreamConnection
- (instancetype)init {
    if((self=[super init])) { _fd=-1; _listenFD=-1; _outgoing=[NSMutableArray new]; _writer=dispatch_queue_create("shock.writer",DISPATCH_QUEUE_SERIAL); }
    return self;
}
static BOOL readAll(int fd,void *buffer,size_t count) {
    uint8_t *bytes=buffer; size_t done=0;
    while(done<count) { ssize_t n=recv(fd,bytes+done,count-done,0); if(n<=0)return NO; done+=(size_t)n; }
    return YES;
}
static BOOL writeAll(int fd,const void *buffer,size_t count) {
    const uint8_t *bytes=buffer; size_t done=0;
    while(done<count) { ssize_t n=send(fd,bytes+done,count-done,0); if(n<=0)return NO; done+=(size_t)n; }
    return YES;
}
- (void)prepareSocket:(int)fd {
    struct timeval timeout={5,0};
    setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout));setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout));
    int yes=1;setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&yes,sizeof(yes));setsockopt(fd,IPPROTO_TCP,TCP_NODELAY,&yes,sizeof(yes));
}
static BOOL connectWithinAddress(int fd,const struct sockaddr *address,socklen_t size) {
    int flags=fcntl(fd,F_GETFL,0);
    if(flags<0||fcntl(fd,F_SETFL,flags|O_NONBLOCK)<0)return NO;
    int result=connect(fd,address,size);
    if(result<0&&errno==EINPROGRESS) {
        fd_set writeSet;FD_ZERO(&writeSet);FD_SET(fd,&writeSet);struct timeval timeout={3,0};
        result=select(fd+1,NULL,&writeSet,NULL,&timeout);
        if(result>0){int error=0;socklen_t length=sizeof(error);result=getsockopt(fd,SOL_SOCKET,SO_ERROR,&error,&length)==0&&error==0?0:-1;}
        else result=-1;
    }
    if(fcntl(fd,F_SETFL,flags)<0)return NO;
    return result==0;
}
- (BOOL)readSocket:(int)fd bytes:(void *)bytes length:(size_t)length {
    return self.tls?[self.tls readBytes:bytes length:length]:readAll(fd,bytes,length);
}
- (BOOL)writeSocket:(int)fd bytes:(const void *)bytes length:(size_t)length {
    return self.tls?[self.tls writeBytes:bytes length:length]:writeAll(fd,bytes,length);
}
- (NSString *)receiveSocket:(int)fd pin:(NSString *)pin {
    uint8_t challenge[38],response[CC_SHA256_DIGEST_LENGTH],accepted=0;
    if(![self readSocket:fd bytes:challenge length:sizeof(challenge)]||memcmp(challenge,"SHOCK1",6)!=0)return @"O PC não respondeu ao protocolo Shock Stream";
    const char *key=pin.UTF8String;CCHmac(kCCHmacAlgSHA256,key,strlen(key),challenge+6,32,response);
    if(![self writeSocket:fd bytes:response length:sizeof(response)]||![self readSocket:fd bytes:&accepted length:1])return @"A conexão foi interrompida durante o emparelhamento";
    if(accepted==0)return @"PIN incorreto";
    if(accepted!=1)return @"Resposta de emparelhamento inválida";
    if(self.closed)return @"Conexão encerrada";
    if(self.authenticated)self.authenticated();
    while(!self.closed) {
        uint8_t header[5];if(![self readSocket:fd bytes:header length:5])break;
        uint32_t length;memcpy(&length,header+1,4);length=ntohl(length);
        if(length>4*1024*1024)return @"Pacote inválido";
        NSMutableData *body=[NSMutableData dataWithLength:length];if(![self readSocket:fd bytes:body.mutableBytes length:length])break;
        if(self.received)self.received(header[0],body);
    }
    return @"Conexão encerrada";
}
- (void)finishSocket:(int)fd reason:(NSString *)reason {
    [self disconnect];dispatch_sync(self.writer,^{});
    self.tls=nil;
    @synchronized(self){if(self.fd==fd){close(fd);self.fd=-1;}}
    if(self.ended)self.ended(reason);
}
- (void)connectHost:(NSString *)host port:(int)port pin:(NSString *)pin {
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT,0),^{
        @autoreleasepool {
            int fd=socket(AF_INET,SOCK_STREAM,0);if(fd<0){if(self.ended)self.ended(@"Não foi possível abrir a conexão");return;}
            @synchronized(self){if(self.closed){close(fd);return;}self.fd=fd;}
            [self prepareSocket:fd];struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_port=htons((uint16_t)port);
            NSString *reason;
            if(inet_pton(AF_INET,host.UTF8String,&address.sin_addr)!=1)reason=@"Informe o IP IPv4 do PC";
            else if(!connectWithinAddress(fd,(const struct sockaddr *)&address,sizeof(address)))reason=@"PC não encontrado; confira IP, porta e Firewall";
            else reason=[self receiveSocket:fd pin:pin];
            [self finishSocket:fd reason:reason];
        }
    });
}
- (void)connectRemote:(NSDictionary *)invitation {
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT,0),^{
        @autoreleasepool {
            struct addrinfo hints={0},*addresses=NULL;hints.ai_socktype=SOCK_STREAM;hints.ai_family=AF_UNSPEC;
            NSString *port=[invitation[@"port"] stringValue];
            if(getaddrinfo([invitation[@"host"] UTF8String],port.UTF8String,&hints,&addresses)!=0) {
                if(self.ended)self.ended(@"Endereço remoto não encontrado no DNS");return;
            }
            int fd=-1;BOOL connected=NO;
            for(struct addrinfo *address=addresses;address&&!self.closed;address=address->ai_next) {
                fd=socket(address->ai_family,SOCK_STREAM,0);if(fd<0)continue;
                @synchronized(self){if(self.closed){close(fd);fd=-1;break;}self.fd=fd;}
                [self prepareSocket:fd];
                if(connectWithinAddress(fd,address->ai_addr,(socklen_t)address->ai_addrlen)){connected=YES;break;}
                @synchronized(self){close(fd);self.fd=-1;fd=-1;}
            }
            freeaddrinfo(addresses);
            NSString *reason=@"PC remoto inacessível. Confira endereço, encaminhamento TCP 8093 ou túnel e Firewall.";
            if(connected&&!self.closed) {
                self.tls=[[RemoteTLS alloc] initWithSocket:fd];
                BOOL relay=invitation[@"relaycert"]!=nil;
                if(!self.tls||![self.tls handshakeWithFingerprint:relay?invitation[@"relaycert"]:invitation[@"cert"]])
                    reason=@"Conexão TLS recusada. Certificado diferente, versão incompatível ou tempo esgotado. Copie um convite atual do PC.";
                else {
                    BOOL ready=YES;
                    if(relay) {
                        NSData *request=[NSJSONSerialization dataWithJSONObject:@{@"v":@1,@"op":@"join",@"route":invitation[@"route"],@"ticket":invitation[@"ticket"]} options:0 error:nil];
                        NSMutableData *line=[request mutableCopy];[line appendBytes:"\n" length:1];
                        ready=[self.tls writeBytes:line.bytes length:line.length];
                        NSMutableData *response=[NSMutableData new];uint8_t byte=0;
                        while(ready&&response.length<64) {
                            ready=[self.tls readBytes:&byte length:1];if(!ready||byte=='\n')break;
                            [response appendBytes:&byte length:1];
                        }
                        NSString *status=[[NSString alloc] initWithData:response encoding:NSUTF8StringEncoding];
                        ready=ready&&byte=='\n'&&[status isEqual:@"READY"];
                        if(ready) {
                            RemoteTLS *inner=[[RemoteTLS alloc] initWithSocket:fd upstream:self.tls];
                            ready=inner&&[inner handshakeWithFingerprint:invitation[@"cert"]];
                            if(ready)self.tls=inner;
                        }
                    }
                    reason=ready?[self receiveSocket:fd pin:invitation[@"key"]]:@"PC indisponível, convite recusado ou conexão protegida interrompida. Verifique o app no PC.";
                }
            }
            [self finishSocket:fd reason:reason];
        }
    });
}
- (void)waitUSBWithPIN:(NSString *)pin {
    dispatch_async(dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT,0),^{
        @autoreleasepool {
            int listener=socket(AF_INET,SOCK_STREAM,0);if(listener<0){if(self.ended)self.ended(@"Não foi possível preparar o USB");return;}
            @synchronized(self){if(self.closed){close(listener);return;}self.listenFD=listener;}
            int yes=1;setsockopt(listener,SOL_SOCKET,SO_REUSEADDR,&yes,sizeof(yes));
            struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_port=htons(8091);address.sin_addr.s_addr=htonl(INADDR_LOOPBACK);
            NSString *reason=@"Espera USB encerrada";int fd=-1;
            if(bind(listener,(struct sockaddr *)&address,sizeof(address))<0||listen(listener,1)<0)reason=@"Porta USB indisponível. Feche e abra o app novamente.";
            else {
                fcntl(listener,F_SETFL,fcntl(listener,F_GETFL,0)|O_NONBLOCK);
                while(!self.closed) {
                    fd_set set;FD_ZERO(&set);FD_SET(listener,&set);struct timeval timeout={0,500000};
                    int ready=select(listener+1,&set,NULL,NULL,&timeout);
                    if(ready<0)break;if(ready==0)continue;
                    fd=accept(listener,NULL,NULL);if(fd>=0)break;
                }
            }
            @synchronized(self){close(listener);self.listenFD=-1;if(fd>=0)self.fd=fd;}
            if(fd>=0){
                int flags=fcntl(fd,F_GETFL,0);if(flags>=0)fcntl(fd,F_SETFL,flags&~O_NONBLOCK);
                [self prepareSocket:fd];reason=[self receiveSocket:fd pin:pin];[self finishSocket:fd reason:reason];
            }
            else {[self disconnect];if(self.ended)self.ended(reason);}
        }
    });
}
- (void)sendKind:(uint8_t)kind body:(NSData *)body {
    if(!body)body=[NSData data];
    BOOL schedule=NO;
    @synchronized(self) {
        if(self.closed||self.fd<0)return;
        // Consecutive axis updates with the same button/trigger state may replace each other.
        NSDictionary *last=self.outgoing.lastObject;
        if(kind==11&&[last[@"kind"] intValue]==11) {
            NSDictionary *old=[NSJSONSerialization JSONObjectWithData:last[@"body"] options:0 error:nil];
            NSDictionary *next=[NSJSONSerialization JSONObjectWithData:body options:0 error:nil];
            if([old[@"buttons"] isEqual:next[@"buttons"]]&&[old[@"lt"] isEqual:next[@"lt"]]&&[old[@"rt"] isEqual:next[@"rt"]]) [self.outgoing removeLastObject];
        }
        if(kind==14&&[last[@"kind"] intValue]==14) {
            NSArray *old=[NSJSONSerialization JSONObjectWithData:last[@"body"] options:0 error:nil];
            NSArray *next=[NSJSONSerialization JSONObjectWithData:body options:0 error:nil];
            BOOL moves=YES;NSMutableDictionary *merged=[NSMutableDictionary new];
            for(NSDictionary *event in old){if(![event[@"a"] isEqual:@"move"])moves=NO;merged[event[@"id"]]=event;}
            for(NSDictionary *event in next){if(![event[@"a"] isEqual:@"move"])moves=NO;merged[event[@"id"]]=event;}
            if(moves){[self.outgoing removeLastObject];body=[NSJSONSerialization dataWithJSONObject:merged.allValues options:0 error:nil];}
        }
        if(self.outgoing.count>=128){[self disconnect];return;}
        [self.outgoing addObject:@{@"kind":@(kind),@"body":body}];
        if(!self.writing){self.writing=YES;schedule=YES;}
    }
    if(schedule)dispatch_async(self.writer,^{
        while(YES) {
            NSDictionary *item;int fd;
            @synchronized(self) {
                if(self.closed||!self.outgoing.count){self.writing=NO;return;}
                item=self.outgoing[0];[self.outgoing removeObjectAtIndex:0];fd=self.fd;
            }
            NSData *payload=item[@"body"];uint8_t header[5];header[0]=[item[@"kind"] unsignedCharValue];
            uint32_t size=htonl((uint32_t)payload.length);memcpy(header+1,&size,4);
            if(![self writeSocket:fd bytes:header length:5]||![self writeSocket:fd bytes:payload.bytes length:payload.length]){[self disconnect];return;}
        }
    });
}
- (void)sendPad:(NSDictionary *)state {
    [self sendKind:11 body:[NSJSONSerialization dataWithJSONObject:state options:0 error:nil]];
}
- (void)disconnect {
    @synchronized(self) {
        if(self.closed)return;self.closed=YES;[self.outgoing removeAllObjects];
        if(self.fd>=0)shutdown(self.fd,SHUT_RDWR);
        if(self.listenFD>=0)shutdown(self.listenFD,SHUT_RDWR);
    }
}
@end
