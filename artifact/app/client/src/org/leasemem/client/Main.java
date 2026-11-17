package org.leasemem.client;
import android.app.Activity;
import android.os.Bundle;
/** Launcher entry used by the driver to (re)start the process, as a user or agent relaunch would. */
public class Main extends Activity {
    @Override protected void onCreate(Bundle b) { super.onCreate(b); if (!getIntent().getBooleanExtra("stay", false)) finish(); }
}
