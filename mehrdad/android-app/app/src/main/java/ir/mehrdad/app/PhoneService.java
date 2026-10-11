package ir.mehrdad.app;

import android.Manifest;
import android.app.Activity;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.app.Service;
import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.content.IntentFilter;
import android.content.pm.PackageManager;
import android.content.pm.ServiceInfo;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.IBinder;
import android.os.Looper;
import android.telecom.TelecomManager;
import android.telephony.SmsManager;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import org.json.JSONObject;

import java.util.ArrayList;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * سرویس پیش‌زمینهٔ «کنترل گوشی»: به سرور شخصی مهرداد long-poll می‌کند و فقط اقدام‌هایی را اجرا می‌کند که
 * خودِ صاحب در اپ/تلگرام تأیید کرده است (پیامک، تماس، باز کردن صفحهٔ ارسال اینستاگرام).
 * هیچ اقدامی از طرف محتوای پیامک/اعلان یا هر منبع دیگری اجرا نمی‌شود؛ سرور فقط اقدام تأییدشده را می‌دهد.
 */
public class PhoneService extends Service {
    private static final String CH_SERVICE = "mehrdad_phone";
    private static final String CH_ACTION = "mehrdad_phone_actions";
    private static final String ACTION_SMS_SENT = "ir.mehrdad.app.SMS_SENT";
    private static final int NOTIF_ID = 4001;
    private static final long CONTACTS_EVERY_MS = 12L * 3600 * 1000;

    private volatile boolean running;
    private Thread worker;
    private final Map<Long, int[]> smsPending = new ConcurrentHashMap<>();   // شناسهٔ اقدام → {تکه‌های باقی‌مانده، تکه‌های ناموفق}
    private final Handler main = new Handler(Looper.getMainLooper());

    private final BroadcastReceiver smsSent = new BroadcastReceiver() {
        @Override
        public void onReceive(Context c, Intent i) {
            long id = i.getLongExtra("aid", -1);
            int[] st = smsPending.get(id);
            if (st == null) return;
            int code = getResultCode();
            if (code != Activity.RESULT_OK) st[1]++;
            if (--st[0] <= 0) {
                smsPending.remove(id);
                ackAsync(id, st[1] == 0 ? "sent" : "failed", st[1] == 0 ? "به پیامک‌ساز گوشی تحویل شد" : "خطا در ارسال پیامک (کد " + code + ")");
            }
        }
    };

    public static void start(Context ctx) {
        ContextCompat.startForegroundService(ctx, new Intent(ctx, PhoneService.class));
    }

    public static void stop(Context ctx) {
        ctx.stopService(new Intent(ctx, PhoneService.class));
    }

