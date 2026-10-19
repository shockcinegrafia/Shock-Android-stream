#import "StreamController.h"
#import "StreamConnection.h"
#import "RemoteTLS.h"
#import "HostDiscovery.h"
#import "WakeBridge.h"
#import "H264Decoder.h"
#import "AudioPlayer.h"
#import "GamepadView.h"
#import "TouchView.h"
#import <AVFoundation/AVFoundation.h>
#import <CoreMedia/CoreMedia.h>
#include <math.h>
#include <notify.h>

@interface StreamAttempt : NSObject
@property(nonatomic,strong) StreamConnection *connection;
@property(nonatomic,strong) H264Decoder *decoder;
@property(nonatomic,copy) NSString *transport;
@property(nonatomic,copy) NSString *pin;
@property(nonatomic,copy) NSString *hostId;
@property(nonatomic,copy) NSString *addressGroup;
@property(nonatomic,copy) NSString *host;
@property(nonatomic) int port;
@property(nonatomic,strong) NSDictionary *invitation;
@property(nonatomic) NSUInteger sentDisplayId;
@end
@implementation StreamAttempt
@end

@interface StreamController ()
@property(nonatomic,strong) AVSampleBufferDisplayLayer *video;
@property(nonatomic,strong) UIView *card;
@property(nonatomic,strong) UITextField *hostField;
@property(nonatomic,strong) UITextField *pinField;
@property(nonatomic,strong) UILabel *status;
@property(nonatomic,strong) GamepadView *pad;
@property(nonatomic,strong) TouchView *touchSurface;
@property(nonatomic,strong) UISegmentedControl *mode;
@property(nonatomic,strong) UIButton *connectButton;
@property(nonatomic,strong) UIButton *disconnectButton;
@property(nonatomic,strong) UIButton *wakeButton;
@property(nonatomic,strong) UILabel *wakeStatus;
@property(nonatomic,strong) WakeBridge *wakeBridge;
@property(atomic,strong) StreamConnection *connection;
@property(atomic,strong) AudioPlayer *audio;
@property(nonatomic,strong) StreamAttempt *activeAttempt;
@property(nonatomic,strong) HostDiscovery *discovery;
@property(nonatomic,strong) NSMutableDictionary *hosts;
@property(nonatomic,strong) NSMutableDictionary *blockedPins;
@property(nonatomic,strong) NSMutableDictionary *addressOffsets;
@property(nonatomic,strong) NSMutableArray *attempts;
@property(nonatomic,strong) NSTimer *heartbeat;
@property(nonatomic,strong) NSTimer *retry;
@property(nonatomic,copy) NSString *selectedHostId;
@property(nonatomic,copy) NSString *manualPIN;
@property(nonatomic,copy) NSString *controlMode;
@property(nonatomic,strong) NSDictionary *displayInfo;
@property(nonatomic) BOOL connected;
@property(nonatomic) BOOL active;
@property(nonatomic) BOOL autoEnabled;
@property(nonatomic) BOOL awaitingGeometry;
@property(nonatomic) BOOL rotating;
@property(nonatomic) NSUInteger displayId;
@property(nonatomic) BOOL suppressInput;
@property(nonatomic,copy) NSString *lastInputNotice;
@property(nonatomic,copy) NSString *remoteInvitation;
@end

