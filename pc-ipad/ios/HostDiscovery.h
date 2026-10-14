#import <Foundation/Foundation.h>

@interface HostDiscovery : NSObject
@property(nonatomic,copy) void (^found)(NSDictionary *host);
@property(nonatomic,copy) void (^failed)(NSString *reason);
- (void)start;
- (void)stop;
@end
