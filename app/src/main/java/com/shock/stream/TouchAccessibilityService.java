package com.shock.stream;
import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.os.Build;
import android.view.WindowManager;
import android.view.Display;
import android.graphics.Point;
import android.view.accessibility.AccessibilityEvent;

public class TouchAccessibilityService extends AccessibilityService {
 private static volatile TouchAccessibilityService instance;
 public static boolean enabled(){return instance!=null;}
 private static float clamp(float n){return Math.max(0f,Math.min(1f,n));}
 public static boolean tap(float x,float y){return gesture(x,y,x,y,65);}
 public static boolean gesture(float x1,float y1,float x2,float y2,int duration){
  TouchAccessibilityService s=instance;
  if(s==null||Build.VERSION.SDK_INT<24)return false;
  WindowManager wm=(WindowManager)s.getSystemService(WINDOW_SERVICE);
  Point size=new Point();
  wm.getDefaultDisplay().getRealSize(size);
  float left=Math.max(1,Math.min(size.x-2,clamp(x1)*(size.x-1)));
  float top=Math.max(1,Math.min(size.y-2,clamp(y1)*(size.y-1)));
  float right=Math.max(1,Math.min(size.x-2,clamp(x2)*(size.x-1)));
  float bottom=Math.max(1,Math.min(size.y-2,clamp(y2)*(size.y-1)));
  Path path=new Path();path.moveTo(left,top);
  if(Math.abs(left-right)+Math.abs(top-bottom)>2)path.lineTo(right,bottom);
  GestureDescription.Builder builder=new GestureDescription.Builder();
  builder.addStroke(new GestureDescription.StrokeDescription(path,0,Math.max(50,Math.min(duration,2500))));
  return s.dispatchGesture(builder.build(),null,null);
 }
 @Override protected void onServiceConnected(){super.onServiceConnected();instance=this;}
 @Override public void onAccessibilityEvent(AccessibilityEvent event){}
 @Override public void onInterrupt(){}
 @Override public void onDestroy(){instance=null;super.onDestroy();}
}