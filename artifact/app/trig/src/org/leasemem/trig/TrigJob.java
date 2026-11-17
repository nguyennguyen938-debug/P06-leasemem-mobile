package org.leasemem.trig;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;
import android.net.Uri;
import android.util.Log;
import java.io.File;
import java.io.FileOutputStream;

/**
 * OS-held change trigger baseline: a JobScheduler job with content-URI triggers. The trigger is held by
 * system_server, so it survives death of this app's process; each firing appends a durable record.
 * Content-trigger jobs cannot be persisted across reboot (JobInfo forbids setPersisted with triggers).
 */
public class TrigJob extends JobService {
    static final int JOB_ID = 6;
    static final String[][] URIS = {
        {"contacts", "content://com.android.contacts"}, {"sms", "content://sms"}, {"calllog", "content://call_log"},
        {"media", "content://media"}, {"calendar", "content://com.android.calendar"},
        {"settings", "content://settings/global/lm_mode"}, {"settings", "content://settings/global/lm_target"}};

    static void schedule(Context c) {
        JobScheduler js = c.getSystemService(JobScheduler.class);
        JobInfo.Builder b = new JobInfo.Builder(JOB_ID, new ComponentName(c, TrigJob.class));
        for (String[] u : URIS) b.addTriggerContentUri(new JobInfo.TriggerContentUri(Uri.parse(u[1]), JobInfo.TriggerContentUri.FLAG_NOTIFY_FOR_DESCENDANTS));
        b.setTriggerContentUpdateDelay(50); b.setTriggerContentMaxDelay(500);
        int r = js.schedule(b.build());
        Log.i("LMTRIG", "schedule=" + r);
    }

    static boolean pending(Context c) { return c.getSystemService(JobScheduler.class).getPendingJob(JOB_ID) != null; }

    static synchronized void append(Context c, String line) {
        try (FileOutputStream f = new FileOutputStream(new File(c.getFilesDir(), "trig.log"), true)) { f.write((line + "\n").getBytes()); f.getFD().sync(); }
        catch (Exception e) { Log.e("LMTRIG", "append", e); }
    }

    @Override public boolean onStartJob(JobParameters p) {
        StringBuilder sb = new StringBuilder();
        String[] auth = p.getTriggeredContentAuthorities();
        Uri[] uris = p.getTriggeredContentUris();
        if (auth != null) for (String a : auth) sb.append(a).append(' ');
        sb.append("| ");
        if (uris != null) for (Uri u : uris) sb.append(u).append(' '); else sb.append("<null-uris>");
        append(this, "FIRE " + System.currentTimeMillis() + " " + sb);
        schedule(this);   // re-arm (content-trigger jobs are one-shot)
        return false;
    }

    @Override public boolean onStopJob(JobParameters p) { return false; }
}
