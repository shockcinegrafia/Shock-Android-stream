#import <Foundation/Foundation.h>
@interface StreamConnection : NSObject
@property(nonatomic,copy) void (^received)(uint8_t kind,NSData *body);
@property(nonatomic,copy) void (^ended)(NSString *reason);
- (void)connectHost:(NSString *)host port:(int)port pin:(NSString *)pin;
- (void)waitUSBWithPIN:(NSString *)pin;
- (void)sendKind:(uint8_t)kind body:(NSData *)body;
- (void)sendPad:(NSDictionary *)state;
- (void)disconnect;
@end
