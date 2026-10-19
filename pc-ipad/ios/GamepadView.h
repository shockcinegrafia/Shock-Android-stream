#import <UIKit/UIKit.h>
@interface GamepadView : UIView
@property(nonatomic,copy) void (^changed)(NSDictionary *state);
- (NSDictionary *)state;
- (void)neutral;
@end