    @Override
    public void onCreate() {
        super.onCreate();
        NotificationManager nm = (NotificationManager) getSystemService(NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(CH_SERVICE, "مهرداد در پس‌زمینه", NotificationManager.IMPORTANCE_LOW));
            nm.createNotificationChannel(new NotificationChannel(CH_ACTION, "اقدام‌های گوشی (یک لمس)", NotificationManager.IMPORTANCE_HIGH));
        }
        ContextCompat.registerReceiver(this, smsSent, new IntentFilter(ACTION_SMS_SENT), ContextCompat.RECEIVER_NOT_EXPORTED);
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
        if (worker == null || !worker.isAlive()) {
            worker = new Thread(this::loop, "mehrdad-phone");
            worker.start();
        }
        return START_STICKY;
    }

    @Override
    public void onDestroy() {
        running = false;
        if (worker != null) worker.interrupt();
        try { unregisterReceiver(smsSent); } catch (Exception ignored) { }
        super.onDestroy();
    }

    @Override
    public IBinder onBind(Intent intent) { return null; }

    // ------------------------------------------------------------------ حلقهٔ اصلی
    private void loop() {
        int backoff = 2;
        while (running) {
            try {
                if (!Prefs.isPaired(this) || !Prefs.phoneService(this)) { Thread.sleep(8000); continue; }
                maybeSyncContacts();
                Api.Result r = Api.call(this, "GET", "/api/phone/next?wait=20", null, 40000);
                if (r.code == 200) {
                    backoff = 2;
                    handle(r.json());
                } else if (r.code == 204) {
                    backoff = 2;
                } else if (r.code == 401) {
                    Prefs.setPhoneService(this, false);
                    notifyInfo(4002, "اتصال گوشی قطع شد", "این دستگاه در تلگرام قطع شده؛ دوباره جفتش کن.");
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

    // ------------------------------------------------------------------ اجرای اقدام
    private void handle(JSONObject a) {
        long id = a.optLong("id", -1);
        String kind = a.optString("kind");
        String number = a.optString("to_number", "");
        String name = a.optString("to_name", "");
        String text = a.optString("text", "");
        if (id < 0) return;
        try {
            if ("sms".equals(kind)) sendSms(id, number, text);
            else if ("call".equals(kind)) placeCall(id, number, name);
            else if ("instagram".equals(kind)) openInstagram(id, name, text);
            else if ("reply".equals(kind)) {
                String err = NotifListener.sendReply(this, number, text);           // number = کلید گفتگو (بسته|نام)
                ackAsync(id, err == null ? "sent" : "failed", err == null ? "از دکمهٔ پاسخ اعلان فرستاده شد" : err);
            }
            else ackAsync(id, "failed", "نوع اقدام ناشناخته");
        } catch (Exception e) {
            ackAsync(id, "failed", e.getClass().getSimpleName());
        }
    }

    private boolean has(String perm) {
        return ContextCompat.checkSelfPermission(this, perm) == PackageManager.PERMISSION_GRANTED;
    }

    private void sendSms(long id, String number, String text) {
        if (!has(Manifest.permission.SEND_SMS)) { ackAsync(id, "failed", "مجوز ارسال پیامک داده نشده"); return; }
        if (number.isEmpty() || text.isEmpty()) { ackAsync(id, "failed", "شماره یا متن خالی بود"); return; }
        SmsManager sm = Build.VERSION.SDK_INT >= 31 ? getSystemService(SmsManager.class) : SmsManager.getDefault();
        ArrayList<String> parts = sm.divideMessage(text);
        ArrayList<PendingIntent> sentIntents = new ArrayList<>();
        for (int i = 0; i < parts.size(); i++) {
            Intent si = new Intent(ACTION_SMS_SENT).setPackage(getPackageName()).putExtra("aid", id);
            sentIntents.add(PendingIntent.getBroadcast(this, (int) (id * 20 + i), si, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        }
        smsPending.put(id, new int[]{parts.size(), 0});
        main.postDelayed(() -> { if (smsPending.remove(id) != null) ackAsync(id, "failed", "پاسخی از سیستم پیامک نیامد"); }, 60000);
        sm.sendMultipartTextMessage(number, null, parts, sentIntents, null);
    }

    private void placeCall(long id, String number, String name) {
        if (number.isEmpty()) { ackAsync(id, "failed", "شماره خالی بود"); return; }
        Intent dial = new Intent(Intent.ACTION_CALL, Uri.fromParts("tel", number, null)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        // یک اعلان «بزن تا زنگ بخورد» همیشه می‌گذاریم: اگر اندروید شروع تماس از پس‌زمینه را نداد، یک لمس کافی است
        PendingIntent pi = PendingIntent.getActivity(this, (int) id, dial, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        postTap((int) (5000 + id), "تماس با " + (name.isEmpty() ? number : name), "اگر خودش زنگ نخورد این را بزن", pi);
        if (!has(Manifest.permission.CALL_PHONE)) { ackAsync(id, "needs_tap", "مجوز تماس نیست؛ اعلان را بزن"); return; }
        try {
            TelecomManager tm = (TelecomManager) getSystemService(TELECOM_SERVICE);
            tm.placeCall(Uri.fromParts("tel", number, null), new Bundle());
            ackAsync(id, "sent", "در حال شماره‌گیری");
        } catch (SecurityException | NullPointerException e) {
            ackAsync(id, "needs_tap", "اندروید شماره‌گیری از پس‌زمینه را نداد");
        }
    }

    private void openInstagram(long id, String name, String text) {
        Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
                .setPackage("com.instagram.android").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pi = PendingIntent.getActivity(this, (int) id, send, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        postTap((int) (5000 + id), "پیام اینستاگرام برای " + name, "بزن، گیرنده را انتخاب کن و ارسال را بزن", pi);
        ackAsync(id, "needs_tap", "اینستاگرام خودکار نیست؛ اعلان را بزن");
    }

    // ------------------------------------------------------------------ اعلان‌ها و گزارش به سرور
    private void postTap(int nid, String title, String text, PendingIntent pi) {
        try {
            Notification n = new NotificationCompat.Builder(this, CH_ACTION)
                    .setSmallIcon(android.R.drawable.sym_action_call).setContentTitle(title).setContentText(text)
                    .setContentIntent(pi).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH)
                    .setTimeoutAfter(10 * 60 * 1000L).build();
            NotificationManagerCompat.from(this).notify(nid, n);
        } catch (SecurityException ignored) { }
    }

    private void notifyInfo(int nid, String title, String text) {
        try {
            Notification n = new NotificationCompat.Builder(this, CH_ACTION).setSmallIcon(android.R.drawable.stat_notify_error)
                    .setContentTitle(title).setContentText(text).setAutoCancel(true).build();
            NotificationManagerCompat.from(this).notify(nid, n);
        } catch (SecurityException ignored) { }
    }

    private void ackAsync(long id, String status, String detail) {
        final Context ctx = getApplicationContext();
        new Thread(() -> {
            try {
                Api.call(ctx, "POST", "/api/phone/actions/" + id + "/ack", new JSONObject().put("status", status).put("detail", detail), 15000);
            } catch (Exception ignored) { }
        }).start();
    }
}