@implementation StreamController
- (UIColor *)accent { return [UIColor colorWithRed:0.3 green:0.89 blue:0.74 alpha:1]; }
- (void)viewDidLoad {
    [super viewDidLoad];
    self.hosts=[NSMutableDictionary new];self.blockedPins=[NSMutableDictionary new];self.addressOffsets=[NSMutableDictionary new];self.attempts=[NSMutableArray new];
    self.autoEnabled=YES;self.active=YES;
    self.view.backgroundColor=[UIColor colorWithRed:0.06 green:0.09 blue:0.13 alpha:1];
    self.video=[AVSampleBufferDisplayLayer layer];self.video.videoGravity=AVLayerVideoGravityResizeAspect;[self.view.layer addSublayer:self.video];
    self.pad=[[GamepadView alloc] initWithFrame:self.view.bounds];self.pad.hidden=YES;[self.view addSubview:self.pad];
    self.touchSurface=[[TouchView alloc] initWithFrame:self.view.bounds];self.touchSurface.hidden=YES;[self.view addSubview:self.touchSurface];
    __weak StreamController *weakSelf=self;
    self.touchSurface.changed=^(NSArray *events){
        if(weakSelf.connected&&!weakSelf.suppressInput&&!weakSelf.rotating&&!weakSelf.awaitingGeometry&&[weakSelf.controlMode isEqual:@"touch"])
            [weakSelf.connection sendKind:14 body:[NSJSONSerialization dataWithJSONObject:events options:0 error:nil]];
    };
    self.pad.changed=^(NSDictionary *state){
        if(weakSelf.connected&&!weakSelf.suppressInput&&!weakSelf.rotating&&!weakSelf.awaitingGeometry&&[weakSelf.controlMode isEqual:@"gamepad"])[weakSelf.connection sendPad:state];
    };
    self.card=[UIView new];self.card.backgroundColor=[UIColor colorWithRed:0.10 green:0.15 blue:0.20 alpha:1];self.card.layer.cornerRadius=20;[self.view addSubview:self.card];
    UILabel *title=[[UILabel alloc] initWithFrame:CGRectMake(24,22,382,42)];title.text=@"SHOCK STREAM";title.textColor=[self accent];title.font=[UIFont boldSystemFontOfSize:29];[self.card addSubview:title];
    UILabel *subtitle=[[UILabel alloc] initWithFrame:CGRectMake(24,72,382,52)];subtitle.text=@"Abra o Shock Stream no PC.\nO iPad encontra o computador automaticamente.";subtitle.numberOfLines=2;subtitle.textColor=[UIColor lightGrayColor];subtitle.font=[UIFont systemFontOfSize:15];[self.card addSubview:subtitle];
    self.mode=[[UISegmentedControl alloc] initWithItems:@[@"Auto",@"Wi-Fi",@"USB",@"Remoto"]];
    self.mode.frame=CGRectMake(24,137,382,38);self.mode.selectedSegmentIndex=0;self.mode.tintColor=[self accent];
    [self.mode addTarget:self action:@selector(modeChanged) forControlEvents:UIControlEventValueChanged];[self.card addSubview:self.mode];
    self.hostField=[self fieldWithPlaceholder:@"IP do PC · busca automática" y:189];
    self.hostField.text=[[NSUserDefaults standardUserDefaults] stringForKey:@"host"];
    self.remoteInvitation=ShockLoadRemoteInvitation();
    self.pinField=[self fieldWithPlaceholder:@"PIN do PC · só no primeiro acesso" y:251];
    self.pinField.keyboardType=UIKeyboardTypeNumberPad;self.pinField.secureTextEntry=YES;
    UIToolbar *keyboardBar=[[UIToolbar alloc] initWithFrame:CGRectMake(0,0,self.view.bounds.size.width,44)];
    keyboardBar.items=@[[[UIBarButtonItem alloc] initWithBarButtonSystemItem:UIBarButtonSystemItemFlexibleSpace target:nil action:nil],[[UIBarButtonItem alloc] initWithTitle:@"Conectar" style:UIBarButtonItemStyleDone target:self action:@selector(connect)]];
    self.hostField.inputAccessoryView=keyboardBar;self.pinField.inputAccessoryView=keyboardBar;
    self.connectButton=[UIButton buttonWithType:UIButtonTypeSystem];self.connectButton.frame=CGRectMake(24,317,382,48);self.connectButton.backgroundColor=[self accent];self.connectButton.layer.cornerRadius=10;
    [self.connectButton setTitle:@"Conectar / emparelhar" forState:UIControlStateNormal];[self.connectButton setTitleColor:self.view.backgroundColor forState:UIControlStateNormal];self.connectButton.titleLabel.font=[UIFont boldSystemFontOfSize:18];
    [self.connectButton addTarget:self action:@selector(connect) forControlEvents:UIControlEventTouchUpInside];[self.card addSubview:self.connectButton];
    self.wakeBridge=[WakeBridge new];
    self.wakeBridge.changed=^{[weakSelf updateWakeUI];};
    self.wakeBridge.wake=^(NSString *hostId){
        if(!weakSelf.active)return;
        weakSelf.selectedHostId=hostId;weakSelf.autoEnabled=YES;[weakSelf.blockedPins removeAllObjects];[weakSelf tryAutomatic];
    };
    self.wakeButton=[UIButton buttonWithType:UIButtonTypeSystem];self.wakeButton.frame=CGRectMake(24,375,382,36);self.wakeButton.tintColor=[self accent];
    [self.wakeButton addTarget:self action:@selector(toggleWake) forControlEvents:UIControlEventTouchUpInside];[self.card addSubview:self.wakeButton];
    UIButton *diagnostic=[UIButton buttonWithType:UIButtonTypeSystem];diagnostic.frame=CGRectMake(24,418,382,30);[diagnostic setTitle:@"Diagnóstico / copiar" forState:UIControlStateNormal];diagnostic.tintColor=[UIColor lightGrayColor];
    [diagnostic addTarget:self action:@selector(showDiagnostic) forControlEvents:UIControlEventTouchUpInside];[self.card addSubview:diagnostic];
    self.status=[[UILabel alloc] initWithFrame:CGRectMake(24,460,382,70)];self.status.text=@"Procurando o PC pelo Wi-Fi…\nJá emparelhado? Conecte o cabo ou aguarde.\nTouch ou gamepad são escolhidos no PC.";self.status.numberOfLines=4;self.status.textColor=[UIColor lightGrayColor];self.status.font=[UIFont systemFontOfSize:14];[self.card addSubview:self.status];
    self.wakeStatus=[[UILabel alloc] initWithFrame:CGRectMake(24,536,382,42)];self.wakeStatus.numberOfLines=2;self.wakeStatus.font=[UIFont systemFontOfSize:12];self.wakeStatus.textColor=[UIColor lightGrayColor];[self.card addSubview:self.wakeStatus];[self updateWakeUI];
    self.disconnectButton=[UIButton buttonWithType:UIButtonTypeSystem];[self.disconnectButton setTitle:@"Desconectar" forState:UIControlStateNormal];[self.disconnectButton setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];self.disconnectButton.backgroundColor=[UIColor colorWithWhite:0 alpha:0.65];self.disconnectButton.layer.cornerRadius=10;self.disconnectButton.hidden=YES;
    [self.disconnectButton addTarget:self action:@selector(disconnect) forControlEvents:UIControlEventTouchUpInside];[self.view addSubview:self.disconnectButton];
    self.discovery=[HostDiscovery new];
    self.discovery.found=^(NSDictionary *host){[weakSelf foundHost:host];};
    self.discovery.failed=^(NSString *reason){if(!weakSelf.connected)weakSelf.status.text=reason;};
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(background) name:UIApplicationWillResignActiveNotification object:nil];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(foreground) name:UIApplicationDidBecomeActiveNotification object:nil];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(didEnterBackground) name:UIApplicationDidEnterBackgroundNotification object:nil];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(orientationChanged) name:UIApplicationDidChangeStatusBarOrientationNotification object:nil];
    [self updateDisplayInfo:self.view.bounds.size];[self foreground];
}
- (void)orientationChanged {
    if(!self.rotating)[self updateDisplayInfo:self.view.bounds.size];
}
- (UITextField *)fieldWithPlaceholder:(NSString *)placeholder y:(CGFloat)y {
    UITextField *field=[[UITextField alloc] initWithFrame:CGRectMake(24,y,382,50)];field.placeholder=placeholder;field.backgroundColor=[UIColor whiteColor];field.textColor=[UIColor darkTextColor];field.layer.cornerRadius=8;field.autocorrectionType=UITextAutocorrectionTypeNo;field.autocapitalizationType=UITextAutocapitalizationTypeNone;field.keyboardType=UIKeyboardTypeNumbersAndPunctuation;field.font=[UIFont systemFontOfSize:17];
    UIView *spacer=[[UIView alloc] initWithFrame:CGRectMake(0,0,12,50)];field.leftView=spacer;field.leftViewMode=UITextFieldViewModeAlways;[self.card addSubview:field];return field;
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];CGRect bounds=self.view.bounds;
    [CATransaction begin];[CATransaction setDisableActions:YES];self.video.frame=bounds;[CATransaction commit];
    self.touchSurface.frame=bounds;self.pad.frame=bounds;[self.pad setNeedsDisplay];
    self.card.frame=CGRectMake((bounds.size.width-430)/2,(bounds.size.height-598)/2,430,598);
    self.disconnectButton.frame=CGRectMake(bounds.size.width/2-65,15,130,36);
    if(!self.rotating)[self updateDisplayInfo:bounds.size];
}
- (void)updateDisplayInfo:(CGSize)size {
    CGFloat scale=[UIScreen mainScreen].scale;
    CGFloat width=size.width*scale,height=size.height*scale;
    if(width<=0||height<=0)return;
    CGFloat cap=MIN(1,1024/MAX(width,height));
    NSNumber *pixelWidth=@((int)lround(width*cap)),*pixelHeight=@((int)lround(height*cap));
    NSInteger orientation=[UIApplication sharedApplication].statusBarOrientation;
    if(orientation<1||orientation>4)return;
    if([self.displayInfo[@"width"] isEqual:pixelWidth]&&[self.displayInfo[@"height"] isEqual:pixelHeight]&&[self.displayInfo[@"orientation"] isEqual:@(orientation)])return;
    self.displayId++;
    NSDictionary *info=@{@"width":pixelWidth,@"height":pixelHeight,@"orientation":@(orientation),@"displayId":@(self.displayId)};
    self.displayInfo=info;
    if(self.connected) {
        [self.touchSurface reset];[self.pad neutral];self.awaitingGeometry=YES;self.touchSurface.hidden=YES;
        [self sendDisplayInfo:self.activeAttempt];
    }
}
- (void)sendDisplayInfo:(StreamAttempt *)attempt {
    if(!attempt||!self.displayInfo||attempt.sentDisplayId==self.displayId)return;
    attempt.sentDisplayId=self.displayId;
    [attempt.connection sendKind:15 body:[NSJSONSerialization dataWithJSONObject:self.displayInfo options:0 error:nil]];
}
- (BOOL)validPIN:(NSString *)pin {
    return pin.length==6&&[pin rangeOfCharacterFromSet:[[NSCharacterSet characterSetWithCharactersInString:@"0123456789"] invertedSet]].location==NSNotFound;
}
- (NSDictionary *)pairings {
    NSDictionary *saved=[[NSUserDefaults standardUserDefaults] dictionaryForKey:@"pairings"];
    return saved?:@{};
}
- (void)foundHost:(NSDictionary *)host {
    NSString *identity=host[@"hostId"];self.hosts[identity]=host;
    if(self.mode.selectedSegmentIndex==3)return;
    NSString *last=[[NSUserDefaults standardUserDefaults] stringForKey:@"lastHostId"];
    if(!self.selectedHostId||[identity isEqual:last]) {
        self.selectedHostId=identity;
        if(!self.hostField.isFirstResponder)self.hostField.text=host[@"host"];
    }
    if(!self.connected&&![self pairings][identity]&&!self.manualPIN)
        self.status.text=[NSString stringWithFormat:@"%@ encontrado.\nInforme o PIN exibido no PC para emparelhar.\nDepois a conexão será automática.",host[@"name"]];
    [self tryAutomatic];
}
- (BOOL)hasAttempt:(NSString *)transport {
    for(StreamAttempt *attempt in self.attempts)if([attempt.transport isEqual:transport])return YES;
    return NO;
}
- (void)tryAutomatic {
    [self.wakeBridge updateActive:self.active connected:self.connected];
    [self.wakeBridge processRequest];
    if(!self.active||!self.autoEnabled||self.connected)return;
    NSDictionary *saved=[self pairings];
    NSString *last=[[NSUserDefaults standardUserDefaults] stringForKey:@"lastHostId"];
    NSInteger mode=self.mode.selectedSegmentIndex;
    if(mode==3) {
        NSDictionary *invitation=ShockRemoteInvitation(self.remoteInvitation);
        if(invitation&&![self hasAttempt:@"remote"])
            [self beginHost:invitation transport:@"remote" pin:invitation[@"key"] expected:nil];
        return;
    }
    // The last authenticated PC is also a fallback if multicast is blocked by the router.
    NSString *selected=self.selectedHostId?:last;
    NSDictionary *host=selected?self.hosts[selected]:nil;
    if(!host&&last) {
        NSDictionary *old=saved[last];
        if([old[@"host"] isKindOfClass:[NSString class]]&&[old[@"host"] length])
            host=@{@"hostId":last,@"host":old[@"host"],@"port":old[@"port"]?:@8090,@"name":old[@"name"]?:@"PC"};
    }
    NSString *manualHost=[self.hostField.text stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    NSArray *discoveredAddresses=host[@"addresses"]?: (host[@"host"]?@[host[@"host"]]:@[]);
    if(self.manualPIN&&manualHost.length&&![discoveredAddresses containsObject:manualHost])
        host=@{@"host":manualHost,@"port":@8090};
    NSString *hostId=host[@"hostId"];
    NSString *wifiPIN=self.manualPIN?:saved[hostId?:@""][@"pin"];
    NSString *usbPIN=self.manualPIN?:saved[last?:@""][@"pin"];
    if(mode!=2&&host&&[self validPIN:wifiPIN]&&![self hasAttempt:@"wifi"])
        [self beginHost:host transport:@"wifi" pin:wifiPIN expected:self.manualPIN?nil:hostId];
    if(mode!=1&&[self validPIN:usbPIN]&&![self hasAttempt:@"usb"])
        [self beginHost:@{} transport:@"usb" pin:usbPIN expected:self.manualPIN?nil:last];
}
- (void)connect {
    if(self.mode.selectedSegmentIndex==3) {
        NSString *value=[self.hostField.text stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
        if(!ShockRemoteInvitation(value)){self.status.text=@"Cole o convite completo criado no PC em Ativar / copiar convite.";return;}
        [self.view endEditing:YES];[self stopConnections];self.remoteInvitation=value;
        self.autoEnabled=YES;[self.blockedPins removeAllObjects];[self tryAutomatic];return;
    }
    NSString *pin=self.pinField.text;
    if(![self validPIN:pin]){self.status.text=@"Informe o PIN de 6 dígitos exibido no PC.";return;}
    [self.view endEditing:YES];[self stopConnections];
    self.manualPIN=pin;self.autoEnabled=YES;[self.blockedPins removeAllObjects];
    self.status.text=@"Procurando o PC pelo Wi-Fi e pelo cabo…";
    [self tryAutomatic];
}
- (void)beginHost:(NSDictionary *)host transport:(NSString *)transport pin:(NSString *)pin expected:(NSString *)identity {
    NSString *address=host[@"host"],*addressGroup=host[@"hostId"];
    NSArray *addresses=host[@"addresses"];
    if(addresses.count&&addressGroup) {
        NSUInteger offset=[self.addressOffsets[addressGroup] unsignedIntegerValue];
        address=nil;
        for(NSUInteger i=0;i<addresses.count;i++) {
            NSString *candidate=addresses[(offset+i)%addresses.count];
            if(![self.blockedPins[candidate] isEqual:pin]){address=candidate;self.addressOffsets[addressGroup]=@((offset+i)%addresses.count);break;}
        }
        if(!address)return;
    }
    NSString *key=[transport isEqual:@"usb"]?@"usb":address;
    if([self.blockedPins[key] isEqual:pin])return;
    StreamAttempt *attempt=[StreamAttempt new];attempt.transport=transport;attempt.pin=pin;attempt.hostId=identity;attempt.addressGroup=addressGroup;attempt.host=address;attempt.port=[host[@"port"] intValue];
    if([transport isEqual:@"remote"])attempt.invitation=host;
    attempt.connection=[StreamConnection new];attempt.decoder=[H264Decoder new];[self.attempts addObject:attempt];
    __weak StreamController *weakSelf=self;__weak StreamAttempt *weakAttempt=attempt;__weak StreamConnection *weakConnection=attempt.connection;
    attempt.connection.authenticated=^{
        // Display geometry must precede the first INFO/frame, including on USB.
        dispatch_sync(dispatch_get_main_queue(),^{
            if([weakSelf.attempts containsObject:weakAttempt])
                [weakSelf sendDisplayInfo:weakAttempt];
        });
    };
    attempt.decoder.frame=^(CVPixelBufferRef image){
        CVPixelBufferRetain(image);
        dispatch_async(dispatch_get_main_queue(),^{
            if(weakSelf.connected&&weakSelf.connection==weakConnection){[weakSelf presentImage:image];[weakConnection sendKind:10 body:nil];}
            CVPixelBufferRelease(image);
        });
    };
    attempt.decoder.failure=^(NSString *reason){dispatch_async(dispatch_get_main_queue(),^{[weakSelf attemptEnded:weakAttempt reason:reason];});};
    attempt.connection.received=^(uint8_t kind,NSData *body){
        if(kind==3) {
            // Serialize selection of the first fully accepted session before decoding its next packet.
            dispatch_sync(dispatch_get_main_queue(),^{[weakSelf acceptInfo:body attempt:weakAttempt];});
        }else if(weakSelf.connection==weakConnection) {
            if(kind==1)[weakAttempt.decoder decode:body];
            else if(kind==2){AudioPlayer *audio=weakSelf.audio;if(audio)[audio append:body];}
            else if(kind==4||kind==16)dispatch_async(dispatch_get_main_queue(),^{
                if(weakSelf.connection!=weakConnection)return;
                if([weakSelf handleNotice:body]||kind==16)return;
                NSString *reason=[[NSString alloc] initWithData:body encoding:NSUTF8StringEncoding];[weakSelf attemptEnded:weakAttempt reason:reason?:@"O PC encerrou a transmissão."];
            });
        }
    };
    attempt.connection.ended=^(NSString *reason){dispatch_async(dispatch_get_main_queue(),^{[weakSelf attemptEnded:weakAttempt reason:reason];});};
    if([transport isEqual:@"usb"])[attempt.connection waitUSBWithPIN:pin];
    else if([transport isEqual:@"remote"])[attempt.connection connectRemote:attempt.invitation];
    else [attempt.connection connectHost:attempt.host port:attempt.port pin:pin];
}
- (void)acceptInfo:(NSData *)body attempt:(StreamAttempt *)attempt {
    if(!attempt||![self.attempts containsObject:attempt])return;
    if(self.activeAttempt&&self.activeAttempt!=attempt){[attempt.connection disconnect];[self.attempts removeObject:attempt];return;}
    id value=[NSJSONSerialization JSONObjectWithData:body options:0 error:nil];
    NSDictionary *info=[value isKindOfClass:[NSDictionary class]]?value:nil;
    NSString *mode=info[@"mode"],*identity=info[@"hostId"];
    NSNumber *width=info[@"width"],*height=info[@"height"],*version=info[@"version"];
    BOOL valid=[version isKindOfClass:[NSNumber class]]&&version.intValue==1&&
        [width isKindOfClass:[NSNumber class]]&&[height isKindOfClass:[NSNumber class]]&&
        width.doubleValue>=2&&width.doubleValue<=1024&&height.doubleValue>=2&&height.doubleValue<=1024&&
        ([mode isEqual:@"touch"]||[mode isEqual:@"gamepad"]);
    if(!valid||(attempt.hostId&&![attempt.hostId isEqual:identity])) {
        [self attemptEnded:attempt reason:@"O PC respondeu com uma sessão incompatível. Atualize os dois aplicativos."];return;
    }
    BOOL changed=!CGSizeEqualToSize(self.touchSurface.videoSize,CGSizeMake(width.doubleValue,height.doubleValue))||![self.controlMode isEqual:mode];
    if(changed){[self.touchSurface reset];[self.pad neutral];[self.video flushAndRemoveImage];}
    NSNumber *confirmedDisplay=info[@"displayId"];
    if((id)confirmedDisplay==[NSNull null])confirmedDisplay=nil;
    BOOL currentDisplay=!confirmedDisplay||([confirmedDisplay isKindOfClass:[NSNumber class]]&&[confirmedDisplay isEqual:self.displayInfo[@"displayId"]]);
    self.activeAttempt=attempt;self.connection=attempt.connection;self.connected=YES;self.controlMode=mode;self.awaitingGeometry=!currentDisplay||self.rotating;
    // Rotation can happen after authentication but before the first session INFO.
    if(!currentDisplay)[self sendDisplayInfo:attempt];
    for(StreamAttempt *other in [self.attempts copy])if(other!=attempt){[other.connection disconnect];[self.attempts removeObject:other];}
    self.touchSurface.videoSize=CGSizeMake(width.doubleValue,height.doubleValue);
    BOOL touch=[mode isEqual:@"touch"];
    self.card.hidden=YES;self.pad.hidden=touch;self.touchSurface.hidden=!touch||!currentDisplay||self.rotating;self.disconnectButton.hidden=touch;
    [UIApplication sharedApplication].idleTimerDisabled=YES;
    if([info[@"audio"] boolValue]){if(!self.audio)self.audio=[AudioPlayer new];}
    else {[self.audio stop];self.audio=nil;}
    if(!self.heartbeat)self.heartbeat=[NSTimer scheduledTimerWithTimeInterval:0.25 target:self selector:@selector(keepAlive) userInfo:nil repeats:YES];
    // A PIN is remembered only after the host identity and session INFO have been accepted.
    if([attempt.transport isEqual:@"remote"]) {
        // Never overwrite the local PIN/USB pairing with an internet access key or public address.
        if(!ShockSaveRemoteInvitation(self.remoteInvitation))NSLog(@"ShockStream: convite remoto não pôde ser salvo no Keychain; cole novamente após reiniciar.");
    }else if([identity isKindOfClass:[NSString class]]&&identity.length&&identity.length<=128) {
        NSMutableDictionary *saved=[[self pairings] mutableCopy];NSMutableDictionary *pair=[saved[identity] mutableCopy]?:[NSMutableDictionary new];
        pair[@"pin"]=attempt.pin;pair[@"name"]=[info[@"name"] isKindOfClass:[NSString class]]?info[@"name"]:@"PC";
        if(attempt.host.length){pair[@"host"]=attempt.host;pair[@"port"]=@(attempt.port);}
        saved[identity]=pair;NSUserDefaults *defaults=[NSUserDefaults standardUserDefaults];[defaults setObject:saved forKey:@"pairings"];[defaults setObject:identity forKey:@"lastHostId"];
        if(attempt.host.length)[defaults setObject:attempt.host forKey:@"host"];
        self.selectedHostId=identity;
        [self.wakeBridge registerHost:identity key:info[@"wakeKey"]];
    }
    [self.wakeBridge updateActive:self.active connected:YES];
    self.manualPIN=nil;self.pinField.text=@"";[self keepAlive];
}
- (void)attemptEnded:(StreamAttempt *)attempt reason:(NSString *)reason {
    if(!attempt||![self.attempts containsObject:attempt])return;
    BOOL badPIN=reason&&[reason rangeOfString:@"PIN incorreto"].location!=NSNotFound;
    if(badPIN) {
        self.blockedPins[[attempt.transport isEqual:@"usb"]?@"usb":attempt.host]=attempt.pin;
        self.manualPIN=nil;
    }
    if(!badPIN&&attempt.addressGroup)self.addressOffsets[attempt.addressGroup]=@([self.addressOffsets[attempt.addressGroup] unsignedIntegerValue]+1);
    if(self.activeAttempt==attempt)[self clearSession];
    [attempt.connection disconnect];[self.attempts removeObject:attempt];
    if(!self.connected&&self.active) {
        self.status.text=badPIN?@"PIN recusado. Informe o PIN atual exibido no PC para emparelhar novamente.":[NSString stringWithFormat:@"%@\nTentando reconectar automaticamente…",reason?:@"Conexão encerrada"];
    }
}
- (void)presentImage:(CVPixelBufferRef)image {
    CMVideoFormatDescriptionRef format=NULL;CMSampleBufferRef sample=NULL;
    OSStatus status=CMVideoFormatDescriptionCreateForImageBuffer(kCFAllocatorDefault,image,&format);
    CMSampleTimingInfo timing={kCMTimeInvalid,kCMTimeZero,kCMTimeInvalid};
    if(status==noErr)status=CMSampleBufferCreateReadyWithImageBuffer(kCFAllocatorDefault,image,format,&timing,&sample);
    if(status==noErr) {
        CFArrayRef attachments=CMSampleBufferGetSampleAttachmentsArray(sample,YES);
        if(attachments&&CFArrayGetCount(attachments))CFDictionarySetValue((CFMutableDictionaryRef)CFArrayGetValueAtIndex(attachments,0),kCMSampleAttachmentKey_DisplayImmediately,kCFBooleanTrue);
        if(self.video.status==AVQueuedSampleBufferRenderingStatusFailed)[self.video flush];
        if(!self.video.readyForMoreMediaData)[self.video flush];
        [self.video enqueueSampleBuffer:sample];
    }
    if(sample)CFRelease(sample);if(format)CFRelease(format);
}
- (void)keepAlive {
    if(!self.connected)return;
    if(self.rotating||self.awaitingGeometry){[self.connection sendKind:13 body:nil];return;}
    if([self.controlMode isEqual:@"touch"]) {
        NSArray *held=[self.touchSurface held];
        if(held.count&&!self.awaitingGeometry)[self.connection sendKind:14 body:[NSJSONSerialization dataWithJSONObject:held options:0 error:nil]];
        else [self.connection sendKind:13 body:nil];
    }else [self.connection sendPad:[self.pad state]];
}
- (BOOL)handleNotice:(NSData *)body {
    id value=[NSJSONSerialization JSONObjectWithData:body options:0 error:nil];
    if(![value isKindOfClass:[NSDictionary class]])return NO;
    NSDictionary *notice=value;
    if(![notice[@"scope"] isEqual:@"input"]||![notice[@"recoverable"] isEqual:@YES])return NO;
    self.suppressInput=YES;[self.touchSurface reset];[self.pad neutral];self.suppressInput=NO;
    NSString *message=[notice[@"message"] isKindOfClass:[NSString class]]?notice[@"message"]:@"O Windows recusou um toque. Tente novamente.";
    if(message.length>240)message=[message substringToIndex:240];
    if(![self.lastInputNotice isEqual:message]){self.lastInputNotice=message;NSLog(@"ShockStream input: %@",message);self.status.text=message;}
    return YES;
}
- (void)updateWakeUI {
    self.wakeButton.hidden=!self.wakeBridge.installed;
    [self.wakeButton setTitle:self.wakeBridge.enabled?@"Desativar abertura USB automática":@"Ativar abertura USB automática" forState:UIControlStateNormal];
    self.wakeStatus.text=self.wakeBridge.lastError?: (self.wakeBridge.installed?(self.wakeBridge.enabled?@"Abertura USB ativada. Ao sair pelo Home ela será pausada.":@"O primeiro pareamento com o PC ativa a abertura USB."):@"Para abrir o app pelo cabo, instale a versão .deb.");
}
- (void)toggleWake { [self.wakeBridge setEnabled:!self.wakeBridge.enabled];[self updateWakeUI]; }
- (void)showDiagnostic {
    NSString *summary=[NSString stringWithFormat:@"%@\nÚltimo aviso de toque: %@",[self.wakeBridge diagnostic],self.lastInputNotice?:@"nenhum"];
    UIAlertController *alert=[UIAlertController alertControllerWithTitle:@"Diagnóstico" message:summary preferredStyle:UIAlertControllerStyleAlert];
    [alert addAction:[UIAlertAction actionWithTitle:@"Copiar" style:UIAlertActionStyleDefault handler:^(UIAlertAction *action){(void)action;[UIPasteboard generalPasteboard].string=summary;}]];
    [alert addAction:[UIAlertAction actionWithTitle:@"Fechar" style:UIAlertActionStyleCancel handler:nil]];[self presentViewController:alert animated:YES completion:nil];
}
- (void)modeChanged {
    [self stopConnections];self.autoEnabled=YES;[self.blockedPins removeAllObjects];
    self.hostField.hidden=self.mode.selectedSegmentIndex==2;
    BOOL remote=self.mode.selectedSegmentIndex==3;self.pinField.hidden=remote;
    self.hostField.placeholder=remote?@"Cole o convite shockstream://…":@"IP do PC · busca automática";
    self.hostField.text=remote?self.remoteInvitation:[[NSUserDefaults standardUserDefaults] stringForKey:@"host"];
    if(remote){self.status.text=@"No Windows, ative o acesso remoto e copie o convite.\nRequer endereço público com porta encaminhada ou túnel TCP.";[self tryAutomatic];return;}
    self.status.text=@"Procurando o PC…\nNo primeiro acesso, informe o PIN exibido no Windows.";[self tryAutomatic];
}
- (void)viewWillTransitionToSize:(CGSize)size withTransitionCoordinator:(id<UIViewControllerTransitionCoordinator>)coordinator {
    [self.touchSurface reset];[self.pad neutral];self.rotating=YES;
    self.awaitingGeometry=YES;self.touchSurface.hidden=YES;
    [super viewWillTransitionToSize:size withTransitionCoordinator:coordinator];
    __weak StreamController *weakSelf=self;
    [coordinator animateAlongsideTransition:nil completion:^(id<UIViewControllerTransitionCoordinatorContext> context){
        (void)context;weakSelf.rotating=NO;
        // Commit final size and orientation together, including a cancelled transition.
        weakSelf.displayInfo=nil;[weakSelf updateDisplayInfo:weakSelf.view.bounds.size];
    }];
}
- (void)foreground {
    self.active=YES;self.autoEnabled=YES;[self.discovery start];
    [self.wakeBridge updateActive:YES connected:self.connected];[self.wakeBridge setPaused:NO];[self.wakeBridge processRequest];
    if(!self.retry)self.retry=[NSTimer scheduledTimerWithTimeInterval:2 target:self selector:@selector(tryAutomatic) userInfo:nil repeats:YES];
    [self tryAutomatic];
}
- (void)background {
    [self.wakeBridge setPaused:YES];[self.wakeBridge updateActive:NO connected:NO];
    self.active=NO;[self.discovery stop];[self.hosts removeAllObjects];
    [self.retry invalidate];self.retry=nil;[self stopConnections];
}
- (void)didEnterBackground {
    int token=-1;uint64_t locked=0;BOOL known=NO;
    if(notify_register_check("com.apple.springboard.lockstate",&token)==NOTIFY_STATUS_OK){known=notify_get_state(token,&locked)==NOTIFY_STATUS_OK;notify_cancel(token);}
    // A confirmed screen lock may resume after unlock; Home/unknown state remains paused.
    if(known&&locked&&self.wakeBridge.enabled)[self.wakeBridge setPaused:NO];
}
- (void)clearSession {
    [self.touchSurface reset];[self.pad neutral];self.connected=NO;self.connection=nil;self.activeAttempt=nil;self.controlMode=nil;self.awaitingGeometry=NO;
    [self.audio stop];self.audio=nil;[self.heartbeat invalidate];self.heartbeat=nil;
    [self.video flushAndRemoveImage];self.card.hidden=NO;self.pad.hidden=YES;self.touchSurface.hidden=YES;self.disconnectButton.hidden=YES;
    [UIApplication sharedApplication].idleTimerDisabled=NO;
    [self.wakeBridge updateActive:self.active connected:NO];
}
- (void)stopConnections {
    [self clearSession];
    for(StreamAttempt *attempt in self.attempts)[attempt.connection disconnect];
    [self.attempts removeAllObjects];
}
- (void)disconnect {
    self.autoEnabled=NO;self.manualPIN=nil;[self stopConnections];
    [self.wakeBridge setPaused:YES];
    self.status.text=@"Desconectado. Toque em Conectar para retomar.";
}
- (BOOL)prefersStatusBarHidden { return YES; }
- (void)dealloc {
    [self.wakeBridge stop];
    [[NSNotificationCenter defaultCenter] removeObserver:self];[self.discovery stop];
    for(StreamAttempt *attempt in self.attempts)[attempt.connection disconnect];
    [self.heartbeat invalidate];[self.retry invalidate];
}
@end
