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
 private final java.util.ArrayDeque<org.json.JSONObject> pendingEvents=new java.util.ArrayDeque<>();
 private static final long STALE_MS=2000;
 private final Runnable pendingPump=this::pump;
 private static class Finger {
  float x,y,lastX,lastY;
  boolean down=true;
  boolean terminalSent=false;
  long updated=SystemClock.uptimeMillis();
  long started=updated;
  GestureDescription.StrokeDescription stroke;
  Finger(float x,float y){this.x=x;this.y=y;lastX=x;lastY=y;}
 }
 public static boolean enabled(){return instance!=null;}
 public static boolean event(int id,String action,float x,float y){
  return batch("[{\"id\":"+id+",\"a\":\""+action+"\",\"x\":"+x+",\"y\":"+y+"}]");
 }
 public static boolean batch(String json){
  TouchAccessibilityService s=instance;if(s==null)return false;
  final ArrayList<org.json.JSONObject> events=new ArrayList<>();
  try{
   org.json.JSONArray list=new org.json.JSONArray(json);
   if(list.length()>100)return false;
   for(int i=0;i<list.length();i++){
    org.json.JSONObject e=list.getJSONObject(i);int id=e.getInt("id");
    String a=e.getString("a");double x=e.getDouble("x"),y=e.getDouble("y");
    if(id<0||id>9||!Double.isFinite(x)||!Double.isFinite(y)||x<0||x>1||y<0||y>1)return false;
    if(!a.equals("down")&&!a.equals("move")&&!a.equals("up")&&!a.equals("cancel")&&!a.equals("hold"))return false;
    events.add(e);
   }
  }catch(Exception e){return false;}
  s.main.post(()->{
   if(s.pendingEvents.size()+events.size()>200){s.pendingEvents.clear();for(Finger f:s.fingers.values())f.down=false;}else{s.pendingEvents.addAll(events);s.drainEvents();}
   // Allow a short tap's up to arrive before starting a continuing stroke.
   s.main.postDelayed(s.pendingPump,24);
  });return true;
 }
 private void drainEvents(){
  while(!pendingEvents.isEmpty()){
   org.json.JSONObject e=pendingEvents.peek();int id=e.optInt("id");
   String a=e.optString("a");Finger f=fingers.get(id);
   if(a.equals("down")&&f!=null)break; // Finish the previous up before reusing an id.
   pendingEvents.remove();float x=(float)e.optDouble("x"),y=(float)e.optDouble("y");
   if(a.equals("down"))fingers.put(id,new Finger(x,y));
   else if(f!=null&&!f.terminalSent){
    f.x=x;f.y=y;f.updated=SystemClock.uptimeMillis();
    if(a.equals("up")||a.equals("cancel"))f.down=false;
   }
  }
 }
 public static void cancelAll(){
  TouchAccessibilityService s=instance;if(s==null)return;
  s.main.post(()->{s.pendingEvents.clear();for(Finger f:s.fingers.values())f.down=false;s.pump();});
 }
 private static float clamp(float v){return Math.max(0f,Math.min(1f,v));}
 private void pump(){
  if(busy||fingers.isEmpty())return;
  WindowManager wm=(WindowManager)getSystemService(WINDOW_SERVICE);
  Point size=new Point();wm.getDefaultDisplay().getRealSize(size);
  GestureDescription.Builder builder=new GestureDescription.Builder();
  long now=SystemClock.uptimeMillis();
  final LinkedHashMap<Integer,Finger> submitted=new LinkedHashMap<>(fingers);
  for(Map.Entry<Integer,Finger> entry:fingers.entrySet()){
   Finger f=entry.getValue();
   if(f.down&&now-f.updated>STALE_MS)f.down=false;
   float x1=f.stroke==null?Math.max(1,Math.min(size.x-2,f.lastX*(size.x-1))):f.lastX;
   float y1=f.stroke==null?Math.max(1,Math.min(size.y-2,f.lastY*(size.y-1))):f.lastY;
   float x2=Math.max(1,Math.min(size.x-2,f.x*(size.x-1)));
   float y2=Math.max(1,Math.min(size.y-2,f.y*(size.y-1)));
   Path p=new Path();p.moveTo(x1,y1);p.lineTo(x2,y2);
   boolean continuing=f.down;
   GestureDescription.StrokeDescription stroke;
   if(f.stroke==null)stroke=new GestureDescription.StrokeDescription(p,0,continuing?16:Math.max(1,Math.min(80,now-f.started)),continuing);
   else stroke=f.stroke.continueStroke(p,0,16,continuing);
   builder.addStroke(stroke);
   f.stroke=stroke;f.lastX=x2;f.lastY=y2;
   if(!continuing)f.terminalSent=true;
  }
  busy=true;
  boolean accepted=dispatchGesture(builder.build(),new GestureResultCallback(){
   @Override public void onCompleted(GestureDescription g){finish(true,submitted);}
   @Override public void onCancelled(GestureDescription g){finish(false,submitted);}
  },main);
  if(!accepted)finish(false,submitted);
 }
 private void finish(boolean success,Map<Integer,Finger> submitted){
  busy=false;
  if(!success){fingers.clear();pendingEvents.clear();return;}
  // Only remove a released finger AFTER its terminal stroke has been dispatched.
  for(Map.Entry<Integer,Finger> e:submitted.entrySet())
   if(e.getValue().terminalSent&&fingers.get(e.getKey())==e.getValue())fingers.remove(e.getKey());
  drainEvents();
  if(!fingers.isEmpty())main.postDelayed(pendingPump,1);
 }
 @Override protected void onServiceConnected(){super.onServiceConnected();instance=this;}
 @Override public void onAccessibilityEvent(AccessibilityEvent event){}
 @Override public void onInterrupt(){cancelAll();}
 @Override public void onDestroy(){instance=null;fingers.clear();super.onDestroy();}
}