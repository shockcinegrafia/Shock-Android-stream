#import "AudioPlayer.h"
#import <AudioToolbox/AudioToolbox.h>
#import <AVFoundation/AVFoundation.h>
@interface AudioPlayer () {
    AudioQueueRef _queue;
}
@property(nonatomic,strong) NSMutableData *pending;
@property(nonatomic,strong) NSLock *lock;
@end
@implementation AudioPlayer
static void audioCallback(void *ref,AudioQueueRef queue,AudioQueueBufferRef buffer) {
    AudioPlayer *player=(__bridge AudioPlayer *)ref;
    [player.lock lock];
    NSUInteger amount=MIN(2048,player.pending.length);
    memset(buffer->mAudioData,0,2048);
    if(amount){memcpy(buffer->mAudioData,player.pending.bytes,amount);[player.pending replaceBytesInRange:NSMakeRange(0,amount) withBytes:NULL length:0];}
    [player.lock unlock];buffer->mAudioDataByteSize=2048;AudioQueueEnqueueBuffer(queue,buffer,0,NULL);
}
- (instancetype)init {
    if((self=[super init])) {
        _pending=[NSMutableData new];_lock=[NSLock new];
        [[AVAudioSession sharedInstance] setCategory:AVAudioSessionCategoryPlayback error:nil];
        [[AVAudioSession sharedInstance] setActive:YES error:nil];
        AudioStreamBasicDescription format={0};format.mSampleRate=44100;format.mFormatID=kAudioFormatLinearPCM;
        format.mFormatFlags=kLinearPCMFormatFlagIsSignedInteger|kAudioFormatFlagIsPacked;
        format.mBytesPerPacket=4;format.mFramesPerPacket=1;format.mBytesPerFrame=4;format.mChannelsPerFrame=2;format.mBitsPerChannel=16;
        if(AudioQueueNewOutput(&format,audioCallback,(__bridge void *)self,NULL,NULL,0,&_queue)==noErr) {
            for(int i=0;i<3;i++){AudioQueueBufferRef buffer;AudioQueueAllocateBuffer(_queue,2048,&buffer);memset(buffer->mAudioData,0,2048);buffer->mAudioDataByteSize=2048;AudioQueueEnqueueBuffer(_queue,buffer,0,NULL);}
            AudioQueueStart(_queue,NULL);
        }
    } return self;
}
- (void)append:(NSData *)pcm {
    if(pcm.length%4||pcm.length>8192)return;
    [self.lock lock];
    if(self.pending.length+pcm.length>6144)[self.pending setLength:0];
    [self.pending appendData:pcm];[self.lock unlock];
}
- (void)stop { if(_queue){AudioQueueStop(_queue,true);AudioQueueDispose(_queue,true);_queue=NULL;} }
- (void)dealloc { [self stop]; }
@end
