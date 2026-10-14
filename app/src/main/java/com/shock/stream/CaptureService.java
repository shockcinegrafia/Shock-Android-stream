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
 private volatile long demandUntil=0;
 private Handler captureHandler;
 private int captureWidth,captureHeight,density;
 private DisplayManager displayManager;
 private DisplayManager.DisplayListener rotationListener;
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
   Handler handler=new Handler(imageThread.getLooper());captureHandler=handler;
   final MediaProjection session=projection;
   projection.registerCallback(new MediaProjection.Callback(){
    @Override public void onStop(){if(projection!=session)return;stopCapture();status("Captura encerrada pelo Android");}
    @Override public void onCapturedContentResize(int w,int h){resizeCapture(w,h);}
   },handler);
   DisplayMetrics metrics=new DisplayMetrics();
   ((WindowManager)getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(metrics);
   density=metrics.densityDpi;
   int[] dimensions=scaledSize(metrics.widthPixels,metrics.heightPixels);
   int width=dimensions[0],height=dimensions[1];
   captureWidth=width;captureHeight=height;
   reader=ImageReader.newInstance(width,height,PixelFormat.RGBA_8888,2);
   attachReader(reader);
   display=projection.createVirtualDisplay("ShockCapture",width,height,metrics.densityDpi,
    DisplayManager.VIRTUAL_DISPLAY_FLAG_AUTO_MIRROR,reader.getSurface(),null,handler);
   capturing=true;
   displayManager=(DisplayManager)getSystemService(DISPLAY_SERVICE);
   rotationListener=new DisplayManager.DisplayListener(){
    public void onDisplayAdded(int id){}
    public void onDisplayRemoved(int id){}
    public void onDisplayChanged(int id){
     if(id==android.view.Display.DEFAULT_DISPLAY && Build.VERSION.SDK_INT<34){
      DisplayMetrics m=new DisplayMetrics();
      ((WindowManager)getSystemService(WINDOW_SERVICE)).getDefaultDisplay().getRealMetrics(m);
      resizeCapture(m.widthPixels,m.heightPixels);
     }
    }
   };
   displayManager.registerDisplayListener(rotationListener,handler);
   status("Captura ativa: "+width+"x"+height+" MJPEG");
  }catch(Exception e){status("Falha na captura: "+e.getMessage());android.util.Log.e("ShockStream","Capture error",e);stopCapture();}
 }
 private static int[] scaledSize(int w,int h){
  float scale=Math.min(1f,Math.min(1024f/Math.max(w,h),768f/Math.min(w,h)));
  return new int[]{Math.max(2,((int)(w*scale))&~1),Math.max(2,((int)(h*scale))&~1)};
 }
 private void attachReader(ImageReader target){
   target.setOnImageAvailableListener(r->{
    Image image=null;
    try{
     image=r.acquireLatestImage();
     if(r!=reader)return;
     if(image==null)return;
     long now=android.os.SystemClock.elapsedRealtime();
     if(now-lastFrame<33||now>demandUntil)return;
     lastFrame=now;
     Image.Plane plane=image.getPlanes()[0];
     ByteBuffer buffer=plane.getBuffer();
     int pixelStride=plane.getPixelStride(),rowStride=plane.getRowStride();
     int w=image.getWidth(),h=image.getHeight();
     int paddedWidth=rowStride/pixelStride;
     if(frameBitmap==null||frameBitmap.getWidth()!=paddedWidth||frameBitmap.getHeight()!=h||croppedBitmap.getWidth()!=w){
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
   },captureHandler);
 }
 // Called on the capture handler: one projection consent, one VirtualDisplay.
 private void resizeCapture(int w,int h){
  if(!capturing||display==null||w<=0||h<=0)return;
  int[] size=scaledSize(w,h);
  if(size[0]==captureWidth&&size[1]==captureHeight)return;
  try{
   ImageReader replacement=ImageReader.newInstance(size[0],size[1],PixelFormat.RGBA_8888,2);
   ImageReader old=reader;
   display.setSurface(null);
   display.resize(size[0],size[1],density);
   reader=replacement;attachReader(reader);display.setSurface(reader.getSurface());
   captureWidth=size[0];captureHeight=size[1];latest.set(null);lastFrame=0;
   if(old!=null){old.setOnImageAvailableListener(null,null);old.close();}
   status("Captura ativa: "+captureWidth+"x"+captureHeight+" MJPEG");
  }catch(Exception e){status("Falha ao redimensionar: "+e.getMessage());stopCapture();}
 }
 private void serve(){
  try(ServerSocket s=new ServerSocket(8088)){
   server=s;status("Host ativo na porta 8088");
   while(running){Socket client=s.accept();Thread t=new Thread(()->reply(client),"ShockClient");t.start();}
  }catch(Exception e){if(running)status("Falha HTTP: "+e.getMessage());}
 }
 private void reply(Socket socket){
  try(Socket s=socket){
   s.setSoTimeout(10000);s.setTcpNoDelay(true);s.setSendBufferSize(32768);
   BufferedReader input=new BufferedReader(new InputStreamReader(s.getInputStream(),"UTF-8"));
   String request=input.readLine();if(request==null)return;
   String[] parts=request.split(" ");
   String path=parts.length>1?parts[1]:"/";
   int length=0;String line;
   while((line=input.readLine())!=null&&!line.isEmpty()){
    if(line.toLowerCase(java.util.Locale.ROOT).startsWith("content-length:"))length=Integer.parseInt(line.substring(15).trim());
   }
   if(length<0||length>16384)return;
   OutputStream out=s.getOutputStream();
   if(path.equals("/events")&&request.startsWith("POST ")){
    char[] body=new char[length];int read=0;
    while(read<length){int n=input.read(body,read,length-read);if(n<0)return;read+=n;}
    boolean ok=TouchAccessibilityService.batch(new String(body));
    out.write(("HTTP/1.1 "+(ok?"200 OK":"503 Service Unavailable")+"\r\nContent-Length: 0\r\nCache-Control: no-store\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));out.flush();
   }else if(path.startsWith("/input?")){
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
   }else if(path.startsWith("/frame")){
    demandUntil=SystemClock.elapsedRealtime()+1500;
    byte[] before=latest.get(),frame=null;
    long until=SystemClock.elapsedRealtime()+1000;
    synchronized(frameLock){
     while(running && (frame=latest.get())==before && SystemClock.elapsedRealtime()<until)frameLock.wait(50);
    }
    if(frame==null){out.write("HTTP/1.1 503 Service Unavailable\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".getBytes("UTF-8"));}
    else{
     out.write(("HTTP/1.1 200 OK\r\nContent-Type: image/jpeg\r\nCache-Control: no-store\r\nContent-Length: "+frame.length+"\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));out.write(frame);
    }out.flush();
   }else if(path.startsWith("/stream")){
    demandUntil=SystemClock.elapsedRealtime()+1500;
    out.write(("HTTP/1.1 200 OK\r\nContent-Type: multipart/x-mixed-replace; boundary=shockframe\r\nCache-Control: no-cache, no-store\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));
    byte[] previous=null;
    while(running&&!s.isClosed()){
     demandUntil=SystemClock.elapsedRealtime()+1500;
     byte[] frame=latest.get();
     if(frame==null||frame==previous){synchronized(frameLock){frameLock.wait(500);}continue;}
     previous=frame;
     out.write(("--shockframe\r\nContent-Type: image/jpeg\r\nContent-Length: "+frame.length+"\r\n\r\n").getBytes("UTF-8"));
     out.write(frame);out.write("\r\n".getBytes("UTF-8"));out.flush();
    }
   }else{
    ByteArrayOutputStream page=new ByteArrayOutputStream();
    try(InputStream asset=getAssets().open("index.html")){byte[] chunk=new byte[4096];int n;while((n=asset.read(chunk))!=-1)page.write(chunk,0,n);}
    String html=page.toString("UTF-8");
    byte[] body=html.getBytes("UTF-8");
    out.write(("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));
    out.write(body);out.flush();
   }
  }catch(Exception e){android.util.Log.d("ShockStream","Client disconnected: "+e.getMessage());}
 }
 private void stopCapture(){
  Handler h=captureHandler;
  if(h!=null&&Looper.myLooper()!=h.getLooper()){h.post(this::stopCapture);return;}
  captureHandler=null;
  capturing=false;latest.set(null);
  TouchAccessibilityService.cancelAll();
  if(displayManager!=null&&rotationListener!=null){displayManager.unregisterDisplayListener(rotationListener);rotationListener=null;}
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