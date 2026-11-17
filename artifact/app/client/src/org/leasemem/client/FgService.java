package org.leasemem.client;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.Service;
import android.content.Intent;
import android.os.IBinder;

/** Foreground-service mode: keeps the memory process in the foreground-service state (no ContentService background
 *  deferral, not cached, not frozen), as an always-on assistant memory would run. Started by the driver with
 *  `am start-foreground-service`; restarted by the driver after any process-ending gap. */
public class FgService extends Service {
    static volatile boolean running = false;
    @Override public int onStartCommand(Intent i, int flags, int id) {
        NotificationManager nm = getSystemService(NotificationManager.class);
        nm.createNotificationChannel(new NotificationChannel("lm", "LeaseMem", NotificationManager.IMPORTANCE_LOW));
        Notification n = new Notification.Builder(this, "lm").setContentTitle("LeaseMem memory").setSmallIcon(android.R.drawable.ic_menu_info_details).build();
        startForeground(1, n);
        running = true;
        return START_NOT_STICKY;
    }
    @Override public void onDestroy() { running = false; super.onDestroy(); }
    @Override public IBinder onBind(Intent i) { return null; }
}
