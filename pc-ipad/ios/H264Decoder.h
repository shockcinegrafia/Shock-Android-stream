#import <Foundation/Foundation.h>
#import <CoreVideo/CoreVideo.h>
@interface H264Decoder : NSObject
@property(nonatomic,copy) void (^frame)(CVPixelBufferRef buffer);
@property(nonatomic,copy) void (^failure)(NSString *reason);
- (void)decode:(NSData *)packet;
- (void)stop;
@end
