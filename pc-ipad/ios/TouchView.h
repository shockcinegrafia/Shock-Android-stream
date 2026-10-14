#import <UIKit/UIKit.h>
@interface TouchView : UIView
@property(nonatomic) CGSize videoSize;
@property(nonatomic,copy) void (^changed)(NSArray *events);
- (NSArray *)held;
- (void)reset;
@end
