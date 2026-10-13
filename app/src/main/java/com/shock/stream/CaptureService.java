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
   if(path.startsWith("/stream")){
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
    String html="<!doctype html><html><head><meta name='viewport' content='width=device-width,initial-scale=1,maximum-scale=1'><title>Shock Stream</title></head><body style='margin:0;background:#101116;color:#fff;font-family:Arial;text-align:center'><h3>Shock Android Stream</h3><p>Host online na porta 8088</p><img src='/stream' style='display:block;width:100%;height:auto' alt='Aguardando captura...'><p>Se a imagem nao aparecer, autorize a captura no Android.</p></body></html>";
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