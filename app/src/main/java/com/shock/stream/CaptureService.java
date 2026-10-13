package com.shock.stream;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.IBinder;
public class CaptureService extends Service {
 @Override public void onCreate() {
  super.onCreate();
  NotificationManager manager=getSystemService(NotificationManager.class);
  manager.createNotificationChannel(new NotificationChannel("capture","Screen capture",NotificationManager.IMPORTANCE_LOW));
  Notification note=new Notification.Builder(this,"capture").setSmallIcon(android.R.drawable.ic_media_play).setContentTitle("Shock Android Stream").setContentText("Streaming prototype").build();
  startForeground(1,note,ServiceInfo.FOREGROUND_SERVICE_TYPE_MEDIA_PROJECTION);
 }
 @Override public int onStartCommand(Intent intent,int flags,int startId) {return START_NOT_STICKY;}
 @Override public IBinder onBind(Intent intent) {return null;}
}