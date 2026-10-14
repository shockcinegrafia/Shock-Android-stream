package com.shock.stream;

import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.graphics.*;
import android.hardware.display.DisplayManager;
import android.hardware.display.VirtualDisplay;
import android.media.Image;
import android.media.ImageReader;
import android.media.projection.MediaProjection;
import android.media.projection.MediaProjectionManager;
import android.os.*;
import android.util.DisplayMetrics;
import android.view.WindowManager;
import java.io.*;
import java.net.*;
import java.nio.ByteBuffer;
import java.util.concurrent.atomic.AtomicReference;

public class CaptureService extends Service {
 public static final String STATUS_ACTION="com.shock.stream.STATUS";
 private volatile boolean running=false;
 private volatile boolean capturing=false;
 private ServerSocket server;
 private Thread worker;
 private MediaProjection projection;
 private VirtualDisplay display;
 private ImageReader reader;
 private HandlerThread imageThread;
 private final AtomicReference<byte[]> latest=new AtomicReference<>();
 private final Object frameLock=new Object();
 private long lastFrame=0;

 private void status(String value){
  Intent i=new Intent(STATUS_ACTION);
  i.setPackage(getPackageName());i.putExtra("status",value);sendBroadcast(i);
 }
 @Override public void onCreate(){
  super.onCreate();
  NotificationManager nm=getSystemService(NotificationManager.class);
  nm.createNotificationChannel(new NotificationChannel("capture","Shock Stream",NotificationManager.IMPORTANCE_LOW));
  Notification note=new Notification.Builder(this,"capture")
   .setSmallIcon(android.R.drawable.ic_media_play).setContentTitle("Shock Android Stream")
   .setContentText("Servidor local na porta 8088").build();
  startForeground(1,note,ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
 }
 @Override public int onStartCommand(Intent intent,int flags,int startId){
  if(!running){
   running=true;
   worker=new Thread(()->serve(),"ShockHTTP");
   worker.start();
  }
  if(intent!=null && intent.hasExtra("data") && !capturing){
   Intent data;
   if(Build.VERSION.SDK_INT>=33)data=intent.getParcelableExtra("data",Intent.class);
   else data=(Intent)intent.getParcelableExtra("data");
   if(data!=null)startCapture(intent.getIntExtra("result",Activity.RESULT_CANCELED),data);
  }
  return START_NOT_STICKY;
 }
 private void startCapture(int result,Intent data){
  try{
   MediaProjectionManager mgr=(MediaProjectionManager)getSystemService(MEDIA_PROJECTION_SERVICE);
   projection=mgr.getMediaProjection(result,data);
   if(projection==null){status("Captura nao autorizada");return;}
   imageThread=new HandlerThread("ShockFrames");imageThread.start();
   Handler handler=new Handler(imageThread.getLooper());
   projection.registerCallback(new MediaProjection.Callback(){
    @Override public void onStop(){stopCapture();status("Captura encerrada pelo Android");}
   },handler);
   DisplayMetrics metrics=new DisplayMetrics();
   ((WindowManager)getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(metrics);
   int width=metrics.widthPixels,height=metrics.heightPixels;
   float scale=Math.min(1f,960f/Math.max(width,height));
   width=Math.max(2,((int)(width*scale))&~1);
   height=Math.max(2,((int)(height*scale))&~1);
   reader=ImageReader.newInstance(width,height,PixelFormat.RGBA_8888,2);
   reader.setOnImageAvailableListener(r->{
    Image image=null;
    try{
     image=r.acquireLatestImage();
     if(image==null)return;
     long now=android.os.SystemClock.elapsedRealtime();
     if(now-lastFrame<100)return;
     lastFrame=now;
     Image.Plane plane=image.getPlanes()[0];
     ByteBuffer buffer=plane.getBuffer();
     int pixelStride=plane.getPixelStride(),rowStride=plane.getRowStride();
     int w=image.getWidth(),h=image.getHeight();
     Bitmap padded=Bitmap.createBitmap(rowStride/pixelStride,h,Bitmap.Config.ARGB_8888);
     padded.copyPixelsFromBuffer(buffer);
     Bitmap cropped=Bitmap.createBitmap(padded,0,0,w,h);
     ByteArrayOutputStream out=new ByteArrayOutputStream();
     cropped.compress(Bitmap.CompressFormat.JPEG,65,out);
     cropped.recycle();padded.recycle();
     latest.set(out.toByteArray());
     synchronized(frameLock){frameLock.notifyAll();}
    }catch(Exception e){android.util.Log.e("ShockStream","Frame error",e);}
    finally{if(image!=null)image.close();}
   },handler);
   display=projection.createVirtualDisplay("ShockCapture",width,height,metrics.densityDpi,
    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,reader.getSurface(),null,handler);
   capturing=true;
   status("Captura ativa: "+width+"x"+height+" MJPEG");
  }catch(Exception e){status("Falha na captura: "+e.getMessage());android.util.Log.e("ShockStream","Capture error",e);stopCapture();}
 }
 private void serve(){
  try(ServerSocket s=new ServerSocket(8088)){
   server=s;status("Host ativo na porta 8088");
   while(running){Socket client=s.accept();Thread t=new Thread(()->reply(client),"ShockClient");t.start();}
  }catch(Exception e){if(running)status("Falha HTTP: "+e.getMessage());}
 }
 private void reply(Socket socket){
  try(Socket s=socket){
   s.setSoTimeout(10000);
   BufferedReader input=new BufferedReader(new InputStreamReader(s.getInputStream(),"UTF-8"));
   String request=input.readLine();if(request==null)return;
   String[] parts=request.split(" ");
   String path=parts.length>1?parts[1]:"/";
   String line;while((line=input.readLine())!=null&&!line.isEmpty()){}
   OutputStream out=s.getOutputStream();
   if(path.startsWith("/tap?")){
    boolean ok=false;
    try{
     String query=path.substring(path.indexOf('?')+1);
     float x=-1,y=-1,x2=-1,y2=-1; int duration=65;
     for(String pair:query.split("&")){
      String[] kv=pair.split("=",2);
      if(kv.length==2){if(kv[0].equals("x"))x=Float.parseFloat(kv[1]);if(kv[0].equals("y"))y=Float.parseFloat(kv[1]);if(kv[0].equals("x2"))x2=Float.parseFloat(kv[1]);if(kv[0].equals("y2"))y2=Float.parseFloat(kv[1]);if(kv[0].equals("ms"))duration=Integer.parseInt(kv[1]);}
     }
     if(x>=0&&x<=1&&y>=0&&y<=1){if(x2>=0&&x2<=1&&y2>=0&&y2<=1)ok=TouchAccessibilityService.gesture(x,y,x2,y2,duration);else ok=TouchAccessibilityService.tap(x,y);}
    }catch(Exception ignored){}
    byte[] body=(ok?"OK":"ACCESSIBILITY_DISABLED").getBytes("UTF-8");
    out.write(("HTTP/1.1 "+(ok?"200 OK":"503 Service Unavailable")+"\r\nContent-Type: text/plain\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));
    out.write(body);out.flush();
   }else if(path.startsWith("/stream")){
    out.write(("HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=shockframe\r\nCache-Control: no-cache, no-store\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));
    byte[] previous=null;
    while(running&&!s.isClosed()){
     byte[] frame=latest.get();
     if(frame==null||frame==previous){synchronized(frameLock){frameLock.wait(500);}continue;}
     previous=frame;
     out.write(("--shockframe\r\nContent-Type: image/jpeg\r\nContent-Length: "+frame.length+"\r\n\r\n").getBytes("UTF-8"));
     out.write(frame);out.write("\r\n".getBytes("UTF-8"));out.flush();
    }
   }else{
    String html="<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no'><meta name='apple-mobile-web-app-capable' content='yes'><title>Shock Stream</title><style>html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#000;font-family:Arial}#video{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:contain}#controls{position:absolute;z-index:5;top:8px;right:8px;background:rgba(0,0,0,.7);padding:5px;border-radius:5px}button{font-size:14px;color:#fff;background:#333;border:1px solid #888;border-radius:4px;padding:9px;margin:2px}#tip{position:absolute;bottom:5px;left:8px;color:#ddd;font-size:11px;pointer-events:none}</style></head><body><img id='video' src='/stream' alt='Aguardando transmissao'><div id='controls'><button id='fit'>Ajustar</button><button id='fill'>Preencher</button><button id='hide'>Ocultar</button><button id='touch'>Toque: OFF</button></div><div id='tip'>Shock Stream | deslize para arrastar</div><script>(function(){var v=document.getElementById('video'),c=document.getElementById('controls'),touch=false,start=null;document.getElementById('fit').onclick=function(){v.style.objectFit='contain'};document.getElementById('fill').onclick=function(){v.style.objectFit='cover'};document.getElementById('hide').onclick=function(){c.style.display='none';document.getElementById('tip').style.display='none'};document.getElementById('touch').onclick=function(){touch=!touch;this.innerHTML=touch?'Toque: ON':'Toque: OFF'};function coords(t){var r=v.getBoundingClientRect(),nw=v.naturalWidth||1,nh=v.naturalHeight||1,scale=v.style.objectFit==='cover'?Math.max(r.width/nw,r.height/nh):Math.min(r.width/nw,r.height/nh),w=nw*scale,h=nh*scale,x=(t.clientX-r.left-(r.width-w)/2)/w,y=(t.clientY-r.top-(r.height-h)/2)/h;return {x:Math.max(0,Math.min(1,x)),y:Math.max(0,Math.min(1,y))}}function send(p,q,ms){var url='/tap?x='+p.x.toFixed(5)+'&y='+p.y.toFixed(5);if(q)url+='&x2='+q.x.toFixed(5)+'&y2='+q.y.toFixed(5)+'&ms='+ms;var req=new XMLHttpRequest();req.open('GET',url,true);req.send(null)}document.body.addEventListener('touchstart',function(e){if(c.style.display==='none'&&e.touches.length===2){c.style.display='block';return}if(!touch||e.target!==v||e.touches.length!==1)return;e.preventDefault();start={p:coords(e.touches[0]),time:new Date().getTime()}},false);document.body.addEventListener('touchmove',function(e){if(start&&touch)e.preventDefault()},false);document.body.addEventListener('touchend',function(e){if(!start||!touch)return;e.preventDefault();var p=start.p,q=e.changedTouches.length?coords(e.changedTouches[0]):p,ms=new Date().getTime()-start.time;start=null;if(Math.abs(q.x-p.x)+Math.abs(q.y-p.y)<.012)send(p,null,65);else send(p,q,Math.max(90,Math.min(ms,1800)))},false);document.body.addEventListener('touchcancel',function(){start=null},false)})();</script></body></html>";
    byte[] body=html.getBytes("UTF-8");
    out.write(("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));
    out.write(body);out.flush();
   }
  }catch(Exception e){android.util.Log.d("ShockStream","Client disconnected: "+e.getMessage());}
 }
 private synchronized void stopCapture(){
  capturing=false;latest.set(null);
  if(display!=null){display.release();display=null;}
  if(reader!=null){reader.close();reader=null;}
  if(projection!=null){MediaProjection p=projection;projection=null;p.stop();}
  if(imageThread!=null){imageThread.quitSafely();imageThread=null;}
 }
 @Override public void onDestroy(){
  running=false;try{if(server!=null)server.close();}catch(Exception ignored){}
  synchronized(frameLock){frameLock.notifyAll();}
  stopCapture();status("Servidor parado");super.onDestroy();
 }
 @Override public IBinder onBind(Intent i){return null;}
}