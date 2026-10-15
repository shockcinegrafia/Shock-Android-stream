// Fixed-purpose mobile-user USB wake service. It never accepts paths, bundle
// identifiers, shell commands or launch options, and never unlocks the device.
#import <Foundation/Foundation.h>
#import <CoreFoundation/CoreFoundation.h>
#import <Security/SecRandom.h>
#import <CommonCrypto/CommonHMAC.h>
#import <CommonCrypto/CommonDigest.h>
#import <objc/message.h>
#import <dispatch/dispatch.h>
#include <arpa/inet.h>
#include <sys/socket.h>
#include <sys/select.h>
#include <sys/stat.h>
#include <sys/file.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <mach/mach_time.h>
#include <pthread.h>
#include <signal.h>
#include <unistd.h>
#include <fcntl.h>
#include <pwd.h>
#include <dlfcn.h>
#include <errno.h>
#include <limits.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

static NSString *const kShared = @"/var/mobile/Library/Application Support/ShockStream";
static NSString *const kBundle = @"com.shock.stream.ipad";
static const char *kNotification = "com.shock.stream.wake";
static const uint16_t kPort = 8092;
static volatile sig_atomic_t gStop = 0;
static pthread_mutex_t gClientsLock = PTHREAD_MUTEX_INITIALIZER;
static NSMutableSet *gClients;
static dispatch_queue_t gLaunchQueue;
static dispatch_semaphore_t gLaunchSlot;

// Signatures: conradev/Open/open.m and theos/headers/SpringBoardServices.
// Private frameworks remain optional runtime capabilities, not link dependencies.
typedef int (*SBSLaunch)(CFStringRef identifier, Boolean suspended);
typedef mach_port_t (*SBServerPort)(void);
typedef void (*SBLockStatus)(mach_port_t port, BOOL *locked, BOOL *passcode);
static SBSLaunch gSBSLaunch;
static SBServerPort gSBServerPort;
static SBLockStatus gSBLockStatus;
static Class gWorkspaceClass;
extern uint32_t notify_post(const char *name);

static NSString *SharedPath(NSString *name) { return [kShared stringByAppendingPathComponent:name]; }
static double Monotonic(void) {
    static mach_timebase_info_data_t info;
    static dispatch_once_t once;
    dispatch_once(&once, ^{ mach_timebase_info(&info); });
    return (double)mach_absolute_time() * (double)info.numer / (double)info.denom / 1e9;
}
static void StopSignal(int number) { (void)number; gStop = 1; }

