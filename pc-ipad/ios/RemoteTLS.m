#import "RemoteTLS.h"
#import <Security/Security.h>
#import <Security/SecureTransport.h>
#import <CommonCrypto/CommonDigest.h>
#include <sys/socket.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <time.h>

@interface RemoteTLS () {
    SSLContextRef _context;
    int _socket;
    NSLock *_lock;
    RemoteTLS *_upstream;
}
- (OSStatus)transportRead:(void *)data length:(size_t *)length;
- (OSStatus)transportWrite:(const void *)data length:(size_t *)length;
- (OSStatus)step:(void *)data length:(size_t)length processed:(size_t *)processed writing:(BOOL)writing;
@end

static OSStatus tlsRead(SSLConnectionRef connection,void *data,size_t *length) {
    return [(__bridge RemoteTLS *)connection transportRead:data length:length];
}
static OSStatus tlsWrite(SSLConnectionRef connection,const void *data,size_t *length) {
    return [(__bridge RemoteTLS *)connection transportWrite:data length:length];
}
static OSStatus rawRead(int fd,void *data,size_t *length) {
    size_t wanted=*length;ssize_t n;
    do {n=recv(fd,data,wanted,0);}while(n<0&&errno==EINTR);
    *length=n>0?(size_t)n:0;
    if(n==0)return errSSLClosedGraceful;
    if(n<0)return errno==EAGAIN||errno==EWOULDBLOCK?errSSLWouldBlock:errSecIO;
    return (size_t)n==wanted?noErr:errSSLWouldBlock;
}
static OSStatus rawWrite(int fd,const void *data,size_t *length) {
    size_t wanted=*length;ssize_t n;
    do {n=send(fd,data,wanted,0);}while(n<0&&errno==EINTR);
    *length=n>0?(size_t)n:0;
    if(n<0)return errno==EAGAIN||errno==EWOULDBLOCK?errSSLWouldBlock:errSecIO;
    return (size_t)n==wanted?noErr:errSSLWouldBlock;
}
static double monotonicSeconds(void) {
    // CLOCK_MONOTONIC/clock_gettime is not available on iOS 9.
    return [NSProcessInfo processInfo].systemUptime;
}

@implementation RemoteTLS
- (instancetype)initWithSocket:(int)fd {
    return [self initWithSocket:fd upstream:nil];
}
- (instancetype)initWithSocket:(int)fd upstream:(RemoteTLS *)upstream {
    if((self=[super init])) {
        _socket=fd;_lock=[NSLock new];_upstream=upstream;
        _context=SSLCreateContext(kCFAllocatorDefault,kSSLClientSide,kSSLStreamType);
        int flags=fcntl(fd,F_GETFL,0);
        if(!_context||flags<0||fcntl(fd,F_SETFL,flags|O_NONBLOCK)<0||
           SSLSetIOFuncs(_context,tlsRead,tlsWrite)!=noErr||
           SSLSetConnection(_context,(__bridge SSLConnectionRef)self)!=noErr||
           SSLSetProtocolVersionMin(_context,kTLSProtocol12)!=noErr||
           SSLSetSessionOption(_context,kSSLSessionOptionBreakOnServerAuth,true)!=noErr)return nil;
    }
    return self;
}
- (OSStatus)step:(void *)data length:(size_t)length processed:(size_t *)processed writing:(BOOL)writing {
    [_lock lock];
    OSStatus status=writing?SSLWrite(_context,data,length,processed):SSLRead(_context,data,length,processed);
    [_lock unlock];return status;
}
- (OSStatus)transportRead:(void *)data length:(size_t *)length {
    if(!_upstream)return rawRead(_socket,data,length);
    size_t processed=0;OSStatus status=[_upstream step:data length:*length processed:&processed writing:NO];
    *length=processed;return status;
}
- (OSStatus)transportWrite:(const void *)data length:(size_t *)length {
    if(!_upstream)return rawWrite(_socket,data,length);
    size_t processed=0;OSStatus status=[_upstream step:(void *)data length:*length processed:&processed writing:YES];
    *length=processed;return status;
}
- (BOOL)handshakeWithFingerprint:(NSString *)fingerprint {
    BOOL verified=NO;double deadline=monotonicSeconds()+8;
    while(monotonicSeconds()<deadline) {
        OSStatus status=SSLHandshake(_context);
        if(status==noErr)return verified;
        if(status==errSSLServerAuthCompleted) {
            SecTrustRef trust=NULL;
            if(verified||SSLCopyPeerTrust(_context,&trust)!=noErr||!trust)return NO;
            SecCertificateRef certificate=SecTrustGetCertificateAtIndex(trust,0);
            CFDataRef data=certificate?SecCertificateCopyData(certificate):NULL;
            uint8_t digest[CC_SHA256_DIGEST_LENGTH];NSMutableString *actual=[NSMutableString new];
            if(data) {
                CC_SHA256(CFDataGetBytePtr(data),(CC_LONG)CFDataGetLength(data),digest);
                for(NSUInteger i=0;i<sizeof(digest);i++)[actual appendFormat:@"%02x",digest[i]];
                CFRelease(data);
            }
            CFRelease(trust);
            // The exact SHA-256 certificate is the trust anchor supplied out of band in the invite.
            if(actual.length!=64||![actual isEqualToString:fingerprint])return NO;
            verified=YES;continue;
        }
        if(status!=errSSLWouldBlock)return NO;
        usleep(1000);
    }
    return NO;
}
- (BOOL)transfer:(void *)buffer length:(size_t)length writing:(BOOL)writing {
    size_t done=0;double deadline=monotonicSeconds()+5;
    while(done<length) {
        size_t processed=0;
        OSStatus status=[self step:(uint8_t *)buffer+done length:length-done processed:&processed writing:writing];
        if(processed){done+=processed;deadline=monotonicSeconds()+5;}
        if(status!=noErr&&status!=errSSLWouldBlock){NSLog(@"ShockStream TLS transfer ended: status %d",(int)status);return NO;}
        if(monotonicSeconds()>=deadline)return NO;
        if(status==errSSLWouldBlock)usleep(1000);
    }
    return YES;
}
- (BOOL)readBytes:(void *)buffer length:(size_t)length {return [self transfer:buffer length:length writing:NO];}
- (BOOL)writeBytes:(const void *)buffer length:(size_t)length {return [self transfer:(void *)buffer length:length writing:YES];}
- (void)dealloc {if(_context)CFRelease(_context);}
@end

