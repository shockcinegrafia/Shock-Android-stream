#import "StreamController.h"
#import "StreamConnection.h"
#import "H264Decoder.h"
#import "AudioPlayer.h"
#import "GamepadView.h"
#import "TouchView.h"
#import <AVFoundation/AVFoundation.h>
#import <CoreMedia/CoreMedia.h>

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
@property(nonatomic,strong) StreamConnection *connection;
@property(nonatomic,strong) H264Decoder *decoder;
@property(nonatomic,strong) AudioPlayer *audio;
@property(nonatomic,strong) NSTimer *heartbeat;
@property(nonatomic) BOOL connected;
@end
@implementation StreamController
- (UIColor *)accent { return [UIColor colorWithRed:0.3 green:0.89 blue:0.74 alpha:1]; }
- (void)viewDidLoad {
    [super viewDidLoad];self.view.backgroundColor=[UIColor colorWithRed:0.06 green:0.09 blue:0.13 alpha:1];
    self.video=[AVSampleBufferDisplayLayer layer];self.video.videoGravity=AVLayerVideoGravityResizeAspect;[self.view.layer addSublayer:self.video];
    self.pad=[[GamepadView alloc] initWithFrame:self.view.bounds];self.pad.hidden=YES;[self.view addSubview:self.pad];
    self.touchSurface=[[TouchView alloc] initWithFrame:self.view.bounds];self.touchSurface.hidden=YES;[self.view addSubview:self.touchSurface];
    __weak StreamController *weakSelf=self;
    self.touchSurface.changed=^(NSArray *events){if(weakSelf.connected&&!weakSelf.touchSurface.hidden)[weakSelf.connection sendKind:14 body:[NSJSONSerialization dataWithJSONObject:events options:0 error:nil]];};
    self.pad.changed=^(NSDictionary *state){if(weakSelf.connected&&!weakSelf.pad.hidden)[weakSelf.connection sendPad:state];};
    self.card=[UIView new];self.card.backgroundColor=[UIColor colorWithRed:0.10 green:0.15 blue:0.20 alpha:1];self.card.layer.cornerRadius=20;[self.view addSubview:self.card];
    UILabel *title=[[UILabel alloc] initWithFrame:CGRectMake(24,26,382,42)];title.text=@"SHOCK STREAM";title.textColor=[self accent];title.font=[UIFont boldSystemFontOfSize:29];[self.card addSubview:title];
    UILabel *subtitle=[[UILabel alloc] initWithFrame:CGRectMake(24,76,382,52)];subtitle.text=@"Seu PC. Seu jogo. Seu iPad.\nAbra o host no Windows e informe o IP e PIN.";subtitle.numberOfLines=2;subtitle.textColor=[UIColor lightGrayColor];subtitle.font=[UIFont systemFontOfSize:15];[self.card addSubview:subtitle];
    self.hostField=[self fieldWithPlaceholder:@"IP do PC · exemplo: 192.168.1.20" y:146];
    self.hostField.text=[[NSUserDefaults standardUserDefaults] stringForKey:@"host"];
    self.pinField=[self fieldWithPlaceholder:@"PIN de 6 dígitos" y:246];self.pinField.keyboardType=UIKeyboardTypeNumberPad;
    UIButton *connect=[UIButton buttonWithType:UIButtonTypeSystem];connect.frame=CGRectMake(24,310,382,48);connect.backgroundColor=[self accent];connect.layer.cornerRadius=10;[connect setTitle:@"Conectar e jogar" forState:UIControlStateNormal];[connect setTitleColor:self.view.backgroundColor forState:UIControlStateNormal];connect.titleLabel.font=[UIFont boldSystemFontOfSize:18];[connect addTarget:self action:@selector(connect) forControlEvents:UIControlEventTouchUpInside];[self.card addSubview:connect];self.connectButton=connect;
    self.status=[[UILabel alloc] initWithFrame:CGRectMake(24,375,382,65)];self.status.text=@"Mesma rede Wi-Fi · porta 8090\nGamepad Xbox virtual + vídeo H.264";self.status.numberOfLines=3;self.status.textColor=[UIColor lightGrayColor];self.status.font=[UIFont systemFontOfSize:14];[self.card addSubview:self.status];
    self.disconnectButton=[UIButton buttonWithType:UIButtonTypeSystem];[self.disconnectButton setTitle:@"Desconectar" forState:UIControlStateNormal];[self.disconnectButton setTitleColor:[UIColor whiteColor] forState:UIControlStateNormal];self.disconnectButton.backgroundColor=[UIColor colorWithWhite:0 alpha:0.65];self.disconnectButton.layer.cornerRadius=10;self.disconnectButton.hidden=YES;[self.disconnectButton addTarget:self action:@selector(disconnect) forControlEvents:UIControlEventTouchUpInside];[self.view addSubview:self.disconnectButton];
    [[NSNotificationCenter defaultCenter] addObserver:self selector:@selector(background) name:UIApplicationWillResignActiveNotification object:nil];
}
- (UITextField *)fieldWithPlaceholder:(NSString *)placeholder y:(CGFloat)y {
    UITextField *field=[[UITextField alloc] initWithFrame:CGRectMake(24,y,382,50)];field.placeholder=placeholder;field.backgroundColor=[UIColor whiteColor];field.textColor=[UIColor darkTextColor];field.layer.cornerRadius=8;field.autocorrectionType=UITextAutocorrectionTypeNo;field.autocapitalizationType=UITextAutocapitalizationTypeNone;field.keyboardType=UIKeyboardTypeNumbersAndPunctuation;field.font=[UIFont systemFontOfSize:17];UIView *spacer=[[UIView alloc] initWithFrame:CGRectMake(0,0,12,50)];field.leftView=spacer;field.leftViewMode=UITextFieldViewModeAlways;[self.card addSubview:field];return field;
}
- (void)viewDidLayoutSubviews {
    [super viewDidLayoutSubviews];CGRect bounds=self.view.bounds;
    [CATransaction begin];[CATransaction setDisableActions:YES];self.video.frame=bounds;[CATransaction commit];
    self.touchSurface.frame=bounds;
    self.pad.frame=bounds;[self.pad setNeedsDisplay];self.card.frame=CGRectMake((bounds.size.width-430)/2,(bounds.size.height-460)/2,430,460);
    self.disconnectButton.frame=CGRectMake(bounds.size.width/2-65,15,130,36);
}
- (void)connect {
    if(self.connection){[self disconnect];return;}
    NSString *host=[self.hostField.text stringByTrimmingCharactersInSet:[NSCharacterSet whitespaceAndNewlineCharacterSet]];
    NSString *pin=self.pinField.text;
    if(pin.length!=6||[pin rangeOfCharacterFromSet:[[NSCharacterSet decimalDigitCharacterSet] invertedSet]].location!=NSNotFound){self.status.text=@"Informe o PIN de 6 dígitos exibido no PC.";return;}
    [self.view endEditing:YES];self.status.text=@"Conectando ao PC…";[[NSUserDefaults standardUserDefaults] setObject:host forKey:@"host"];
    StreamConnection *connection=[StreamConnection new];self.connection=connection;self.decoder=[H264Decoder new];
    __weak StreamController *weakSelf=self;__weak StreamConnection *weakConnection=connection;
    self.decoder.frame=^(CVPixelBufferRef image) {
        CVPixelBufferRetain(image);
        dispatch_async(dispatch_get_main_queue(),^{
            StreamController *strongSelf=weakSelf;
            if(strongSelf.connection==weakConnection&&strongSelf.connected){[strongSelf presentImage:image];[weakConnection sendKind:10 body:nil];}
            CVPixelBufferRelease(image);
        });
    };
    self.decoder.failure=^(NSString *reason){dispatch_async(dispatch_get_main_queue(),^{if(weakSelf.connection==weakConnection){[weakSelf disconnect];weakSelf.status.text=reason;}});};
    H264Decoder *decoder=self.decoder;
    connection.received=^(uint8_t kind,NSData *body){
        if(kind==1)[decoder decode:body];
        else if(kind==2){AudioPlayer *audio=weakSelf.audio;if(audio)[audio append:body];}
        else if(kind==3)dispatch_async(dispatch_get_main_queue(),^{
            if(weakSelf.connection!=weakConnection)return;
            NSDictionary *info=[NSJSONSerialization JSONObjectWithData:body options:0 error:nil];
            if([info[@"version"] intValue]!=1){[weakSelf disconnect];weakSelf.status.text=@"Versão de host incompatível";return;}
            BOOL touch=[info[@"mode"] isEqual:@"touch"];
            weakSelf.touchSurface.videoSize=CGSizeMake([info[@"width"] doubleValue],[info[@"height"] doubleValue]);
            weakSelf.connected=YES;weakSelf.card.hidden=YES;weakSelf.pad.hidden=touch;weakSelf.touchSurface.hidden=!touch;weakSelf.disconnectButton.hidden=NO;
            [UIApplication sharedApplication].idleTimerDisabled=YES;
            if([info[@"audio"] boolValue])weakSelf.audio=[AudioPlayer new];
            weakSelf.heartbeat=[NSTimer scheduledTimerWithTimeInterval:0.25 target:weakSelf selector:@selector(keepAlive) userInfo:nil repeats:YES];
            [weakSelf keepAlive];
        });
    };
    connection.ended=^(NSString *reason){dispatch_async(dispatch_get_main_queue(),^{if(weakSelf.connection==weakConnection){[weakSelf disconnect];weakSelf.status.text=reason;}});};
    if(self.mode.selectedSegmentIndex==1)[connection waitUSBWithPIN:pin];
    else [connection connectHost:host port:8090 pin:pin];
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
        // Keep at most the current display submission; decoder ACK paces the host.
        if(!self.video.readyForMoreMediaData)[self.video flush];
        [self.video enqueueSampleBuffer:sample];
    }
    if(sample)CFRelease(sample);if(format)CFRelease(format);
}
- (void)keepAlive {
    if(!self.connected)return;
    if(!self.touchSurface.hidden) {
        NSArray *held=[self.touchSurface held];
        if(held.count)[self.connection sendKind:14 body:[NSJSONSerialization dataWithJSONObject:held options:0 error:nil]];
        else [self.connection sendKind:13 body:nil];
    }else [self.connection sendPad:[self.pad state]];
}
- (void)modeChanged {
    [self disconnect];BOOL usb=self.mode.selectedSegmentIndex==1;self.hostField.hidden=usb;
    [self.connectButton setTitle:usb?@"Aguardar PC pelo USB":@"Conectar e jogar" forState:UIControlStateNormal];
    self.status.text=usb?@"Conecte o cabo, informe o PIN do PC e aguarde.\nO toque controla a tela selecionada no Windows.":@"Informe o IP e o PIN do PC.\nGamepad virtual pela rede Wi-Fi.";
}
- (void)viewWillTransitionToSize:(CGSize)size withTransitionCoordinator:(id<UIViewControllerTransitionCoordinator>)coordinator {
    [self.touchSurface reset];[self.pad neutral];
    [super viewWillTransitionToSize:size withTransitionCoordinator:coordinator];
}
- (void)background { [self disconnect]; }
- (void)disconnect {
    [self.touchSurface reset];[self.pad neutral];self.connected=NO;[self.connection disconnect];self.connection=nil;
    // Decode work finishes on the reader thread; invalidation is safe once the connection ends.
    self.decoder=nil;[self.audio stop];self.audio=nil;
    [self.heartbeat invalidate];self.heartbeat=nil;
    [self.video flushAndRemoveImage];self.card.hidden=NO;self.pad.hidden=YES;self.touchSurface.hidden=YES;self.disconnectButton.hidden=YES;
    self.status.text=@"Desconectado. Abra o host no PC para conectar novamente.";
    [UIApplication sharedApplication].idleTimerDisabled=NO;
}
- (BOOL)prefersStatusBarHidden { return YES; }
- (void)dealloc { [[NSNotificationCenter defaultCenter] removeObserver:self];[self.connection disconnect];[self.heartbeat invalidate]; }
@end
