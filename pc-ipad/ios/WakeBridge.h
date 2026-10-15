#import <Foundation/Foundation.h>
@interface WakeBridge : NSObject
@property(nonatomic,readonly) BOOL installed;
@property(nonatomic,readonly) BOOL enabled;
@property(nonatomic,readonly,copy) NSString *lastError;
@property(nonatomic,copy) void (^wake)(NSString *hostId);
@property(nonatomic,copy) void (^changed)(void);
- (void)setEnabled:(BOOL)enabled;
- (void)registerHost:(NSString *)hostId key:(NSString *)key;
- (void)setPaused:(BOOL)paused;
- (void)updateActive:(BOOL)active connected:(BOOL)connected;
- (void)processRequest;
- (NSString *)diagnostic;
- (void)stop;
@end
