package ir.mehrdad.app;

import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ServiceInfo;
import android.os.Build;
import android.os.IBinder;

import androidx.core.app.NotificationCompat;
import androidx.core.content.ContextCompat;

import org.json.JSONObject;

/**
 * سرویس پیش‌زمینهٔ «کنترل گوشی»: به سرور شخصی مهرداد long-poll می‌کند و فقط اقدام‌هایی را اجرا می‌کند که
 * خودِ صاحب در اپ/تلگرام تأیید کرده است (پیامک، تماس، باز کردن صفحهٔ ارسال اینستاگرام، پاسخ به پیام‌رسان).
 * اگر سیستم (مثلاً MIUI) سرویس را بکشد، PhoneWorker هر ~۱۵ دقیقه دوباره بالایش می‌آورد و اقدام‌های منتظر را برمی‌دارد.
 */
public class PhoneService extends Service {
    private static final String CH_SERVICE = "mehrdad_phone";
    private static final int NOTIF_ID = 4001;
    private static final long CONTACTS_EVERY_MS = 12L * 3600 * 1000;
    private static final long ALIVE_WINDOW_MS = 75_000;       // هر دور حلقه ≤ ~۴۵ ثانیه است

    private static volatile long lastLoopMs;                  // آخرین باری که حلقه زنده بود (فقط داخل همین پروسه معتبر است)
    private volatile boolean running;
    private Thread worker;

    public static void start(Context ctx) {
        ContextCompat.startForegroundService(ctx, new Intent(ctx, PhoneService.class));
    }

    /** تلاش بی‌صدا برای بالا آوردن سرویس (از پس‌زمینه ممکن است سیستم اجازه ندهد؛ در این صورت کارگر خودش جواب می‌دهد). */
    public static boolean ensure(Context ctx) {
        try {
            if (!Prefs.isPaired(ctx) || !Prefs.phoneService(ctx)) return false;
            if (isAlive()) return true;
            start(ctx);
            return true;
        } catch (Exception e) {
            return false;
        }
    }

    public static boolean isAlive() { return System.currentTimeMillis() - lastLoopMs < ALIVE_WINDOW_MS; }

    public static void stop(Context ctx) {
        ctx.stopService(new Intent(ctx, PhoneService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(CH_SERVICE, "مهرداد در پس‌زمینه", NotificationManager.IMPORTANCE_LOW));
        }
        PhoneActions.ensureChannels(this);
    }

    @Override
    public int onStartCommand(Intent intent, int flags, int startId) {
        PendingIntent talk = PendingIntent.getActivity(this, 1, new Intent(this, MainActivity.class).putExtra("voice", true)
                .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_SINGLE_TOP), PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        Notification n = new NotificationCompat.Builder(this, CH_SERVICE)
                .setSmallIcon(android.R.drawable.stat_sys_data_bluetooth)
                .setContentTitle("مهرداد آمادهٔ دستورهای توست")
                .setContentText("بزن و بگو؛ پیامک و تماسی که تأیید کنی از همین گوشی انجام می‌شود")
                .setContentIntent(talk)
                .addAction(android.R.drawable.ic_btn_speak_now, "🎤 بگو به مهرداد", talk)
                .setOngoing(true).setPriority(NotificationCompat.PRIORITY_LOW).build();
        if (Build.VERSION.SDK_INT >= 34) startForeground(NOTIF_ID, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE);
        else startForeground(NOTIF_ID, n);
        running = true;
        lastLoopMs = System.currentTimeMillis();
        if (worker == null || !worker.isAlive()) {
            worker = new Thread(this::loop, "mehrdad-phone");
            worker.start();
        }
        return START_STICKY;
    }

    /** کاربر اپ را از «برنامه‌های اخیر» کشید: سرویس باید بماند؛ اگر سیستم کشتش، کارگر دوباره بالایش می‌آورد. */
    @Override
    public void onTaskRemoved(Intent rootIntent) {
        super.onTaskRemoved(rootIntent);
        PhoneWorker.runSoon(this);
    }

    @Override
    public void onDestroy() {
        running = false;
        lastLoopMs = 0;
        if (worker != null) worker.interrupt();
        if (Prefs.isPaired(this) && Prefs.phoneService(this)) PhoneWorker.runSoon(this);     // خودمان نخواستیم بسته شویم
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    // ------------------------------------------------------------------ حلقهٔ اصلی
    private void loop() {
        int backoff = 2;
        while (running) {
            try {
                lastLoopMs = System.currentTimeMillis();
                if (!Prefs.isPaired(this) || !Prefs.phoneService(this)) { Thread.sleep(8000); continue; }
                maybeSyncContacts();
                Api.Result r = Api.call(this, "GET", "/api/phone/next?wait=20", null, 40000);
                lastLoopMs = System.currentTimeMillis();
                if (r.code == 200) {
                    backoff = 2;
                    PhoneActions.handle(this, r.json());
                } else if (r.code == 204) {
                    backoff = 2;
                } else if (r.code == 401) {
                    Prefs.setPhoneService(this, false);
                    PhoneActions.notifyInfo(this, 4002, "اتصال گوشی قطع شد", "این دستگاه در تلگرام قطع شده؛ دوباره جفتش کن.");
                    stopSelf();
                    return;
                } else {
                    Thread.sleep(backoff * 1000L);
                    backoff = Math.min(backoff * 2, 60);
                }
            } catch (InterruptedException e) {
                return;
            } catch (Exception e) {
                try { Thread.sleep(5000); } catch (InterruptedException ie) { return; }
            }
        }
    }

    private void maybeSyncContacts() {
        long now = System.currentTimeMillis();
        if (ContactsSync.hasPermission(this) && now - Prefs.lastContactsSync(this) >= CONTACTS_EVERY_MS) ContactsSync.run(this);
        if (CallLogSync.hasPermission(this) && now - Prefs.lastCallsSync(this) >= 6L * 3600 * 1000) CallLogSync.run(this, 2);
        if (CalendarSync.hasPermission(this) && now - Prefs.lastCalendarSync(this) >= 6L * 3600 * 1000) CalendarSync.run(this);
    }
}
