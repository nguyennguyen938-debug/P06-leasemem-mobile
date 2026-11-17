package org.leasemem.trig;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.util.Log;
public class Cmd extends BroadcastReceiver {
    @Override public void onReceive(Context c, Intent it) {
        String cmd = it.getStringExtra("cmd");
        if ("RESET".equals(cmd)) TrigJob.append(c, "RESET " + System.currentTimeMillis());
        if (!TrigJob.pending(c)) { TrigJob.append(c, "ARM " + System.currentTimeMillis()); TrigJob.schedule(c); }
        Log.i("LMTRIG", "DONE " + cmd + " pending=" + TrigJob.pending(c));
    }
}
