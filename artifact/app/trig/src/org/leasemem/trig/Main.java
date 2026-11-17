package org.leasemem.trig;
import android.app.Activity;
import android.os.Bundle;
public class Main extends Activity {
    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        if (!TrigJob.pending(this)) { TrigJob.append(this, "ARM " + System.currentTimeMillis()); TrigJob.schedule(this); }
        finish();
    }
}
