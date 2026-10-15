#import "WakeBridge.h"
#import <UIKit/UIKit.h>
#include <notify.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <math.h>

static NSString *const WakeDirectory=@"/var/mobile/Library/Application Support/ShockStream";
@interface WakeBridge ()
@property(nonatomic,readwrite) BOOL installed;
@property(nonatomic,readwrite) BOOL enabled;
@property(nonatomic,readwrite,copy) NSString *lastError;
@property(nonatomic) BOOL active;
@property(nonatomic) BOOL connected;
@property(nonatomic) BOOL stopped;
@property(nonatomic) int notification;
@property(nonatomic,strong) NSMutableArray *operations;
@property(nonatomic) BOOL working;
@property(nonatomic) BOOL requestPending;
@property(nonatomic) NSTimeInterval lastReady;
@property(nonatomic,copy) NSString *lastRequestId;
@end
@implementation WakeBridge
- (instancetype)init {
    if((self=[super init])) {
        _notification=-1;_operations=[NSMutableArray new];
        _installed=[[NSFileManager defaultManager] fileExistsAtPath:[[[NSBundle mainBundle] bundlePath] stringByAppendingPathComponent:@".shock-deb"]];
        _enabled=[[NSUserDefaults standardUserDefaults] boolForKey:@"wakeEnabled"];
        _lastRequestId=[[NSUserDefaults standardUserDefaults] stringForKey:@"lastWakeRequestId"];
        if(_installed) {
            __weak WakeBridge *weakSelf=self;int token=-1;
            if(notify_register_dispatch("com.shock.stream.wake",&token,dispatch_get_main_queue(),^(int value){(void)value;[weakSelf processRequest];})==NOTIFY_STATUS_OK)_notification=token;
            else [self fail:@"Não foi possível observar a abertura automática."];
        }
    }
    return self;
}
- (void)fail:(NSString *)message {
    if([self.lastError isEqual:message])return;
    self.lastError=message?:@"Falha ao atualizar o serviço USB.";
    NSLog(@"ShockStream USB: %@",self.lastError);
    if(self.changed)self.changed();
}
- (BOOL)prepareDirectory {
    if(geteuid()!=501){[self fail:@"O app precisa executar como mobile para compartilhar o pareamento."];return NO;}
    struct stat st;
    if(lstat(WakeDirectory.fileSystemRepresentation,&st)==0) {
        if(!S_ISDIR(st.st_mode)||st.st_uid!=501){[self fail:@"A pasta do serviço USB tem proprietário ou formato inválido."];return NO;}
    }else if(errno!=ENOENT){[self fail:@"Não foi possível acessar a pasta do serviço USB."];return NO;}
    NSDictionary *attributes=@{NSFilePosixPermissions:@0700,NSFileProtectionKey:NSFileProtectionNone};
    NSFileManager *manager=[NSFileManager defaultManager];
    if(![manager createDirectoryAtPath:WakeDirectory withIntermediateDirectories:YES attributes:attributes error:nil]||
       ![manager setAttributes:attributes ofItemAtPath:WakeDirectory error:nil]) {
        [self fail:@"Não foi possível preparar a pasta do serviço USB. O streaming continua disponível."];return NO;
    }
    return YES;
}
- (NSDictionary *)readName:(NSString *)name limit:(size_t)limit error:(BOOL *)invalid {
    *invalid=NO;NSString *path=[WakeDirectory stringByAppendingPathComponent:name];
    int fd=open(path.fileSystemRepresentation,O_RDONLY|O_NOFOLLOW|O_NONBLOCK);
    if(fd<0){if(errno!=ENOENT)*invalid=YES;return nil;}
    struct stat st;
    if(fstat(fd,&st)<0||!S_ISREG(st.st_mode)||st.st_uid!=501||(st.st_mode&0077)!=0||st.st_size<1||(uint64_t)st.st_size>limit){close(fd);*invalid=YES;return nil;}
    NSMutableData *data=[NSMutableData dataWithLength:(NSUInteger)st.st_size];size_t done=0;
    while(done<data.length){ssize_t count=read(fd,(uint8_t *)data.mutableBytes+done,data.length-done);if(count<0&&errno==EINTR)continue;if(count<=0)break;done+=(size_t)count;}
    close(fd);
    if(done!=data.length){*invalid=YES;return nil;}
    id value=[NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:nil];
    if(![value isKindOfClass:[NSDictionary class]]){*invalid=YES;return nil;}
    return value;
}
- (BOOL)writeName:(NSString *)name value:(NSDictionary *)value {
    NSData *data=[NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:nil];
    if(!data||data.length>65536)return NO;
    NSString *path=[WakeDirectory stringByAppendingPathComponent:name];
    NSString *temporary=[WakeDirectory stringByAppendingPathComponent:[NSString stringWithFormat:@".%@.%@",name,[NSUUID UUID].UUIDString]];
    int fd=open(temporary.fileSystemRepresentation,O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);
    if(fd<0)return NO;
    size_t done=0;
    while(done<data.length){ssize_t count=write(fd,(const uint8_t *)data.bytes+done,data.length-done);if(count<0&&errno==EINTR)continue;if(count<=0)break;done+=(size_t)count;}
    BOOL good=done==data.length&&fchmod(fd,0600)==0;
    if(close(fd)<0)good=NO;
    if(good)good=[[NSFileManager defaultManager] setAttributes:@{NSFileProtectionKey:NSFileProtectionNone,NSFilePosixPermissions:@0600} ofItemAtPath:temporary error:nil];
    if(good)good=rename(temporary.fileSystemRepresentation,path.fileSystemRepresentation)==0;
    if(!good)unlink(temporary.fileSystemRepresentation);
    return good;
}
- (void)mutate:(void (^)(NSMutableDictionary *state))mutation {
    if(!self.installed||self.stopped)return;
    if(self.operations.count>=32){[self fail:@"O serviço USB está ocupado; tente ativar novamente."];return;}
    [self.operations addObject:[@{@"change":[mutation copy],@"tries":@0} mutableCopy]];
    if(!self.working){self.working=YES;[self nextMutation];}
}
- (void)nextMutation {
    if(self.stopped||!self.operations.count){self.working=NO;return;}
    NSMutableDictionary *operation=self.operations[0];BOOL retry=NO,success=NO;
    BOOL isRequest=[operation[@"request"] boolValue],prepared=[self prepareDirectory];NSDictionary *accepted=nil;
    if(prepared) {
        NSString *path=[WakeDirectory stringByAppendingPathComponent:@"wake.lock"];
        int fd=open(path.fileSystemRepresentation,O_RDWR|O_CREAT|O_NOFOLLOW|O_NONBLOCK,0600);struct stat st;
        if(fd>=0&&fstat(fd,&st)==0&&S_ISREG(st.st_mode)&&st.st_uid==501&&(st.st_mode&0077)==0) {
            if(flock(fd,LOCK_EX|LOCK_NB)==0) {
                BOOL invalid=NO;NSDictionary *saved=[self readName:@"wake.plist" limit:65536 error:&invalid];
                if(!invalid&&(!saved||([saved[@"version"] isEqual:@1]&&[saved[@"hosts"] isKindOfClass:[NSDictionary class]]))) {
                    NSMutableDictionary *state=saved?[saved mutableCopy]:[@{@"version":@1,@"hosts":@{},@"paused":@YES,@"enabled":@NO} mutableCopy];
                    if(isRequest) {
                        accepted=[self acceptedRequestForState:state];
                        if(accepted){state[@"paused"]=@NO;success=[self writeName:@"wake.plist" value:state];}
                        else success=YES;
                    }else {
                        void (^change)(NSMutableDictionary *)=operation[@"change"];change(state);
                        success=[self writeName:@"wake.plist" value:state];
                    }
                }
                flock(fd,LOCK_UN);
            }else retry=errno==EWOULDBLOCK||errno==EAGAIN;
        }
        if(fd>=0)close(fd);
    }
    if(retry&&[operation[@"tries"] intValue]<10) {
        operation[@"tries"]=@([operation[@"tries"] intValue]+1);
        __weak WakeBridge *weakSelf=self;
        dispatch_after(dispatch_time(DISPATCH_TIME_NOW,50*NSEC_PER_MSEC),dispatch_get_main_queue(),^{[weakSelf nextMutation];});return;
    }
    if(!success&&prepared)[self fail:@"Não foi possível salvar o pareamento do serviço USB. O streaming continua disponível."];
    else if(success&&(!isRequest||accepted)){self.lastError=nil;if(self.changed)self.changed();}
    if(isRequest)self.requestPending=NO;
    if(success&&accepted){self.lastRequestId=accepted[@"requestId"];[[NSUserDefaults standardUserDefaults] setObject:self.lastRequestId forKey:@"lastWakeRequestId"];}
    [self.operations removeObjectAtIndex:0];
    if(success&&accepted&&self.wake)self.wake(accepted[@"hostId"]);
    [self nextMutation];
}
- (void)setEnabled:(BOOL)enabled {
    _enabled=enabled;[[NSUserDefaults standardUserDefaults] setBool:enabled forKey:@"wakeEnabled"];
    [self mutate:^(NSMutableDictionary *state){state[@"enabled"]=@(enabled);state[@"paused"]=@(!enabled);}];
    if(self.changed)self.changed();
}
- (void)registerHost:(NSString *)hostId key:(NSString *)key {
    if(!self.installed||![hostId isKindOfClass:[NSString class]]||!hostId.length||hostId.length>128||![key isKindOfClass:[NSString class]]||key.length!=64)return;
    NSCharacterSet *hex=[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdefABCDEF"];
    if([key rangeOfCharacterFromSet:hex.invertedSet].location!=NSNotFound)return;
    if(![[NSUserDefaults standardUserDefaults] objectForKey:@"wakeEnabled"]){_enabled=YES;[[NSUserDefaults standardUserDefaults] setBool:YES forKey:@"wakeEnabled"];}
    BOOL enabled=self.enabled,paused=!enabled||!self.active;
    NSString *normalized=[key lowercaseString];
    [self mutate:^(NSMutableDictionary *state){
        NSMutableDictionary *hosts=[state[@"hosts"] mutableCopy];
        if(hosts.count>=64&&!hosts[hostId])return;
        hosts[hostId]=@{@"key":normalized};state[@"hosts"]=hosts;state[@"enabled"]=@(enabled);state[@"paused"]=@(paused);
    }];
}
- (void)setPaused:(BOOL)paused {
    BOOL enabled=self.enabled;
    [self mutate:^(NSMutableDictionary *state){state[@"enabled"]=@(enabled);state[@"paused"]=@(paused||!enabled);}];
}
- (void)updateActive:(BOOL)active connected:(BOOL)connected {
    BOOL changed=self.active!=active||self.connected!=connected;self.active=active;self.connected=connected;
    if(!self.installed||self.stopped)return;
    NSTimeInterval now=[NSDate timeIntervalSinceReferenceDate];
    if(!changed&&now-self.lastReady<1)return;
    self.lastReady=now;
    if(![self prepareDirectory]||![self writeName:@"ready.plist" value:@{@"active":@(active),@"connected":@(connected),@"updated":@([[NSDate date] timeIntervalSince1970])}])
        [self fail:@"Não foi possível atualizar o estado do app para o serviço USB."];
}
- (void)processRequest {
    if(!self.installed||!self.enabled||!self.active||self.stopped||self.requestPending||self.operations.count>=32)return;
    self.requestPending=YES;
    [self.operations addObject:[@{@"request":@YES,@"tries":@0} mutableCopy]];
    if(!self.working){self.working=YES;[self nextMutation];}
}
- (NSDictionary *)acceptedRequestForState:(NSDictionary *)state {
    if(!self.active||!self.enabled)return nil;
    BOOL invalid=NO;NSDictionary *request=[self readName:@"request.plist" limit:8192 error:&invalid];
    if(invalid){[self fail:@"O pedido do serviço USB é inválido. Abra o app pelo ícone."];return nil;}
    NSString *requestId=request[@"requestId"],*hostId=request[@"hostId"];NSNumber *expiry=request[@"expires"];
    NSTimeInterval now=[[NSDate date] timeIntervalSince1970];
    if(![requestId isKindOfClass:[NSString class]]||!requestId.length||requestId.length>128||[requestId isEqual:self.lastRequestId]||
       ![hostId isKindOfClass:[NSString class]]||!hostId.length||hostId.length>128||![expiry isKindOfClass:[NSNumber class]]||
       !isfinite(expiry.doubleValue)||expiry.doubleValue<=now||expiry.doubleValue>now+300)return nil;
    if(![state[@"enabled"] isEqual:@YES]||![state[@"hosts"] isKindOfClass:[NSDictionary class]]||![state[@"hosts"][hostId] isKindOfClass:[NSDictionary class]])return nil;
    if([state[@"paused"] isEqual:@YES]&&![request[@"force"] isEqual:@YES])return nil;
    return request;
}
- (NSString *)diagnostic {
    return [NSString stringWithFormat:@"Shock Stream %@\niOS %@ · ARMv7\nPacote .deb: %@\nAbertura USB: %@\nApp ativo: %@ · conectado: %@\nEstado compartilhado: %@",[[NSBundle mainBundle] objectForInfoDictionaryKey:@"CFBundleShortVersionString"],[[UIDevice currentDevice] systemVersion],self.installed?@"sim":@"não",self.enabled?@"ativada":@"desativada",self.active?@"sim":@"não",self.connected?@"sim":@"não",self.lastError?:@"sem erro registrado"];
}
- (void)stop { self.stopped=YES;if(self.notification>=0){notify_cancel(self.notification);self.notification=-1;}[self.operations removeAllObjects]; }
- (void)dealloc { [self stop]; }
@end
