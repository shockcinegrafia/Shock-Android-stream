#import "TouchView.h"
#include <math.h>
@interface TouchView ()
@property(nonatomic,strong) NSMapTable *contacts;
@property(nonatomic,strong) NSMutableDictionary *positions;
@property(nonatomic) CGRect gestureRect;
@property(nonatomic) CGSize gestureBounds;
@end
@implementation TouchView
@synthesize videoSize=_videoSize;
- (instancetype)initWithFrame:(CGRect)frame {
    if((self=[super initWithFrame:frame])) {
        self.multipleTouchEnabled=YES;self.backgroundColor=[UIColor clearColor];
        _contacts=[[NSMapTable alloc] initWithKeyOptions:NSPointerFunctionsStrongMemory|NSPointerFunctionsObjectPointerPersonality valueOptions:NSPointerFunctionsStrongMemory capacity:10];
        _positions=[NSMutableDictionary new];
    }return self;
}
- (CGRect)imageRect {
    if(!isfinite(self.videoSize.width)||!isfinite(self.videoSize.height)||self.videoSize.width<=0||self.videoSize.height<=0||self.bounds.size.width<=0||self.bounds.size.height<=0)return CGRectZero;
    CGFloat scale=MIN(self.bounds.size.width/self.videoSize.width,self.bounds.size.height/self.videoSize.height);
    CGSize size=CGSizeMake(self.videoSize.width*scale,self.videoSize.height*scale);
    return CGRectMake((self.bounds.size.width-size.width)/2,(self.bounds.size.height-size.height)/2,size.width,size.height);
}
- (void)setVideoSize:(CGSize)size {
    if(!CGSizeEqualToSize(_videoSize,size))[self reset];
    _videoSize=size;
}
- (void)layoutSubviews {
    [super layoutSubviews];
    if(self.positions.count&&!CGSizeEqualToSize(self.gestureBounds,self.bounds.size))[self reset];
}
- (NSDictionary *)eventForTouch:(UITouch *)touch action:(NSString *)action ident:(NSNumber *)ident {
    CGRect r=self.gestureRect;CGPoint p=[touch locationInView:self];
    NSDictionary *previous=self.positions[ident];
    CGFloat x=previous?[previous[@"x"] doubleValue]:0.5,y=previous?[previous[@"y"] doubleValue]:0.5;
    if(!CGRectIsEmpty(r)&&isfinite(p.x)&&isfinite(p.y)) {
        x=MAX(0,MIN(1,(p.x-r.origin.x)/r.size.width));y=MAX(0,MIN(1,(p.y-r.origin.y)/r.size.height));
    }
    NSDictionary *event=@{@"id":ident,@"a":action,@"x":@(x),@"y":@(y)};
    self.positions[ident]=event;return event;
}
- (void)touchesBegan:(NSSet *)touches withEvent:(UIEvent *)event {
    (void)event;NSMutableArray *events=[NSMutableArray new];CGRect r=[self imageRect];
    if(!self.positions.count){self.gestureRect=r;self.gestureBounds=self.bounds.size;}
    for(UITouch *touch in touches) {
        if([self.contacts objectForKey:touch])continue;
        if(CGRectIsEmpty(r)||!CGRectContainsPoint(r,[touch locationInView:self]))continue;
        NSNumber *ident=nil;
        for(int i=0;i<10;i++)if(!self.positions[@(i)]){ident=@(i);break;}
        if(!ident)continue;
        [self.contacts setObject:ident forKey:touch];[events addObject:[self eventForTouch:touch action:@"down" ident:ident]];
    }
    if(events.count&&self.changed)self.changed(events);
}
- (void)handle:(NSSet *)touches action:(NSString *)action {
    NSMutableArray *events=[NSMutableArray new];
    for(UITouch *touch in touches) {
        NSNumber *ident=[self.contacts objectForKey:touch];if(!ident)continue;
        [events addObject:[self eventForTouch:touch action:action ident:ident]];
        if([action isEqual:@"up"]||[action isEqual:@"cancel"]){[self.contacts removeObjectForKey:touch];[self.positions removeObjectForKey:ident];}
    }
    if(events.count&&self.changed)self.changed(events);
}
- (void)touchesMoved:(NSSet *)touches withEvent:(UIEvent *)event { (void)event;[self handle:touches action:@"move"]; }
- (void)touchesEnded:(NSSet *)touches withEvent:(UIEvent *)event { (void)event;[self handle:touches action:@"up"]; }
- (void)touchesCancelled:(NSSet *)touches withEvent:(UIEvent *)event { (void)event;[self handle:touches action:@"cancel"]; }
- (NSArray *)held {
    NSMutableArray *events=[NSMutableArray new];
    for(NSNumber *ident in self.positions){NSMutableDictionary *item=[self.positions[ident] mutableCopy];item[@"a"]=@"hold";[events addObject:item];}
    return events;
}
- (void)reset {
    NSMutableArray *events=[NSMutableArray new];
    for(NSNumber *ident in self.positions){NSMutableDictionary *item=[self.positions[ident] mutableCopy];item[@"a"]=@"cancel";[events addObject:item];}
    [self.positions removeAllObjects];[self.contacts removeAllObjects];
    self.gestureRect=CGRectZero;
    if(events.count&&self.changed)self.changed(events);
}
@end
