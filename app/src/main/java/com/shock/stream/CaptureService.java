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
 private Bitmap frameBitmap;
 private Bitmap croppedBitmap;
 private ByteArrayOutputStream jpegBuffer;

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
   float scale=Math.min(1f,800f/Math.max(width,height));
   width=Math.max(2,((int)(width*scale))&~1);
   height=Math.max(2,((int)(height*scale))&~1);
   reader=ImageReader.newInstance(width,height,PixelFormat.RGBA_8888,2);
   reader.setOnImageAvailableListener(r->{
    Image image=null;
    try{
     image=r.acquireLatestImage();
     if(image==null)return;
     long now=android.os.SystemClock.elapsedRealtime();
     if(now-lastFrame<66)return;
     lastFrame=now;
     Image.Plane plane=image.getPlanes()[0];
     ByteBuffer buffer=plane.getBuffer();
     int pixelStride=plane.getPixelStride(),rowStride=plane.getRowStride();
     int w=image.getWidth(),h=image.getHeight();
     int paddedWidth=rowStride/pixelStride;
     if(frameBitmap==null||frameBitmap.getWidth()!=paddedWidth||frameBitmap.getHeight()!=h){
      if(frameBitmap!=null)frameBitmap.recycle();
      if(croppedBitmap!=null)croppedBitmap.recycle();
      frameBitmap=Bitmap.createBitmap(paddedWidth,h,Bitmap.Config.ARGB_8888);
      croppedBitmap=Bitmap.createBitmap(w,h,Bitmap.Config.ARGB_8888);
      jpegBuffer=new ByteArrayOutputStream(160000);
     }
     buffer.rewind();
     frameBitmap.copyPixelsFromBuffer(buffer);
     Canvas canvas=new Canvas(croppedBitmap);
     canvas.drawBitmap(frameBitmap,0,0,null);
     jpegBuffer.reset();
     croppedBitmap.compress(Bitmap.CompressFormat.JPEG,60,jpegBuffer);
     latest.set(jpegBuffer.toByteArray());
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
   if(path.startsWith("/input?")){
    boolean ok=false;
    try{
     String action="",query=path.substring(path.indexOf('?')+1);
     int id=-1;float x=-1,y=-1;
     for(String pair:query.split("&")){
      String[] kv=pair.split("=",2);
      if(kv.length!=2)continue;
      if(kv[0].equals("a"))action=kv[1];
      if(kv[0].equals("id"))id=Integer.parseInt(kv[1]);
      if(kv[0].equals("x"))x=Float.parseFloat(kv[1]);
      if(kv[0].equals("y"))y=Float.parseFloat(kv[1]);
     }
     if(x>=0&&x<=1&&y>=0&&y<=1)ok=TouchAccessibilityService.event(id,action,x,y);
    }catch(Exception e){android.util.Log.w("ShockStream","Bad input",e);}
    byte[] body=(ok?"OK":"INPUT_UNAVAILABLE").getBytes("UTF-8");
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
    String html="<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no'><meta name='apple-mobile-web-app-capable' content='yes'><title>Shock Stream</title><style>html,body{margin:0;padding:0;width:100%;height:100%;overflow:hidden;background:#000;font-family:Arial}#video{position:absolute;left:0;top:0;width:100%;height:100%;object-fit:contain}#controls{position:absolute;z-index:5;top:8px;right:8px;background:rgba(0,0,0,.7);padding:5px;border-radius:5px}button{font-size:14px;color:#fff;background:#333;border:1px solid #888;border-radius:4px;padding:9px;margin:2px}</style></head><body><img id='video' src='/stream' alt='Aguardando transmissao'><div id='controls'><button id='fit'>Ajustar</button><button id='fill'>Preencher</button><button id='hide'>Ocultar</button><button id='touch'>Toque: OFF</button></div><script>(function(){var v=document.getElementById('video'),c=document.getElementById('controls'),enabled=false,active={},last={};document.getElementById('fit').onclick=function(){v.style.objectFit='contain'};document.getElementById('fill').onclick=function(){v.style.objectFit='cover'};document.getElementById('hide').onclick=function(){c.style.display='none'};document.getElementById('touch').onclick=function(){enabled=!enabled;this.innerHTML=enabled?'Toque: ON':'Toque: OFF'};function point(t){var r=v.getBoundingClientRect(),nw=v.naturalWidth||1,nh=v.naturalHeight||1,scale=v.style.objectFit==='cover'?Math.max(r.width/nw,r.height/nh):Math.min(r.width/nw,r.height/nh),w=nw*scale,h=nh*scale;return {x:Math.max(0,Math.min(1,(t.clientX-r.left-(r.width-w)/2)/w)),y:Math.max(0,Math.min(1,(t.clientY-r.top-(r.height-h)/2)/h))}}function send(a,id,p){var req=new XMLHttpRequest();req.open('GET','/input?a='+a+'&id='+id+'&x='+p.x.toFixed(5)+'&y='+p.y.toFixed(5),true);req.send(null)}function handle(e,a){if(!enabled)return;if(e.target!==v&&a==='down')return;e.preventDefault();for(var i=0;i<e.changedTouches.length;i++){var t=e.changedTouches[i],id=t.identifier;if(a==='down'){if(active[id]!==undefined)continue;var slot=-1;for(var n=0;n<5;n++){var used=false;for(var key in active)if(active[key]===n)used=true;if(!used){slot=n;break}}if(slot<0)continue;active[id]=slot}else if(active[id]===undefined)continue;var p=point(t),now=new Date().getTime();if(a!=='move'||!last[id]||now-last[id]>25){send(a,active[id],p);last[id]=now}if(a==='up'||a==='cancel'){delete active[id];delete last[id]}}}document.body.addEventListener('touchstart',function(e){if(c.style.display==='none'&&e.touches.length===2){c.style.display='block';return}handle(e,'down')},false);document.body.addEventListener('touchmove',function(e){handle(e,'move')},false);document.body.addEventListener('touchend',function(e){handle(e,'up')},false);document.body.addEventListener('touchcancel',function(e){handle(e,'cancel')},false)})();</script></body></html>";
    byte[] body=html.getBytes("UTF-8");
    out.write(("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));
    out.write(body);out.flush();
   }
  }catch(Exception e){android.util.Log.d("ShockStream","Client disconnected: "+e.getMessage());}
 }
 private synchronized void stopCapture(){
  capturing=false;latest.set(null);
  if(frameBitmap!=null){frameBitmap.recycle();frameBitmap=null;}
  if(croppedBitmap!=null){croppedBitmap.recycle();croppedBitmap=null;}
  jpegBuffer=null;
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