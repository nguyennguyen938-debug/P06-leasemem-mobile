package org.leasemem.mut;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** F6 L1: SMS role requirement only; ignores every delivered SMS. */
public class SmsStub extends BroadcastReceiver {
    @Override public void onReceive(Context c, Intent i) { }
}
