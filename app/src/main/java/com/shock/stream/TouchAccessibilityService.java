package com.shock.stream;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.graphics.Path;
import android.graphics.Point;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.ArrayList;

public class TouchAccessibilityService extends AccessibilityService {
 private static volatile TouchAccessibilityService instance;
 private final Handler main=new Handler(Looper.getMainLooper());
 private final LinkedHashMap<Integer,Finger> fingers=new LinkedHashMap<>();
 private boolean busy=false;
 private static final long STALE_MS=850;
 private static class Finger {
  float x,y,lastX,lastY;
  boolean down=true;
  boolean terminalSent=false;
  long updated=SystemClock.uptimeMillis();
  GestureDescription.StrokeDescription stroke;
  Finger(float x,float y){this.x=x;this.y=y;lastX=x;lastY=y;}
 }
 public static boolean enabled(){return instance!=null;}
 public static boolean event(int id,String action,float x,float y){
  TouchAccessibilityService s=instance;
  if(s==null||id<0||id>9||!Float.isFinite(x)||!Float.isFinite(y))return false;
  if(!action.equals("down")&&!action.equals("move")&&!action.equals("up")&&!action.equals("cancel"))return false;
  s.main.post(()->{
   Finger f=s.fingers.get(id);
   if(action.equals("down")){
    if(f==null)s.fingers.put(id,new Finger(clamp(x),clamp(y)));
   }else if(f!=null){
    f.x=clamp(x);f.y=clamp(y);f.updated=SystemClock.uptimeMillis();
    if(action.equals("up")||action.equals("cancel"))f.down=false;
   }
   s.pump();
  });
  return true;
 }
 private static float clamp(float v){return Math.max(0f,Math.min(1f,v));}
 private void pump(){
  if(busy||fingers.isEmpty())return;
  WindowManager wm=(WindowManager)getSystemService(WINDOW_SERVICE);
  Point size=new Point();wm.getDefaultDisplay().getRealSize(size);
  GestureDescription.Builder builder=new GestureDescription.Builder();
  long now=SystemClock.uptimeMillis();
  for(Map.Entry<Integer,Finger> entry:fingers.entrySet()){
   Finger f=entry.getValue();
   if(f.down&&now-f.updated>STALE_MS)f.down=false;
   float x1=Math.max(1,Math.min(size.x-2,f.lastX*(size.x-1)));
   float y1=Math.max(1,Math.min(size.y-2,f.lastY*(size.y-1)));
   float x2=Math.max(1,Math.min(size.x-2,f.x*(size.x-1)));
   float y2=Math.max(1,Math.min(size.y-2,f.y*(size.y-1)));
   Path p=new Path();p.moveTo(x1,y1);p.lineTo(x2,y2);
   boolean continuing=f.down;
   GestureDescription.StrokeDescription stroke;
   if(f.stroke==null)stroke=new GestureDescription.StrokeDescription(p,0,40,continuing);
   else stroke=f.stroke.continueStroke(p,0,40,continuing);
   builder.addStroke(stroke);
   f.stroke=stroke;f.lastX=f.x;f.lastY=f.y;
   if(!continuing)f.terminalSent=true;
  }
  busy=true;
  boolean accepted=dispatchGesture(builder.build(),new GestureResultCallback(){
   @Override public void onCompleted(GestureDescription g){finish(true);}
   @Override public void onCancelled(GestureDescription g){finish(false);}
  },main);
  if(!accepted)finish(false);
 }
 private void finish(boolean success){
  busy=false;
  if(!success){fingers.clear();return;}
  // Only remove a released finger AFTER its terminal stroke has been dispatched.
  fingers.entrySet().removeIf(e->e.getValue().terminalSent);
  if(!fingers.isEmpty())main.postDelayed(this::pump,1);
 }
 @Override protected void onServiceConnected(){super.onServiceConnected();instance=this;}
 @Override public void onAccessibilityEvent(AccessibilityEvent event){}
 @Override public void onInterrupt(){fingers.clear();}
 @Override public void onDestroy(){instance=null;fingers.clear();super.onDestroy();}
}