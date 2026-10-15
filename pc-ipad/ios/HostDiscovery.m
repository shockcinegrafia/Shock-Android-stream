#import "HostDiscovery.h"
#import <CoreFoundation/CoreFoundation.h>
#include <sys/socket.h>
#include <arpa/inet.h>
#include <netinet/in.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <fcntl.h>
#include <unistd.h>
#include <string.h>
#include <math.h>

@interface HostDiscovery () <NSNetServiceBrowserDelegate, NSNetServiceDelegate>
@property(nonatomic,strong) NSNetServiceBrowser *browser;
@property(nonatomic,strong) NSMutableArray *services;
@property(nonatomic,strong) NSMutableSet *resolving;
@property(nonatomic,strong) NSTimer *refresh;
@property(nonatomic) int udpSocket;
@property(nonatomic,strong) dispatch_source_t udpSource;
@property(nonatomic,strong) NSTimer *udpPingTimer;
@property(nonatomic) NSUInteger generation;
@end

@implementation HostDiscovery
+ (NSDictionary *)hostFromUDPReply:(NSData *)data sender:(NSString *)address {
    const char prefix[]="SHOCK_REPLY_V1:";NSUInteger prefixLength=sizeof(prefix)-1;
    if(data.length<=prefixLength||data.length>1024||memcmp(data.bytes,prefix,prefixLength))return nil;
    struct in_addr source;
    if(![address isKindOfClass:[NSString class]]||inet_pton(AF_INET,address.UTF8String,&source)!=1)return nil;
    uint32_t ip=ntohl(source.s_addr);
    if(ip==0||(ip>>24)==127||(ip>>24)>=224)return nil;
    id value=[NSJSONSerialization JSONObjectWithData:[data subdataWithRange:NSMakeRange(prefixLength,data.length-prefixLength)] options:0 error:nil];
    if(![value isKindOfClass:[NSDictionary class]])return nil;
    NSString *identity=value[@"hostId"];NSNumber *port=value[@"port"];id name=value[@"name"];
    NSCharacterSet *hex=[[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdefABCDEF"] invertedSet];
    if(![identity isKindOfClass:[NSString class]]||identity.length!=32||[identity rangeOfCharacterFromSet:hex].location!=NSNotFound)return nil;
    if(![port isKindOfClass:[NSNumber class]]||CFGetTypeID((__bridge CFTypeRef)port)==CFBooleanGetTypeID()||
       !isfinite(port.doubleValue)||port.doubleValue<1||port.doubleValue>65535||floor(port.doubleValue)!=port.doubleValue)return nil;
    if(name&&(![name isKindOfClass:[NSString class]]||[name length]>128))return nil;
    // Prefer the actual LAN sender. Never let unauthenticated JSON supply a target address.
    return @{@"hostId":identity,@"host":address,@"addresses":@[address],@"port":port,@"name":name?:@"PC"};
}
- (instancetype)init {
    if((self=[super init])) {
        _udpSocket = -1;
    }
    return self;
}
- (void)start {
    if(self.browser)return;
    NSUInteger generation=++self.generation;
    self.services=[NSMutableArray new];self.resolving=[NSMutableSet new];
    self.browser=[NSNetServiceBrowser new];self.browser.delegate=self;
    [self.browser searchForServicesOfType:@"_shockstream._tcp." inDomain:@"local."];
    self.refresh=[NSTimer scheduledTimerWithTimeInterval:5 target:self selector:@selector(resolveServices) userInfo:nil repeats:YES];

    self.udpSocket = socket(AF_INET, SOCK_DGRAM, 0);
    if(self.udpSocket >= 0) {
        int broadcast = 1;
        setsockopt(self.udpSocket, SOL_SOCKET, SO_BROADCAST, &broadcast, sizeof(broadcast));
        struct sockaddr_in bindAddr;
        memset(&bindAddr, 0, sizeof(bindAddr));
        bindAddr.sin_family = AF_INET;
        bindAddr.sin_addr.s_addr = INADDR_ANY;
        bindAddr.sin_port = 0;
        int flags=fcntl(self.udpSocket,F_GETFL,0);
        if(flags<0||fcntl(self.udpSocket,F_SETFL,flags|O_NONBLOCK)<0||
           bind(self.udpSocket,(struct sockaddr *)&bindAddr,sizeof(bindAddr))!=0) {
            close(self.udpSocket);self.udpSocket=-1;return;
        }

        self.udpSource = dispatch_source_create(DISPATCH_SOURCE_TYPE_READ, self.udpSocket, 0, dispatch_get_main_queue());
        if(!self.udpSource){close(self.udpSocket);self.udpSocket=-1;return;}
        __weak HostDiscovery *weakSelf = self;
        int sock = self.udpSocket;
        dispatch_source_set_event_handler(self.udpSource, ^{
            HostDiscovery *owner=weakSelf;
            if(!owner||owner.generation!=generation||owner.udpSocket!=sock)return;
            for(int count=0;count<16;count++) {
                char buffer[1025];struct sockaddr_in from={0};socklen_t fromLen=sizeof(from);
                ssize_t n=recvfrom(sock,buffer,sizeof(buffer),0,(struct sockaddr *)&from,&fromLen);
                if(n<=0)break;
                if(from.sin_family!=AF_INET||fromLen<sizeof(from)||n>1024)continue;
                char ip[INET_ADDRSTRLEN];if(!inet_ntop(AF_INET,&from.sin_addr,ip,sizeof(ip)))continue;
                NSDictionary *host=[HostDiscovery hostFromUDPReply:[NSData dataWithBytes:buffer length:(NSUInteger)n] sender:[NSString stringWithUTF8String:ip]];
                if(host&&owner.found)owner.found(host);
                if(owner.generation!=generation)return;
            }
        });
        // GCD must finish using the descriptor before it is closed or reused.
        dispatch_source_set_cancel_handler(self.udpSource, ^{close(sock);});
        dispatch_resume(self.udpSource);
        [self sendUDPPing];
        self.udpPingTimer = [NSTimer scheduledTimerWithTimeInterval:3 target:self selector:@selector(sendUDPPing) userInfo:nil repeats:YES];
    }
}
- (void)sendUDPPing {
    if(self.udpSocket < 0) return;
    struct sockaddr_in to;
    memset(&to, 0, sizeof(to));
    to.sin_family = AF_INET;
    to.sin_port = htons(8090);
    to.sin_addr.s_addr = INADDR_BROADCAST;
    const char *msg = "SHOCK_DISCOVER_V1";
    sendto(self.udpSocket, msg, strlen(msg), 0, (struct sockaddr *)&to, sizeof(to));
}
- (void)stop {
    self.generation++;
    if(self.udpPingTimer) { [self.udpPingTimer invalidate]; self.udpPingTimer = nil; }
    if(self.udpSource) { dispatch_source_cancel(self.udpSource); self.udpSource = nil;self.udpSocket=-1; }
    else if(self.udpSocket >= 0) { close(self.udpSocket); self.udpSocket = -1; }
    self.browser.delegate=nil;[self.browser stop];self.browser=nil;
    [self.refresh invalidate];self.refresh=nil;
    for(NSNetService *service in self.services){service.delegate=nil;[service stop];}
    [self.services removeAllObjects];
    [self.resolving removeAllObjects];
}
- (void)netServiceBrowser:(NSNetServiceBrowser *)browser didFindService:(NSNetService *)service moreComing:(BOOL)moreComing {
    (void)browser;(void)moreComing;
    service.delegate=self;[self.services addObject:service];[self.resolving addObject:service];[service resolveWithTimeout:4];
}
- (void)netServiceBrowser:(NSNetServiceBrowser *)browser didRemoveService:(NSNetService *)service moreComing:(BOOL)moreComing {
    (void)browser;(void)moreComing;
    NSUInteger index=[self.services indexOfObject:service];
    if(index!=NSNotFound){NSNetService *old=self.services[index];old.delegate=nil;[old stop];[self.resolving removeObject:old];[self.services removeObjectAtIndex:index];}
}
- (void)netServiceBrowser:(NSNetServiceBrowser *)browser didNotSearch:(NSDictionary *)error {
    (void)browser;(void)error;
    if(self.failed)self.failed(@"Busca automática indisponível. Você ainda pode informar o IP do PC.");
}
- (void)netServiceDidResolveAddress:(NSNetService *)service {
    [self.resolving removeObject:service];
    NSData *record=service.TXTRecordData;
    if(!record.length)return;
    NSDictionary *txt=[NSNetService dictionaryFromTXTRecordData:record];
    NSData *identity=txt[@"hostId"];
    NSString *hostId=identity?[[NSString alloc] initWithData:identity encoding:NSUTF8StringEncoding]:nil;
    if(!hostId.length||hostId.length>128||service.port<1||service.port>65535)return;
    NSMutableArray *local=[NSMutableArray new],*other=[NSMutableArray new];
    struct ifaddrs *interfaces=NULL;getifaddrs(&interfaces);
    for(NSData *data in service.addresses) {
        if(data.length<sizeof(struct sockaddr_in))continue;
        const struct sockaddr *address=data.bytes;
        if(address->sa_family!=AF_INET)continue;
        const struct sockaddr_in *ipv4=data.bytes;char text[INET_ADDRSTRLEN];
        if(!inet_ntop(AF_INET,&ipv4->sin_addr,text,sizeof(text)))continue;
        NSString *ip=[NSString stringWithUTF8String:text];
        if(!ip.length||[ip hasPrefix:@"127."]||[ip isEqual:@"0.0.0.0"])continue;
        BOOL sameSubnet=NO;
        for(struct ifaddrs *item=interfaces;item;item=item->ifa_next) {
            if(!item->ifa_addr||!item->ifa_netmask||item->ifa_addr->sa_family!=AF_INET)continue;
            const struct sockaddr_in *own=(const struct sockaddr_in *)item->ifa_addr,*mask=(const struct sockaddr_in *)item->ifa_netmask;
            if(mask->sin_addr.s_addr&&(ipv4->sin_addr.s_addr&mask->sin_addr.s_addr)==(own->sin_addr.s_addr&mask->sin_addr.s_addr))sameSubnet=YES;
        }
        NSMutableArray *target=sameSubnet?local:other;
        if(![local containsObject:ip]&&![other containsObject:ip])[target addObject:ip];
    }
    if(interfaces)freeifaddrs(interfaces);
    [local addObjectsFromArray:other];
    if(!local.count)return;
    NSString *name=txt[@"name"]?[[NSString alloc] initWithData:txt[@"name"] encoding:NSUTF8StringEncoding]:service.name;
    if(self.found)self.found(@{@"hostId":hostId,@"host":local[0],@"addresses":local,@"port":@(service.port),@"name":name?:service.name?:@"PC"});
}
- (void)netService:(NSNetService *)service didNotResolve:(NSDictionary *)error { (void)error;[self.resolving removeObject:service]; }
- (void)resolveServices {
    for(NSNetService *service in self.services)if(![self.resolving containsObject:service]) {
        [self.resolving addObject:service];[service stop];[service resolveWithTimeout:4];
    }
}
- (void)dealloc { [self stop]; }
@end
