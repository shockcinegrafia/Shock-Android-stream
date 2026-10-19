#import "../ios/RemoteTLS.h"
#include <arpa/inet.h>
#include <sys/socket.h>
#include <unistd.h>

int main(int argc,const char **argv) {
    @autoreleasepool {
        if(argc!=4)return 2;
        NSString *fingerprint=[NSString stringWithUTF8String:argv[2]];
        NSString *invite=[NSString stringWithFormat:@"shockstream://home.example:8093?key=%@&cert=%@",[@"a" stringByPaddingToLength:64 withString:@"a" startingAtIndex:0],fingerprint];
        if(!ShockRemoteInvitation(invite)||ShockRemoteInvitation([invite stringByAppendingString:@"&cert=bad"])||ShockRemoteInvitation([invite stringByReplacingOccurrencesOfString:@"8093" withString:@"0"]))return 3;
        int fd=socket(AF_INET,SOCK_STREAM,0),yes=1;setsockopt(fd,SOL_SOCKET,SO_NOSIGPIPE,&yes,sizeof(yes));
        struct sockaddr_in address={0};address.sin_family=AF_INET;address.sin_port=htons((uint16_t)atoi(argv[1]));inet_pton(AF_INET,"127.0.0.1",&address.sin_addr);
        if(connect(fd,(struct sockaddr *)&address,sizeof(address))<0)return 4;
        RemoteTLS *tls=[[RemoteTLS alloc] initWithSocket:fd];BOOL accepted=[tls handshakeWithFingerprint:fingerprint];
        BOOL expected=atoi(argv[3])!=0;
        if(accepted!=expected){close(fd);return 5;}
        if(accepted) {
            // A reader must make progress while a separate writer transmits ACK/control traffic.
            __block BOOL wrote=YES;
            dispatch_group_t group=dispatch_group_create();
            dispatch_group_async(group,dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT,0),^{
                for(int i=0;i<200;i++) {
                    uint32_t value=htonl((uint32_t)i);
                    if(![tls writeBytes:&value length:sizeof(value)]){wrote=NO;break;}
                    usleep(500);
                }
            });
            NSMutableData *received=[NSMutableData dataWithLength:1024*1024];
            if(![tls readBytes:received.mutableBytes length:received.length])return 6;
            const uint8_t *bytes=received.bytes;
            for(NSUInteger i=0;i<received.length;i++)if(bytes[i]!=(uint8_t)(i%251))return 7;
            dispatch_group_wait(group,DISPATCH_TIME_FOREVER);if(!wrote)return 8;
        }
        shutdown(fd,SHUT_RDWR);close(fd);
        puts(expected?"PASS: pinned native TLS and concurrent video/control":"PASS: wrong native TLS certificate rejected");
    }
    return 0;
}
