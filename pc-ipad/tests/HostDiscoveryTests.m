#import "../ios/HostDiscovery.h"
#include <stdio.h>
#include <stdlib.h>

static void Check(BOOL condition,const char *message) {
    if(!condition){fprintf(stderr,"FAIL: %s\n",message);exit(1);}
}
static NSData *Reply(id value) {
    NSMutableData *data=[NSMutableData dataWithBytes:"SHOCK_REPLY_V1:" length:15];
    [data appendData:[NSJSONSerialization dataWithJSONObject:value options:0 error:nil]];return data;
}
int main(void) {
    @autoreleasepool {
        NSDictionary *valid=@{@"hostId":@"0123456789abcdef0123456789abcdef",@"name":@"PC",@"port":@8090,
                              @"addresses":@[@"203.0.113.1"]};
        NSDictionary *host=[HostDiscovery hostFromUDPReply:Reply(valid) sender:@"192.168.1.20"];
        Check([host[@"host"] isEqual:@"192.168.1.20"],"use packet sender, not advertised addresses");
        Check([host[@"addresses"] isEqual:@[@"192.168.1.20"]],"normalize address list");
        Check([host[@"hostId"] isEqual:valid[@"hostId"]],"preserve identity");
        for(id port in @[@YES,@0,@65536,@1.5,@"8090",[NSNull null]]) {
            NSMutableDictionary *bad=[valid mutableCopy];bad[@"port"]=port;
            Check(![HostDiscovery hostFromUDPReply:Reply(bad) sender:@"192.168.1.20"],"reject invalid port types/range");
        }
        for(id identity in @[@[],@123,@"",@"not-a-host",[NSNull null]]) {
            NSMutableDictionary *bad=[valid mutableCopy];bad[@"hostId"]=identity;
            Check(![HostDiscovery hostFromUDPReply:Reply(bad) sender:@"192.168.1.20"],"reject invalid identities");
        }
        for(id name in @[@[],@1,[NSNull null]]) {
            NSMutableDictionary *bad=[valid mutableCopy];bad[@"name"]=name;
            Check(![HostDiscovery hostFromUDPReply:Reply(bad) sender:@"192.168.1.20"],"reject unsafe display name");
        }
        for(NSString *source in @[@"invalid",@"0.0.0.0",@"127.0.0.1",@"224.0.0.1",@"255.255.255.255"]) {
            Check(![HostDiscovery hostFromUDPReply:Reply(valid) sender:source],"reject invalid source addresses");
        }
        Check(![HostDiscovery hostFromUDPReply:Reply(@[]) sender:@"192.168.1.20"],"reject JSON array");
        Check(![HostDiscovery hostFromUDPReply:[@"SHOCK_REPLY_V1:{" dataUsingEncoding:NSUTF8StringEncoding] sender:@"192.168.1.20"],"reject malformed JSON");
        Check(![HostDiscovery hostFromUDPReply:[NSMutableData dataWithLength:1025] sender:@"192.168.1.20"],"bound packet length");
        puts("PASS: native discovery JSON validation, source address and malformed replies");
    }
    return 0;
}
