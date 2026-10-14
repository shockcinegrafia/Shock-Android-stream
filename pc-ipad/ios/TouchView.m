#import "TouchView.h"
@interface TouchView ()
@property(nonatomic,strong) NSMapTable *contacts;
@property(nonatomic,strong) NSMutableDictionary *positions;
@end
@implementation TouchView
- (instancetype)initWithFrame:(CGRect)frame {
    if((self=[super initWithFrame:frame])) {
        self.multipleTouchEnabled=YES;self.backgroundColor=[UIColor clearColor];
        _contacts=[NSMapTable strongToStrongObjectsMapTable];_positions=[NSMutableDictionary new];
    }return self;
}
- (CGRect)imageRect {
    if(self.videoSize.width<=0||self.videoSize.height<=0)return CGRectZero;
    CGFloat scale=MIN(self.bounds.size.width/self.videoSize.width,self.bounds.size.height/self.videoSize.height);
    CGSize size=CGSizeMake(self.videoSize.width*scale,self.videoSize.height*scale);
    return CGRectMake((self.bounds.size.width-size.width)/2,(self.bounds.size.height-size.height)/2,size.width,size.height);
}
- (NSDictionary *)eventForTouch:(UITouch *)touch action:(NSString *)action ident:(NSNumber *)ident {
    CGRect r=[self imageRect];CGPoint p=[touch locationInView:self];
    CGFloat x=MAX(0,MIN(1,(p.x-r.origin.x)/r.size.width)),y=MAX(0,MIN(1,(p.y-r.origin.y)/r.size.height));
    NSDictionary *event=@{@"id":ident,@"a":action,@"x":@(x),@"y":@(y)};
    self.positions[ident]=event;return event;
}
- (void)touchesBegan:(NSSet *)touches withEvent:(UIEvent *)event {
    (void)event;NSMutableArray *events=[NSMutableArray new];CGRect r=[self imageRect];
    for(UITouch *touch in touches) {
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
    if(events.count&&self.changed)self.changed(events);
}
@end
