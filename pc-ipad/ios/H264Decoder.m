#import "H264Decoder.h"
#import <VideoToolbox/VideoToolbox.h>
#import <CoreMedia/CoreMedia.h>
#include <arpa/inet.h>
@interface H264Decoder () {
    VTDecompressionSessionRef _session;
    CMVideoFormatDescriptionRef _format;
}
@property(nonatomic,strong) NSData *sps;
@property(nonatomic,strong) NSData *pps;
@end
@implementation H264Decoder
static void decoded(void *ref,void *source,OSStatus status,VTDecodeInfoFlags flags,CVImageBufferRef image,CMTime pts,CMTime duration) {
    (void)source;(void)flags;(void)pts;(void)duration;
    H264Decoder *decoder=(__bridge H264Decoder *)ref;
    if(status==noErr&&image&&decoder.frame)decoder.frame(image);
    else if(decoder.failure)decoder.failure([NSString stringWithFormat:@"Falha ao decodificar H.264 (%d)",(int)status]);
}
static size_t startCode(const uint8_t *p,size_t n,size_t i) {
    if(i+3<=n&&p[i]==0&&p[i+1]==0&&p[i+2]==1)return 3;
    if(i+4<=n&&p[i]==0&&p[i+1]==0&&p[i+2]==0&&p[i+3]==1)return 4;
    return 0;
}
- (void)decode:(NSData *)packet {
    const uint8_t *p=packet.bytes;size_t length=packet.length;
    NSMutableData *sample=[NSMutableData new];
    BOOL changed=NO;
    size_t i=0;
    while(i<length) {
        size_t prefix=startCode(p,length,i);if(!prefix){i++;continue;}
        size_t begin=i+prefix,end=begin;
        while(end<length&&!startCode(p,length,end))end++;
        if(end>begin) {
            NSData *nal=[NSData dataWithBytes:p+begin length:end-begin];uint8_t type=p[begin]&31;
            if(type==7){if(![self.sps isEqual:nal])changed=YES;self.sps=nal;}
            else if(type==8){if(![self.pps isEqual:nal])changed=YES;self.pps=nal;}
            else if(type==1||type==5){uint32_t size=htonl((uint32_t)nal.length);[sample appendBytes:&size length:4];[sample appendData:nal];}
        }
        i=end;
    }
    if(changed)[self stop];
    if(!_session&&self.sps&&self.pps) {
        const uint8_t *parameters[]={self.sps.bytes,self.pps.bytes};size_t sizes[]={self.sps.length,self.pps.length};
        OSStatus status=CMVideoFormatDescriptionCreateFromH264ParameterSets(kCFAllocatorDefault,2,parameters,sizes,4,&_format);
        if(status==noErr) {
            VTDecompressionOutputCallbackRecord output={decoded,(__bridge void *)self};
            NSDictionary *attributes=@{(NSString *)kCVPixelBufferPixelFormatTypeKey:@(kCVPixelFormatType_420YpCbCr8BiPlanarVideoRange)};
            status=VTDecompressionSessionCreate(kCFAllocatorDefault,_format,NULL,(__bridge CFDictionaryRef)attributes,&output,&_session);
        }
        if(status!=noErr){if(self.failure)self.failure([NSString stringWithFormat:@"Decoder indisponível (%d)",(int)status]);return;}
    }
    if(!_session||!sample.length){if(self.failure)self.failure(@"Frame H.264 inválido");return;}
    CMBlockBufferRef block=NULL;CMSampleBufferRef buffer=NULL;
    OSStatus status=CMBlockBufferCreateWithMemoryBlock(kCFAllocatorDefault,NULL,sample.length,kCFAllocatorDefault,NULL,0,sample.length,0,&block);
    if(status==noErr)status=CMBlockBufferReplaceDataBytes(sample.bytes,block,0,sample.length);
    size_t size=sample.length;
    CMSampleTimingInfo timing={kCMTimeInvalid,kCMTimeZero,kCMTimeInvalid};
    if(status==noErr)status=CMSampleBufferCreateReady(kCFAllocatorDefault,block,_format,1,1,&timing,1,&size,&buffer);
    if(status==noErr)status=VTDecompressionSessionDecodeFrame(_session,buffer,kVTDecodeFrame_EnableAsynchronousDecompression,NULL,NULL);
    if(buffer)CFRelease(buffer);if(block)CFRelease(block);
    if(status!=noErr&&self.failure)self.failure([NSString stringWithFormat:@"Frame recusado (%d)",(int)status]);
}
- (void)stop {
    if(_session){VTDecompressionSessionWaitForAsynchronousFrames(_session);VTDecompressionSessionInvalidate(_session);CFRelease(_session);_session=NULL;}
    if(_format){CFRelease(_format);_format=NULL;}
}
- (void)dealloc { [self stop]; }
@end