static BOOL Transfer(int fd, void *buffer, size_t size, BOOL writing, double deadline) {
    size_t done = 0;
    while (done < size && !gStop) {
        double remaining = deadline - Monotonic();
        if (remaining <= 0 || fd < 0 || fd >= FD_SETSIZE) return NO;
        struct timeval wait = {(time_t)remaining, (suseconds_t)((remaining - (time_t)remaining) * 1e6)};
        fd_set set; FD_ZERO(&set); FD_SET(fd, &set);
        int ready = select(fd + 1, writing ? NULL : &set, writing ? &set : NULL, NULL, &wait);
        if (ready < 0 && errno == EINTR) continue;
        if (ready <= 0) return NO;
        ssize_t count = writing ? send(fd, (const char *)buffer + done, size - done, 0)
                               : recv(fd, (char *)buffer + done, size - done, 0);
        if (count < 0 && (errno == EINTR || errno == EAGAIN || errno == EWOULDBLOCK)) continue;
        if (count <= 0) return NO;
        done += (size_t)count;
    }
    return done == size;
}
static BOOL PrivateFile(int fd, off_t maximum) {
    struct stat st;
    return fstat(fd, &st) == 0 && S_ISREG(st.st_mode) && st.st_uid == getuid() &&
           (st.st_mode & 0777) == 0600 && st.st_size >= 0 && st.st_size <= maximum;
}
static int OpenLock(NSString *name) {
    int fd = open(SharedPath(name).fileSystemRepresentation, O_RDWR | O_CREAT | O_NOFOLLOW | O_CLOEXEC, 0600);
    if (fd < 0) return -1;
    if (!PrivateFile(fd, 64)) { close(fd); return -1; }
    return fd;
}
static int StateLock(void) {
    int fd = OpenLock(@"wake.lock");
    if (fd < 0) return -1;
    for (int attempt = 0; attempt < 50 && !gStop; attempt++) {
        if (flock(fd, LOCK_EX | LOCK_NB) == 0) return fd;
        if (errno != EWOULDBLOCK && errno != EAGAIN && errno != EINTR) break;
        usleep(10000);
    }
    close(fd); return -1;
}
static void Unlock(int fd) { if (fd >= 0) { flock(fd, LOCK_UN); close(fd); } }
static NSDictionary *ReadPlist(NSString *name, off_t maximum) {
    int fd = open(SharedPath(name).fileSystemRepresentation, O_RDONLY | O_NOFOLLOW | O_CLOEXEC);
    if (fd < 0) return nil;
    if (!PrivateFile(fd, maximum)) { close(fd); return nil; }
    NSMutableData *data = [NSMutableData new];
    uint8_t buffer[4096];
    while (YES) {
        ssize_t count = read(fd, buffer, sizeof(buffer));
        if (count < 0 && errno == EINTR) continue;
        if (count < 0 || data.length + (NSUInteger)MAX(count, 0) > (NSUInteger)maximum) { close(fd); return nil; }
        if (count == 0) break;
        [data appendBytes:buffer length:(NSUInteger)count];
    }
    close(fd);
    id value = [NSPropertyListSerialization propertyListWithData:data options:NSPropertyListImmutable format:NULL error:nil];
    return [value isKindOfClass:[NSDictionary class]] ? value : nil;
}
static BOOL WritePlist(NSString *name, NSDictionary *value) {
    NSData *data = [NSPropertyListSerialization dataWithPropertyList:value format:NSPropertyListBinaryFormat_v1_0 options:0 error:nil];
    if (!data || data.length > 128 * 1024) return NO;
    NSString *pattern = SharedPath([NSString stringWithFormat:@".%@.XXXXXX", name]);
    char temporary[PATH_MAX];
    if (![pattern getFileSystemRepresentation:temporary maxLength:sizeof(temporary)]) return NO;
    int fd = mkstemp(temporary);
    if (fd < 0) return NO;
    BOOL okay = fchmod(fd, 0600) == 0;
    size_t offset = 0;
    while (okay && offset < data.length) {
        ssize_t count = write(fd, (const char *)data.bytes + offset, data.length - offset);
        if (count < 0 && errno == EINTR) continue;
        if (count <= 0) { okay = NO; break; }
        offset += (size_t)count;
    }
    if (okay) okay = fsync(fd) == 0;
    close(fd);
    if (okay) okay = rename(temporary, SharedPath(name).fileSystemRepresentation) == 0;
    if (!okay) unlink(temporary);
    return okay;
}
static int HexDigit(unichar value) {
    if (value >= '0' && value <= '9') return value - '0';
    if (value >= 'a' && value <= 'f') return value - 'a' + 10;
    if (value >= 'A' && value <= 'F') return value - 'A' + 10;
    return -1;
}
static BOOL IsHex(NSString *text, NSUInteger length) {
    if (![text isKindOfClass:[NSString class]] || text.length != length) return NO;
    for (NSUInteger index = 0; index < length; index++) if (HexDigit([text characterAtIndex:index]) < 0) return NO;
    return YES;
}
static NSData *DecodeKey(id text) {
    if (!IsHex(text, 64)) return nil;
    uint8_t bytes[32];
    for (NSUInteger index = 0; index < 32; index++)
        bytes[index] = (uint8_t)((HexDigit([text characterAtIndex:index * 2]) << 4) | HexDigit([text characterAtIndex:index * 2 + 1]));
    return [NSData dataWithBytes:bytes length:sizeof(bytes)];
}
static NSString *RandomID(void) {
    uint8_t bytes[16];
    if (SecRandomCopyBytes(kSecRandomDefault, sizeof(bytes), bytes) != errSecSuccess) return nil;
    NSMutableString *text = [NSMutableString stringWithCapacity:32];
    for (size_t index = 0; index < sizeof(bytes); index++) [text appendFormat:@"%02x", bytes[index]];
    return text;
}
static BOOL EqualMAC(const uint8_t *a, const uint8_t *b) {
    volatile uint8_t difference = 0;
    for (NSUInteger index = 0; index < CC_SHA256_DIGEST_LENGTH; index++) difference |= a[index] ^ b[index];
    return difference == 0;
}
static NSData *ClientMessage(NSData *nonce, NSData *identity, uint8_t operation) {
    NSMutableData *message = [NSMutableData dataWithBytes:"client\0" length:7];
    [message appendData:nonce]; [message appendData:identity]; [message appendBytes:&operation length:1];
    return message;
}
static NSData *ServerMessage(NSData *nonce, uint8_t operation, NSData *body) {
    NSMutableData *message = [NSMutableData dataWithBytes:"server\0" length:7];
    [message appendData:nonce]; [message appendBytes:&operation length:1]; [message appendData:body];
    return message;
}
static BOOL VerifyProtocol(void) {
    // Independent Python hmac.digest vectors for windows/wake.py's wire contract.
    NSData *key = DecodeKey(@"000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f");
    NSData *clientExpected = DecodeKey(@"b60089694a8694effc1a8690a5fc19edb883d8c5f4aa73321baeeecf05801a16");
    NSData *serverExpected = DecodeKey(@"69e1964b14ca11461a06ea488bfec9aaa77a3096d5de31b9af4d710e3c7a1e29");
    uint8_t nonceBytes[32], digest[CC_SHA256_DIGEST_LENGTH];
    for (NSUInteger i = 0; i < sizeof(nonceBytes); i++) nonceBytes[i] = (uint8_t)(i + 32);
    NSData *nonce = [NSData dataWithBytes:nonceBytes length:sizeof(nonceBytes)];
    NSData *identity = [@"0123456789abcdef0123456789abcdef" dataUsingEncoding:NSASCIIStringEncoding];
    NSData *message = ClientMessage(nonce, identity, 1);
    CCHmac(kCCHmacAlgSHA256, key.bytes, key.length, message.bytes, message.length, digest);
    if (!EqualMAC(digest, clientExpected.bytes)) return NO;
    message = ClientMessage(nonce, identity, 0);
    CCHmac(kCCHmacAlgSHA256, key.bytes, key.length, message.bytes, message.length, digest);
    if (EqualMAC(digest, clientExpected.bytes)) return NO;
    NSData *body = [@"{\"status\":\"idle\",\"requestId\":\"001122\"}" dataUsingEncoding:NSUTF8StringEncoding];
    message = ServerMessage(nonce, 1, body);
    CCHmac(kCCHmacAlgSHA256, key.bytes, key.length, message.bytes, message.length, digest);
    if (!EqualMAC(digest, serverExpected.bytes)) return NO;
    digest[31] ^= 1;
    if (EqualMAC(digest, serverExpected.bytes) || DecodeKey(@"bad-key")) return NO;
    return YES;
}
static NSDictionary *State(void) {
    NSDictionary *config = ReadPlist(@"wake.plist", 128 * 1024);
    if (![config[@"version"] isKindOfClass:[NSNumber class]] || [config[@"version"] intValue] != 1 ||
        ![config[@"hosts"] isKindOfClass:[NSDictionary class]] || [config[@"hosts"] count] > 256 ||
        ![config[@"enabled"] isKindOfClass:[NSNumber class]] || ![config[@"paused"] isKindOfClass:[NSNumber class]]) return nil;
    return config;
}
static NSDictionary *Readiness(void) {
    NSDictionary *ready = ReadPlist(@"ready.plist", 4096);
    NSNumber *updated = ready[@"updated"];
    double age = [updated isKindOfClass:[NSNumber class]] ? [NSDate date].timeIntervalSince1970 - updated.doubleValue : 1e9;
    BOOL fresh = age >= 0 && age <= 5;
    BOOL active = fresh && [ready[@"active"] isKindOfClass:[NSNumber class]] && [ready[@"active"] boolValue];
    BOOL connected = fresh && [ready[@"connected"] isKindOfClass:[NSNumber class]] && [ready[@"connected"] boolValue];
    return @{@"active":@(active), @"connected":@(connected)};
}
static void LoadCapabilities(void) {
    void *sbs = dlopen("/System/Library/PrivateFrameworks/SpringBoardServices.framework/SpringBoardServices", RTLD_LAZY | RTLD_LOCAL);
    if (sbs) {
        gSBSLaunch = (SBSLaunch)dlsym(sbs, "SBSLaunchApplicationWithIdentifier");
        gSBServerPort = (SBServerPort)dlsym(sbs, "SBSSpringBoardServerPort");
        gSBLockStatus = (SBLockStatus)dlsym(sbs, "SBGetScreenLockStatus");
    }
    dlopen("/System/Library/Frameworks/MobileCoreServices.framework/MobileCoreServices", RTLD_LAZY | RTLD_LOCAL);
    gWorkspaceClass = NSClassFromString(@"LSApplicationWorkspace");
}
static BOOL WorkspaceAvailable(void) {
    SEL getter = NSSelectorFromString(@"defaultWorkspace");
    SEL opener = NSSelectorFromString(@"openApplicationWithBundleID:");
    if (!gWorkspaceClass || ![gWorkspaceClass respondsToSelector:getter]) return NO;
    NSMethodSignature *factory = [gWorkspaceClass methodSignatureForSelector:getter];
    NSMethodSignature *open = [gWorkspaceClass instanceMethodSignatureForSelector:opener];
    return factory && open && factory.numberOfArguments == 2 && factory.methodReturnType[0] == '@' &&
           open.numberOfArguments == 3 && [open getArgumentTypeAtIndex:2][0] == '@' &&
           (open.methodReturnType[0] == 'v' || open.methodReturnType[0] == 'B' || open.methodReturnType[0] == 'c');
}
static NSDictionary *LaunchNow(void) {
    @try {
        if (gStop) return @{@"status":@"launch_failed", @"reason":@"service_stopping"};
        if (gSBServerPort && gSBLockStatus) {
            mach_port_t port = gSBServerPort();
            if (port == MACH_PORT_NULL) return @{@"status":@"launch_failed", @"reason":@"springboard_not_ready"};
            BOOL locked = NO, passcode = NO;
            gSBLockStatus(port, &locked, &passcode);
            if (locked) return @{@"status":@"locked", @"reason":@"unlock_ipad"};
        }
        int sbsError = 0;
        if (gSBSLaunch) {
            sbsError = gSBSLaunch((__bridge CFStringRef)kBundle, false);
            if (sbsError == 0) return @{@"status":@"launch_requested", @"method":@"SpringBoardServices"};
        }
        // Legacy Theos declares a void return. That only acknowledges submission;
        // Windows must still establish a video session before reporting success.
        if (WorkspaceAvailable()) {
            SEL getter = NSSelectorFromString(@"defaultWorkspace"), opener = NSSelectorFromString(@"openApplicationWithBundleID:");
            id workspace = ((id (*)(id, SEL))objc_msgSend)(gWorkspaceClass, getter);
            if (workspace && [workspace respondsToSelector:opener]) {
                const char *type = [workspace methodSignatureForSelector:opener].methodReturnType;
                if (type[0] == 'v') {
                    ((void (*)(id, SEL, NSString *))objc_msgSend)(workspace, opener, kBundle);
                    return @{@"status":@"launch_requested", @"method":@"LaunchServices", @"confirmed":@NO};
                }
                if (((BOOL (*)(id, SEL, NSString *))objc_msgSend)(workspace, opener, kBundle))
                    return @{@"status":@"launch_requested", @"method":@"LaunchServices"};
            }
        }
        if (!gSBSLaunch && !WorkspaceAvailable()) return @{@"status":@"unsupported", @"reason":@"launch_api_unavailable"};
        return @{@"status":@"launch_failed", @"reason":@"launch_rejected", @"code":@(sbsError)};
    } @catch (NSException *exception) {
        (void)exception;
        return @{@"status":@"launch_failed", @"reason":@"launch_api_exception"};
    }
}
static NSDictionary *RequestLaunch(void) {
    if (dispatch_semaphore_wait(gLaunchSlot, DISPATCH_TIME_NOW) != 0)
        return @{@"status":@"launch_failed", @"reason":@"launch_busy"};
    dispatch_semaphore_t completed = dispatch_semaphore_create(0);
    __block NSDictionary *outcome;
    dispatch_async(gLaunchQueue, ^{
        @autoreleasepool {
            outcome = LaunchNow();
            dispatch_semaphore_signal(completed);
            dispatch_semaphore_signal(gLaunchSlot);
        }
    });
    // At most one private API call can remain outstanding if the OS never replies.
    if (dispatch_semaphore_wait(completed, dispatch_time(DISPATCH_TIME_NOW, NSEC_PER_SEC)) != 0)
        return @{@"status":@"launch_failed", @"reason":@"launch_timeout"};
    return outcome;
}
static NSDictionary *Operate(NSDictionary *config, NSString *identity, uint8_t operation, NSString *requestID) {
    NSDictionary *ready = Readiness();
    if (![config[@"enabled"] boolValue]) return @{@"status":@"paused", @"reason":@"disabled"};
    if (operation > 2) return @{@"status":@"unsupported", @"reason":@"invalid_operation"};
    if ([config[@"paused"] boolValue] && operation != 1) return @{@"status":@"paused", @"reason":@"user_paused"};
    if (operation == 2) return @{@"status":[ready[@"active"] boolValue] ? @"already_active" : @"idle",
                                @"active":ready[@"active"], @"connected":ready[@"connected"]};
    if (operation == 1 && [config[@"paused"] boolValue]) {
        NSMutableDictionary *changed = [config mutableCopy]; changed[@"paused"] = @NO;
        if (!WritePlist(@"wake.plist", changed)) return @{@"status":@"launch_failed", @"reason":@"state_write_failed"};
    }
    NSDictionary *request = @{@"requestId":requestID, @"hostId":identity,
                              @"expires":@([NSDate date].timeIntervalSince1970 + 15), @"force":@(operation == 1)};
    if (!WritePlist(@"request.plist", request)) return @{@"status":@"launch_failed", @"reason":@"request_write_failed"};
    notify_post(kNotification);
    if ([ready[@"active"] boolValue]) return @{@"status":@"already_active", @"connected":ready[@"connected"]};
    return nil; // Release the state lock before invoking any private API.
}
static void Reply(int fd, NSDictionary *value, NSData *key, NSData *nonce, uint8_t operation, NSString *requestID) {
    NSMutableDictionary *response = [value mutableCopy]; response[@"requestId"] = requestID;
    NSData *body = [NSJSONSerialization dataWithJSONObject:response options:0 error:nil];
    if (!body || body.length > 4096) return;
    uint8_t mac[CC_SHA256_DIGEST_LENGTH] = {0};
    if (key) {
        NSData *signedBody = ServerMessage(nonce, operation, body);
        CCHmac(kCCHmacAlgSHA256, key.bytes, key.length, signedBody.bytes, signedBody.length, mac);
    }
    uint32_t length = htonl((uint32_t)body.length);
    double deadline = Monotonic() + 2;
    if (!Transfer(fd, &length, sizeof(length), YES, deadline) ||
        !Transfer(fd, (void *)body.bytes, body.length, YES, deadline)) return;
    Transfer(fd, mac, sizeof(mac), YES, deadline);
}
static void Client(int fd) {
    @autoreleasepool {
        uint8_t challenge[39]; memcpy(challenge, "SHOCKW1", 7);
        NSString *requestID = RandomID();
        if (!requestID || SecRandomCopyBytes(kSecRandomDefault, 32, challenge + 7) != errSecSuccess) return;
        NSData *nonce = [NSData dataWithBytes:challenge + 7 length:32];
        double deadline = Monotonic() + 2;
        if (!Transfer(fd, challenge, sizeof(challenge), YES, deadline)) return;
        uint16_t hostLength;
        if (!Transfer(fd, &hostLength, sizeof(hostLength), NO, deadline) || ntohs(hostLength) != 32) return;
        uint8_t hostBytes[32], operation, received[CC_SHA256_DIGEST_LENGTH];
        if (!Transfer(fd, hostBytes, sizeof(hostBytes), NO, deadline) ||
            !Transfer(fd, &operation, 1, NO, deadline) ||
            !Transfer(fd, received, sizeof(received), NO, deadline)) return;
        NSData *hostData = [NSData dataWithBytes:hostBytes length:sizeof(hostBytes)];
        NSString *identity = [[NSString alloc] initWithData:hostData encoding:NSASCIIStringEncoding];
        if (!IsHex(identity, 32)) return;
        int stateLock = StateLock();
        if (stateLock < 0) { Reply(fd, @{@"status":@"not_paired", @"reason":@"state_unavailable"}, nil, nonce, operation, requestID); return; }
        NSDictionary *config = State();
        id host = config[@"hosts"][identity];
        NSData *key = [host isKindOfClass:[NSDictionary class]] ? DecodeKey(host[@"key"]) : nil;
        if (!key) { Unlock(stateLock); Reply(fd, @{@"status":@"not_paired"}, nil, nonce, operation, requestID); return; }
        uint8_t expected[CC_SHA256_DIGEST_LENGTH];
        NSData *message = ClientMessage(nonce, hostData, operation);
        CCHmac(kCCHmacAlgSHA256, key.bytes, key.length, message.bytes, message.length, expected);
        if (!EqualMAC(expected, received)) {
            Unlock(stateLock); Reply(fd, @{@"status":@"auth_failed"}, key, nonce, operation, requestID); return;
        }
        NSDictionary *result = Operate(config, identity, operation, requestID);
        Unlock(stateLock);
        if (!result) result = RequestLaunch();
        Reply(fd, result, key, nonce, operation, requestID);
    }
}
static BOOL SharedDirectory(void) {
    struct stat st;
    return lstat(kShared.fileSystemRepresentation, &st) == 0 && S_ISDIR(st.st_mode) &&
           st.st_uid == getuid() && (st.st_mode & 0777) == 0700;
}
static NSDictionary *Diagnostics(void) {
    struct passwd *mobile = getpwnam("mobile");
    BOOL correctUser = mobile && getuid() == mobile->pw_uid && geteuid() == mobile->pw_uid;
    // A diagnostic launched from a root shell must not create a root-owned lock
    // inside mobile's state directory and prevent the real service from running.
    int lock = correctUser && SharedDirectory() ? StateLock() : -1;
    NSDictionary *config = lock >= 0 ? State() : nil;
    NSDictionary *ready = lock >= 0 ? Readiness() : @{@"active":@NO, @"connected":@NO};
    Unlock(lock);
    return @{@"version":@1, @"uid":@(getuid()), @"address":@"127.0.0.1", @"port":@(kPort),
             @"bundle":kBundle, @"sbsAvailable":@(gSBSLaunch != NULL),
             @"lockCheckAvailable":@(gSBServerPort != NULL && gSBLockStatus != NULL),
             @"workspaceAvailable":@(WorkspaceAvailable()), @"correctUser":@(correctUser), @"stateAvailable":@(config != nil),
             @"pairedHostCount":@(config ? [config[@"hosts"] count] : 0),
             @"enabled":@([config[@"enabled"] boolValue]), @"paused":@([config[@"paused"] boolValue]),
             @"active":ready[@"active"], @"connected":ready[@"connected"]};
}
int main(int argc, char **argv) {
    @autoreleasepool {
        if (argc == 2 && strcmp(argv[1], "--self-test") == 0) {
            BOOL okay = VerifyProtocol();
            fprintf(okay ? stdout : stderr, "Wake protocol vectors: %s\n", okay ? "OK" : "FAILED");
            return okay ? 0 : 1;
        }
        LoadCapabilities();
        if (argc == 2 && strcmp(argv[1], "--diagnose") == 0) {
            NSData *data = [NSJSONSerialization dataWithJSONObject:Diagnostics() options:NSJSONWritingPrettyPrinted error:nil];
            if (data) fwrite(data.bytes, 1, data.length, stdout);
            fputc('\n', stdout); return data ? 0 : 1;
        }
        if (argc != 1) { fprintf(stderr, "Usage: shockstream-waked [--diagnose|--self-test]\n"); return 2; }
        struct passwd *mobile = getpwnam("mobile");
        if (!mobile || getuid() != mobile->pw_uid || geteuid() != mobile->pw_uid || !SharedDirectory()) {
            fprintf(stderr, "ShockStream wake requires the mobile user and its private state directory.\n"); return 1;
        }
        int instanceLock = OpenLock(@"service.lock");
        if (instanceLock < 0 || flock(instanceLock, LOCK_EX | LOCK_NB) != 0) {
            if (instanceLock >= 0) close(instanceLock);
            fprintf(stderr, "ShockStream wake is already running or its instance lock is unavailable.\n"); return 1;
        }
        signal(SIGTERM, StopSignal); signal(SIGINT, StopSignal); signal(SIGPIPE, SIG_IGN);
        int listener = socket(AF_INET, SOCK_STREAM, 0);
        int yes = 1;
        if (listener >= 0) {
            setsockopt(listener, SOL_SOCKET, SO_REUSEADDR, &yes, sizeof(yes));
            setsockopt(listener, SOL_SOCKET, SO_NOSIGPIPE, &yes, sizeof(yes));
        }
        struct sockaddr_in address = {0}; address.sin_family = AF_INET; address.sin_len = sizeof(address);
        address.sin_port = htons(kPort); address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        if (listener < 0 || listener >= FD_SETSIZE || bind(listener, (struct sockaddr *)&address, sizeof(address)) != 0 || listen(listener, 4) != 0) {
            fprintf(stderr, "ShockStream wake cannot bind its loopback control port (%d).\n", errno);
            if (listener >= 0) close(listener);
            Unlock(instanceLock); return 1;
        }
        int flags = fcntl(listener, F_GETFL, 0);
        if (flags < 0 || fcntl(listener, F_SETFL, flags | O_NONBLOCK) < 0) { close(listener); Unlock(instanceLock); return 1; }
        gClients = [NSMutableSet new];
        gLaunchQueue = dispatch_queue_create("com.shock.stream.wake.launch", DISPATCH_QUEUE_SERIAL);
        gLaunchSlot = dispatch_semaphore_create(1);
        dispatch_semaphore_t slots = dispatch_semaphore_create(4);
        dispatch_group_t workers = dispatch_group_create();
        while (!gStop) {
            @autoreleasepool {
                fd_set set; FD_ZERO(&set); FD_SET(listener, &set); struct timeval wait = {0, 250000};
                int ready = select(listener + 1, &set, NULL, NULL, &wait);
                if (ready < 0 && errno != EINTR) break;
                if (ready > 0 && !gStop) {
                    int fd = accept(listener, NULL, NULL);
                    if (fd >= 0) {
                        int acceptedFlags = fcntl(fd, F_GETFL, 0);
                        if (fd >= FD_SETSIZE || acceptedFlags < 0 || fcntl(fd, F_SETFL, acceptedFlags | O_NONBLOCK) < 0 ||
                            dispatch_semaphore_wait(slots, DISPATCH_TIME_NOW) != 0) { close(fd); }
                        else {
                            setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &yes, sizeof(yes));
                            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
                            pthread_mutex_lock(&gClientsLock); [gClients addObject:@(fd)]; pthread_mutex_unlock(&gClientsLock);
                            dispatch_group_async(workers, dispatch_get_global_queue(DISPATCH_QUEUE_PRIORITY_DEFAULT, 0), ^{
                                Client(fd);
                                pthread_mutex_lock(&gClientsLock); [gClients removeObject:@(fd)]; close(fd); pthread_mutex_unlock(&gClientsLock);
                                dispatch_semaphore_signal(slots);
                            });
                        }
                    }
                }
                CFRunLoopRunInMode(kCFRunLoopDefaultMode, 0.001, true);
            }
        }
        gStop = 1; close(listener);
        pthread_mutex_lock(&gClientsLock);
        for (NSNumber *fd in gClients) shutdown(fd.intValue, SHUT_RDWR);
        pthread_mutex_unlock(&gClientsLock);
        dispatch_group_wait(workers, dispatch_time(DISPATCH_TIME_NOW, 3 * NSEC_PER_SEC));
        Unlock(instanceLock);
    }
    return 0;
}
