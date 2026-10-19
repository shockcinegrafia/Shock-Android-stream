#import <UIKit/UIKit.h>
@interface PairingScanner : UIViewController
@property(nonatomic,copy) void (^scanned)(NSString *invitation);
@end
