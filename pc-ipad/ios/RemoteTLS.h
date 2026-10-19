#import <Foundation/Foundation.h>

// Uses iOS 9 Secure Transport. The caller owns the socket and shuts it down to cancel.
@interface RemoteTLS : NSObject
- (instancetype)initWithSocket:(int)fd;
- (BOOL)handshakeWithFingerprint:(NSString *)fingerprint;
- (BOOL)readBytes:(void *)buffer length:(size_t)length;
- (BOOL)writeBytes:(const void *)buffer length:(size_t)length;
@end

FOUNDATION_EXPORT NSDictionary *ShockRemoteInvitation(NSString *value);
FOUNDATION_EXPORT NSString *ShockLoadRemoteInvitation(void);
FOUNDATION_EXPORT BOOL ShockSaveRemoteInvitation(NSString *value);
