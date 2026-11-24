package org.leasemem.mut;

import android.app.Service;
import android.content.Intent;
import android.os.IBinder;

/** F6 L1: SMS role requirement only; never responds to anything. */
public class RespondStub extends Service {
    @Override public IBinder onBind(Intent i) { return null; }
    @Override public int onStartCommand(Intent i, int flags, int id) { stopSelf(); return START_NOT_STICKY; }
}
