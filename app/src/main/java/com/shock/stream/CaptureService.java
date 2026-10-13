package com.shock.stream;
import android.app.*;
import android.content.*;
import android.content.pm.ServiceInfo;
import android.os.*;
import java.net.*;
import java.io.*;
public class CaptureService extends Service {
 public static final String STATUS_ACTION="com.shock.stream.STATUS";
 private volatile boolean running=false;
 private ServerSocket server;
 private Thread worker;
 private void status(String s){Intent i=new Intent(STATUS_ACTION);i.setPackage(getPackageName());i.putExtra("status",s);sendBroadcast(i);}
 @Override public void onCreate(){
  super.onCreate();
  NotificationManager nm=getSystemService(NotificationManager.class);
  nm.createNotificationChannel(new NotificationChannel("capture","Shock Stream",NotificationManager.IMPORTANCE_LOW));
  Notification n=new Notification.Builder(this,"capture").setSmallIcon(android.R.drawable.ic_media_play).setContentTitle("Shock Android Stream").setContentText("Servidor local").build();
  startForeground(1,n,ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
 }
 @Override public int onStartCommand(Intent intent,int flags,int id){
  if(running)return START_NOT_STICKY;
  running=true;status("Abrindo servidor HTTP...");
  worker=new Thread(()->{
   try(ServerSocket s=new ServerSocket(8088)){
    server=s;status("Servidor ativo na porta 8088 (captura pendente)");
    while(running){Socket client=s.accept();new Thread(()->reply(client)).start();}
   }catch(Exception e){status("Falha HTTP: "+e.getMessage());}
  },"ShockHTTP");
  worker.start();return START_NOT_STICKY;
 }
 private void reply(Socket socket){
  try(Socket s=socket){
   s.setSoTimeout(5000);
   BufferedReader in=new BufferedReader(new InputStreamReader(s.getInputStream()));
   String request=in.readLine();if(request==null)return;
   String line;while((line=in.readLine())!=null&&!line.isEmpty()){}
   String html="<html><head><meta name='viewport' content='width=device-width,initial-scale=1'></head><body style='background:#111;color:white;font-family:Arial'><h2>Shock Android Stream</h2><p>Host online na porta 8088.</p><p>Captura de video ainda nao ativada nesta compilacao.</p></body></html>";
   byte[] body=html.getBytes("UTF-8");
   OutputStream out=s.getOutputStream();
   out.write(("HTTP/1.1 200 OK\r\nContent-Type: text/html; charset=utf-8\r\nContent-Length: "+body.length+"\r\nConnection: close\r\n\r\n").getBytes("UTF-8"));
   out.write(body);out.flush();
  }catch(Exception ignored){}
 }
 @Override public void onDestroy(){running=false;try{if(server!=null)server.close();}catch(Exception ignored){}status("Servidor parado");super.onDestroy();}
 @Override public IBinder onBind(Intent intent){return null;}
}