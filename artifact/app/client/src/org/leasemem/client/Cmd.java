package org.leasemem.client;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
/** Explicit-broadcast command channel from the host driver. Runs on the main thread. */
public class Cmd extends BroadcastReceiver {
    @Override public void onReceive(Context c, Intent it) { LmApp.I.handle(it); }
}