static BOOL hex64(NSString *value) {
    return value.length==64&&[value rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet]].location==NSNotFound;
}
NSDictionary *ShockRemoteInvitation(NSString *value) {
    if(![value isKindOfClass:[NSString class]]||value.length>1024)return nil;
    NSURLComponents *url=[NSURLComponents componentsWithString:value];
    BOOL relay=[url.scheme isEqual:@"shockstream-relay"];
    if((![url.scheme isEqual:@"shockstream"]&&!relay)||!url.host.length||url.host.length>253||url.user||url.password||url.path.length||url.fragment)return nil;
    if([url.host rangeOfCharacterFromSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]].location!=NSNotFound)return nil;
    NSInteger port=url.port?url.port.integerValue:(relay?443:8093);if(port<1||port>65535)return nil;
    NSMutableDictionary *query=[NSMutableDictionary new];
    for(NSURLQueryItem *item in url.queryItems) {
        if(query[item.name])return nil;
        if(relay&&[item.name isEqual:@"route"]) {
            if(item.value.length!=32||[item.value rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789abcdef"] invertedSet]].location!=NSNotFound)return nil;
        }else if(!([item.name isEqual:@"key"]||[item.name isEqual:@"cert"]||(relay&&([item.name isEqual:@"relaycert"]||[item.name isEqual:@"ticket"])))||!hex64(item.value))return nil;
        query[item.name]=item.value;
    }
    if(query.count!=(relay?5:2))return nil;
    query[@"host"]=url.host;query[@"port"]=@(port);return query;
}

static NSMutableDictionary *invitationQuery(void) {
    return [@{(__bridge id)kSecClass:(__bridge id)kSecClassGenericPassword,
              (__bridge id)kSecAttrService:@"com.shock.stream.remote",
              (__bridge id)kSecAttrAccount:@"invitation"} mutableCopy];
}
NSString *ShockLoadRemoteInvitation(void) {
    NSMutableDictionary *query=invitationQuery();query[(__bridge id)kSecReturnData]=@YES;
    CFTypeRef result=NULL;
    if(SecItemCopyMatching((__bridge CFDictionaryRef)query,&result)!=errSecSuccess)return nil;
    NSData *data=CFBridgingRelease(result);NSString *value=[[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
    return ShockRemoteInvitation(value)?value:nil;
}
BOOL ShockSaveRemoteInvitation(NSString *value) {
    if(!ShockRemoteInvitation(value))return NO;
    NSMutableDictionary *query=invitationQuery();
    NSDictionary *attributes=@{(__bridge id)kSecValueData:[value dataUsingEncoding:NSUTF8StringEncoding],
                               (__bridge id)kSecAttrAccessible:(__bridge id)kSecAttrAccessibleWhenUnlockedThisDeviceOnly};
    OSStatus result=SecItemUpdate((__bridge CFDictionaryRef)query,(__bridge CFDictionaryRef)attributes);
    if(result==errSecItemNotFound){[query addEntriesFromDictionary:attributes];result=SecItemAdd((__bridge CFDictionaryRef)query,NULL);}
    return result==errSecSuccess;
}
