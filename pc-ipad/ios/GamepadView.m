#import "GamepadView.h"
#include <math.h>
@interface GamepadView ()
@property(nonatomic,strong) NSMapTable *touches;
@property(nonatomic,strong) NSDictionary *snapshot;
@end
@implementation GamepadView
- (instancetype)initWithFrame:(CGRect)frame {
    if((self=[super initWithFrame:frame])) {
        self.backgroundColor=[UIColor clearColor];self.multipleTouchEnabled=YES;
        _touches=[NSMapTable strongToStrongObjectsMapTable];[self neutral];
    }return self;
}
- (CGPoint)centerForZone:(NSInteger)zone {
    CGFloat w=self.bounds.size.width,h=self.bounds.size.height;
    switch(zone) {
        case 100:return CGPointMake(105,h-115);
        case 101:return CGPointMake(w-290,h-110);
        case 0x1000:return CGPointMake(w-100,h-65);
        case 0x2000:return CGPointMake(w-42,h-120);
        case 0x4000:return CGPointMake(w-158,h-120);
        case 0x8000:return CGPointMake(w-100,h-175);
        case 1:return CGPointMake(280,h-145);
        case 2:return CGPointMake(280,h-45);
        case 4:return CGPointMake(230,h-95);
        case 8:return CGPointMake(330,h-95);
        case 0x100:return CGPointMake(70,75);
        case 0x200:return CGPointMake(w-70,75);
        case 200:return CGPointMake(170,75);
        case 201:return CGPointMake(w-170,75);
        case 0x20:return CGPointMake(w/2-55,75);
        case 0x10:return CGPointMake(w/2+55,75);
        case 0x40:return CGPointMake(105,h-235);
        case 0x80:return CGPointMake(w-290,h-215);
    }return CGPointZero;
}
- (NSArray *)zones { return @[@100,@101,@0x1000,@0x2000,@0x4000,@0x8000,@1,@2,@4,@8,@0x100,@0x200,@200,@201,@0x20,@0x10,@0x40,@0x80]; }
- (NSInteger)zoneAt:(CGPoint)p {
    for(NSNumber *number in [self zones]) {
        NSInteger zone=number.integerValue;CGPoint c=[self centerForZone:zone];
        CGFloat radius=(zone==100||zone==101)?72:30;
        if(hypot(p.x-c.x,p.y-c.y)<=radius) {
            if(zone==100||zone==101) {
                for(NSNumber *used in self.touches.objectEnumerator)if(used.integerValue==zone)return -1;
            }
            return zone;
        }
    }return -1;
}
- (NSDictionary *)state { return self.snapshot; }
- (void)update {
    double lx=0,ly=0,rx=0,ry=0,lt=0,rt=0;uint16_t buttons=0;
    for(UITouch *touch in self.touches.keyEnumerator) {
        NSInteger zone=[[self.touches objectForKey:touch] integerValue];
        if(zone==100||zone==101) {
            CGPoint p=[touch locationInView:self],c=[self centerForZone:zone];
            double x=(p.x-c.x)/62,y=(c.y-p.y)/62,length=hypot(x,y);
            if(length>1){x/=length;y/=length;}
            if(length<0.08){x=0;y=0;}
            if(zone==100){lx=x;ly=y;}else{rx=x;ry=y;}
        }else if(zone==200)lt=1;
        else if(zone==201)rt=1;
        else if(zone>=0)buttons|=(uint16_t)zone;
    }
    self.snapshot=@{@"lx":@(lx),@"ly":@(ly),@"rx":@(rx),@"ry":@(ry),@"lt":@(lt),@"rt":@(rt),@"buttons":@(buttons)};
    if(self.changed)self.changed(self.snapshot);[self setNeedsDisplay];
}
- (void)neutral { [self.touches removeAllObjects];[self update]; }
- (void)touchesBegan:(NSSet *)touches withEvent:(UIEvent *)event {
    (void)event;
    for(UITouch *touch in touches){NSInteger zone=[self zoneAt:[touch locationInView:self]];if(zone>=0)[self.touches setObject:@(zone) forKey:touch];}
    [self update];
}
- (void)touchesMoved:(NSSet *)touches withEvent:(UIEvent *)event { (void)touches;(void)event;[self update]; }
- (void)touchesEnded:(NSSet *)touches withEvent:(UIEvent *)event {
    (void)event;for(UITouch *touch in touches)[self.touches removeObjectForKey:touch];[self update];
}
- (void)touchesCancelled:(NSSet *)touches withEvent:(UIEvent *)event { [self touchesEnded:touches withEvent:event]; }
- (void)drawRect:(CGRect)rect {
    (void)rect;
    NSDictionary *names=@{@0x1000:@"A",@0x2000:@"B",@0x4000:@"X",@0x8000:@"Y",@1:@"↑",@2:@"↓",@4:@"←",@8:@"→",@0x100:@"LB",@0x200:@"RB",@200:@"LT",@201:@"RT",@0x20:@"BACK",@0x10:@"START",@0x40:@"L3",@0x80:@"R3"};
    for(NSNumber *number in [self zones]) {
        NSInteger zone=number.integerValue;CGPoint c=[self centerForZone:zone];CGFloat radius=(zone==100||zone==101)?72:28;
        BOOL pressed=NO;for(NSNumber *used in self.touches.objectEnumerator)if(used.integerValue==zone)pressed=YES;
        UIColor *tint=[UIColor colorWithRed:0.3 green:0.89 blue:0.74 alpha:pressed?0.55:0.18];
        [tint setFill];UIBezierPath *circle=[UIBezierPath bezierPathWithOvalInRect:CGRectMake(c.x-radius,c.y-radius,radius*2,radius*2)];[circle fill];
        [[UIColor colorWithWhite:1 alpha:0.45] setStroke];circle.lineWidth=1.5;[circle stroke];
        if(zone==100||zone==101) {
            double x=[self.snapshot[zone==100?@"lx":@"rx"] doubleValue],y=[self.snapshot[zone==100?@"ly":@"ry"] doubleValue];
            [[UIColor colorWithWhite:1 alpha:0.55] setFill];[[UIBezierPath bezierPathWithOvalInRect:CGRectMake(c.x+x*42-24,c.y-y*42-24,48,48)] fill];
        }else {
            NSString *name=names[number];NSDictionary *style=@{NSFontAttributeName:[UIFont boldSystemFontOfSize:name.length>3?10:17],NSForegroundColorAttributeName:[UIColor whiteColor]};
            CGSize size=[name sizeWithAttributes:style];[name drawAtPoint:CGPointMake(c.x-size.width/2,c.y-size.height/2) withAttributes:style];
        }
    }
}
@end
