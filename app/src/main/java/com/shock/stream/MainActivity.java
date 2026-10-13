package com.shock.stream;
import android.app.Activity;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.media.projection.MediaProjectionManager;
import android.os.Bundle;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.content.ClipData;
import android.content.ClipboardManager;
public class MainActivity extends Activity {
 private static final int REQUEST=41;
 private TextView status;
 private final BroadcastReceiver updates=new BroadcastReceiver(){
  @Override public void onReceive(Context c,Intent i){showStatus(i.getStringExtra("status"));}
 };
 @Override public void onCreate(Bundle b){
  super.onCreate(b);
  LinearLayout layout=new LinearLayout(this);
  layout.setOrientation(LinearLayout.VERTICAL);
  layout.setPadding(28,48,28,20);
  status=new TextView(this);
  Button start=new Button(this);start.setText("Autorizar captura e iniciar");
  start.setOnClickListener(v->{
   MediaProjectionManager m=(MediaProjectionManager)getSystemService(MEDIA_PROJECTION_SERVICE);
   startActivityForResult(m.createScreenCaptureIntent(),REQUEST);
  });
  Button copy=new Button(this);copy.setText("Copiar IP local");
  copy.setOnClickListener(v->{
   String ip=NetworkInfoUtil.ip(this);
   ((ClipboardManager)getSystemService(CLIPBOARD_SERVICE)).setPrimaryClip(ClipData.newPlainText("Shock Stream","http://"+ip+":8088"));
  });
  Button stop=new Button(this);stop.setText("Parar transmissao");
  stop.setOnClickListener(v->stopService(new Intent(this,CaptureService.class)));
  layout.addView(status);layout.addView(start);layout.addView(copy);layout.addView(stop);
  setContentView(layout);showStatus("Aguardando autorizacao");
 }
 private void showStatus(String state){
  String ip=NetworkInfoUtil.ip(this);
  status.setText("Shock Android Stream v0.2\nEstado: "+state+"\n\nPrincipal (se mDNS resolver):\nhttp://share.local:8088\n\nAlternativo:\nhttp://"+ip+":8088\n\nAndroid e iPad devem estar na mesma rede Wi-Fi.");
 }
 @Override protected void onResume(){super.onResume();registerReceiver(updates,new IntentFilter(CaptureService.STATUS_ACTION),Context.RECEIVER_NOT_EXPORTED);}
 @Override protected void onPause(){unregisterReceiver(updates);super.onPause();}
 @Override protected void onActivityResult(int request,int result,Intent data){
  super.onActivityResult(request,result,data);
  if(request==REQUEST && result==RESULT_OK && data!=null){
   Intent service=new Intent(this,CaptureService.class);
   service.putExtra("result",result);service.putExtra("data",data);
   startForegroundService(service);showStatus("Iniciando servidor...");
  }else if(request==REQUEST)showStatus("Captura nao autorizada");
 }
}