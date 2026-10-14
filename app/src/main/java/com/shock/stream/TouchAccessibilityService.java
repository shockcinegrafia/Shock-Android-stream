package com.shock.stream;
import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.os.Build;
import android.view.accessibility.AccessibilityEvent;
public class TouchAccessibilityService extends AccessibilityService {
 private static volatile TouchAccessibilityService instance;
 public static boolean enabled(){return instance!=null;}
 public static boolean tap(float x,float y){
  TouchAccessibilityService s=instance;
  if(s==null||Build.VERSION.SDK_INT<24)return false;
  android.util.DisplayMetrics dm=s.getResources().getDisplayMetrics();
  float px=Math.max(0,Math.min(dm.widthPixels-1,x*dm.widthPixels));
  float py=Math.max(0,Math.min(dm.heightPixels-1,y*dm.heightPixels));
  Path path=new Path();path.moveTo(px,py);
  GestureDescription.Builder builder=new GestureDescription.Builder();
  builder.addStroke(new GestureDescription.StrokeDescription(path,0,65));
  return s.dispatchGesture(builder.build(),null,null);
 }
 @Override protected void onServiceConnected(){super.onServiceConnected();instance=this;}
 @Override public void onAccessibilityEvent(AccessibilityEvent event){}
 @Override public void onInterrupt(){}
 @Override public void onDestroy(){instance=null;super.onDestroy();}
}