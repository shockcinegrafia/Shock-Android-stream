package com.shock.stream;
import android.content.Context;
import android.net.ConnectivityManager;
import android.net.LinkAddress;
import android.net.LinkProperties;
import android.net.Network;
import java.net.Inet4Address;
public final class NetworkInfoUtil {
 private NetworkInfoUtil(){}
 public static String ip(Context c) {
  ConnectivityManager cm=(ConnectivityManager)c.getSystemService(Context.CONNECTIVITY_SERVICE);
  if(cm==null)return "IP indisponivel";
  Network active=cm.getActiveNetwork();
  if(active!=null){String value=fromLink(cm.getLinkProperties(active));if(value!=null)return value;}
  for(Network n:cm.getAllNetworks()){String value=fromLink(cm.getLinkProperties(n));if(value!=null)return value;}
  return "IP indisponivel";
 }
 private static String fromLink(LinkProperties lp){
  if(lp==null)return null;
  for(LinkAddress addr:lp.getLinkAddresses()){
   if(addr.getAddress() instanceof Inet4Address && !addr.getAddress().isLoopbackAddress() && !addr.getAddress().isLinkLocalAddress())return addr.getAddress().getHostAddress();
  }
  return null;
 }
}