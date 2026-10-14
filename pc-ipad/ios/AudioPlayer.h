#import <Foundation/Foundation.h>
@interface AudioPlayer : NSObject
- (void)append:(NSData *)pcm;
- (void)stop;
@end
