#import "PairingScanner.h"
#import "RemoteTLS.h"
#import <AVFoundation/AVFoundation.h>
@interface PairingScanner () <AVCaptureMetadataOutputObjectsDelegate>
@property(nonatomic,strong) AVCaptureSession *capture;
@property(nonatomic,strong) AVCaptureVideoPreviewLayer *preview;
@property(nonatomic,strong) UILabel *message;
@property(nonatomic) BOOL finished;
@end
@implementation PairingScanner
- (void)viewDidLoad {
    [super viewDidLoad];self.view.backgroundColor=[UIColor blackColor];
    self.message=[[UILabel alloc] initWithFrame:CGRectMake(24,70,500,70)];self.message.text=@"Aponte para o QR de emparelhamento no PC.";self.message.textColor=[UIColor whiteColor];self.message.numberOfLines=3;[self.view addSubview:self.message];
    UIButton *close=[UIButton buttonWithType:UIButtonTypeSystem];close.frame=CGRectMake(20,20,100,44);[close setTitle:@"Cancelar" forState:UIControlStateNormal];[close addTarget:self action:@selector(cancel) forControlEvents:UIControlEventTouchUpInside];[self.view addSubview:close];
    __weak PairingScanner *weakSelf=self;
    [AVCaptureDevice requestAccessForMediaType:AVMediaTypeVideo completionHandler:^(BOOL allowed){
        dispatch_async(dispatch_get_main_queue(),^{
            if(weakSelf.finished)return;
            if(allowed)[weakSelf prepareCamera];else weakSelf.message.text=@"Câmera não autorizada. Cancele e cole o convite no campo Remoto.";
        });
    }];
}
- (void)prepareCamera {
    AVCaptureDevice *device=[AVCaptureDevice defaultDeviceWithMediaType:AVMediaTypeVideo];NSError *error=nil;
    AVCaptureDeviceInput *input=device?[AVCaptureDeviceInput deviceInputWithDevice:device error:&error]:nil;
    self.capture=[AVCaptureSession new];AVCaptureMetadataOutput *output=[AVCaptureMetadataOutput new];
    if(!input||![self.capture canAddInput:input]||![self.capture canAddOutput:output]){self.message.text=@"Câmera indisponível. Cancele e cole o convite.";return;}
    [self.capture addInput:input];[self.capture addOutput:output];
    if(![output.availableMetadataObjectTypes containsObject:AVMetadataObjectTypeQRCode]){self.message.text=@"Leitura de QR indisponível. Cole o convite.";return;}
    [output setMetadataObjectsDelegate:self queue:dispatch_get_main_queue()];output.metadataObjectTypes=@[AVMetadataObjectTypeQRCode];
    self.preview=[AVCaptureVideoPreviewLayer layerWithSession:self.capture];self.preview.videoGravity=AVLayerVideoGravityResizeAspectFill;self.preview.frame=self.view.bounds;[self.view.layer insertSublayer:self.preview atIndex:0];
    [self.capture startRunning];
}
- (void)viewDidLayoutSubviews {[super viewDidLayoutSubviews];self.preview.frame=self.view.bounds;}
- (void)captureOutput:(AVCaptureOutput *)output didOutputMetadataObjects:(NSArray *)objects fromConnection:(AVCaptureConnection *)connection {
    (void)output;(void)connection;
    if(self.finished)return;
    for(AVMetadataObject *object in objects)if([object isKindOfClass:[AVMetadataMachineReadableCodeObject class]]) {
        NSString *value=[(AVMetadataMachineReadableCodeObject *)object stringValue];
        if(!ShockRemoteInvitation(value)){self.message.text=@"Este QR não é um convite Shock Stream válido.";continue;}
        self.finished=YES;[self.capture stopRunning];
        [self dismissViewControllerAnimated:YES completion:^{if(self.scanned)self.scanned(value);}];return;
    }
}
- (void)cancel {self.finished=YES;[self.capture stopRunning];[self dismissViewControllerAnimated:YES completion:nil];}
- (void)viewDidDisappear:(BOOL)animated {[super viewDidDisappear:animated];[self.capture stopRunning];}
@end
