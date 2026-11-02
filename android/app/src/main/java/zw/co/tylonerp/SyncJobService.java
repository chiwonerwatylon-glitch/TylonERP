package zw.co.tylonerp;

import android.app.job.JobInfo;
import android.app.job.JobParameters;
import android.app.job.JobScheduler;
import android.app.job.JobService;
import android.content.ComponentName;
import android.content.Context;

/**
 * Uploads waiting changes as soon as the phone has a connection, even if the app is closed, and refreshes the
 * phone's copy of the business every hour so offline selling starts from recent stock levels.
 */
public class SyncJobService extends JobService {
    private static final int JOB_UPLOAD = 4211;
    private static final int JOB_PERIODIC = 4212;

    /** Run once the phone is online. Called whenever a change is saved on the phone. */
    static void scheduleUpload(Context context) {
        JobScheduler js = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        JobInfo job = new JobInfo.Builder(JOB_UPLOAD, new ComponentName(context, SyncJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setBackoffCriteria(30_000, JobInfo.BACKOFF_POLICY_EXPONENTIAL)
                .setPersisted(true)
                .build();
        js.schedule(job);
    }

    /** Hourly refresh while the phone has a connection. */
    static void schedulePeriodic(Context context) {
        JobScheduler js = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js == null) return;
        for (JobInfo j : js.getAllPendingJobs()) {
            if (j.getId() == JOB_PERIODIC) return;  // already scheduled
        }
        JobInfo job = new JobInfo.Builder(JOB_PERIODIC, new ComponentName(context, SyncJobService.class))
                .setRequiredNetworkType(JobInfo.NETWORK_TYPE_ANY)
                .setPeriodic(60 * 60 * 1000L)
                .setPersisted(true)
                .build();
        js.schedule(job);
    }

    static void cancelAll(Context context) {
        JobScheduler js = (JobScheduler) context.getSystemService(Context.JOB_SCHEDULER_SERVICE);
        if (js != null) js.cancelAll();
    }

    @Override
    public boolean onStartJob(final JobParameters params) {
        Thread t = new Thread(() -> {
            SyncManager sm = SyncManager.get(getApplicationContext());
            sm.runSync();
            boolean again = sm.lastFailedForNetwork() && Store.get(getApplicationContext()).count("pending") > 0;
            jobFinished(params, again && params.getJobId() == JOB_UPLOAD);
        }, "tylonerp-sync-job");
        t.start();
        return true;  // work continues on the thread above
    }

    @Override
    public boolean onStopJob(JobParameters params) {
        return true;  // the system stopped us (connection lost): try again later
    }
}
