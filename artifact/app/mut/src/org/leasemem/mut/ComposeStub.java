package org.leasemem.mut;

import android.app.Activity;
import android.os.Bundle;

/** F6 L1: SMS role requirement only; closes at once, nothing is composed or sent. */
public class ComposeStub extends Activity {
    @Override protected void onCreate(Bundle b) { super.onCreate(b); finish(); }
}
