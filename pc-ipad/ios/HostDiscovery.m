#import "HostDiscovery.h"
#include <arpa/inet.h>
#include <netinet/in.h>
#include <ifaddrs.h>

@interface HostDiscovery () <NSNetServiceBrowserDelegate, NSNetServiceDelegate>
@property(nonatomic,strong) NSNetServiceBrowser *browser;
@property(nonatomic,strong) NSMutableArray *services;
@property(nonatomic,strong) NSMutableSet *resolving;
@property(nonatomic,strong) NSTimer *refresh;
@end

@implementation HostDiscovery
- (void)start {
    if(self.browser)return;
    self.services=[NSMutableArray new];self.resolving=[NSMutableSet new];
    self.browser=[NSNetServiceBrowser new];self.browser.delegate=self;
    [self.browser searchForServicesOfType:@"_shockstream._tcp." inDomain:@"local."];
    self.refresh=[NSTimer scheduledTimerWithTimeInterval:5 target:self selector:@selector(resolveServices) userInfo:nil repeats:YES];
}
- (void)stop {
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
