package ir.mehrdad.app;

import android.Manifest;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
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
 * اجرای اقدام‌هایی که صاحب تأیید کرده (پیامک، تماس، اینستاگرام، پاسخ به پیام‌رسان).
 * هم سرویس پیش‌زمینه (PhoneService) و هم کارگر پس‌زمینه (PhoneWorker، وقتی سیستم سرویس را کشته) از همین‌جا استفاده می‌کنند.
 * هیچ اقدامی از طرف محتوای پیامک/اعلان اجرا نمی‌شود؛ سرور فقط اقدام تأییدشده را می‌دهد.
 */
public final class PhoneActions {
    static final String CH_ACTION = "mehrdad_phone_actions";
    static final String ACTION_SMS_SENT = "ir.mehrdad.app.SMS_SENT";

    private static final Map<Long, int[]> SMS_PENDING = new ConcurrentHashMap<>();   // شناسهٔ اقدام → {تکه‌های باقی‌مانده، تکه‌های ناموفق}
    private static final Handler MAIN = new Handler(Looper.getMainLooper());

    private PhoneActions() { }

    static void ensureChannels(Context ctx) {
        NotificationManager nm = (NotificationManager) ctx.getSystemService(Context.NOTIFICATION_SERVICE);
        if (Build.VERSION.SDK_INT >= 26 && nm != null) {
            nm.createNotificationChannel(new NotificationChannel(CH_ACTION, "اقدام‌های گوشی (یک لمس)", NotificationManager.IMPORTANCE_HIGH));
        }
    }

    /** یک اقدام تأییدشده را اجرا می‌کند و نتیجه را به سرور خبر می‌دهد. */
    static void handle(Context ctx, JSONObject a) {
        ctx = ctx.getApplicationContext();
        ensureChannels(ctx);
        long id = a.optLong("id", -1);
        String kind = a.optString("kind");
        String number = a.optString("to_number", "");
        String name = a.optString("to_name", "");
        String text = a.optString("text", "");
        if (id < 0) return;
        try {
            if ("sms".equals(kind)) sendSms(ctx, id, number, text);
            else if ("call".equals(kind)) placeCall(ctx, id, number, name);
            else if ("instagram".equals(kind)) openInstagram(ctx, id, name, text);
            else if ("reply".equals(kind)) {
                String err = NotifListener.sendReply(ctx, number, text);           // number = کلید گفتگو (بسته|نام)
                ackAsync(ctx, id, err == null ? "sent" : "failed", err == null ? "از دکمهٔ پاسخ اعلان فرستاده شد" : err);
            }
            else ackAsync(ctx, id, "failed", "نوع اقدام ناشناخته");
        } catch (Exception e) {
            ackAsync(ctx, id, "failed", e.getClass().getSimpleName());
        }
    }

    private static boolean has(Context ctx, String perm) {
        return ContextCompat.checkSelfPermission(ctx, perm) == PackageManager.PERMISSION_GRANTED;
    }

    private static void sendSms(Context ctx, long id, String number, String text) {
        if (!has(ctx, Manifest.permission.SEND_SMS)) { ackAsync(ctx, id, "failed", "مجوز ارسال پیامک داده نشده"); return; }
        if (number.isEmpty() || text.isEmpty()) { ackAsync(ctx, id, "failed", "شماره یا متن خالی بود"); return; }
        SmsManager sm = Build.VERSION.SDK_INT >= 31 ? ctx.getSystemService(SmsManager.class) : SmsManager.getDefault();
        ArrayList<String> parts = sm.divideMessage(text);
        ArrayList<PendingIntent> sentIntents = new ArrayList<>();
        for (int i = 0; i < parts.size(); i++) {
            Intent si = new Intent(ACTION_SMS_SENT).setClass(ctx, SmsSentReceiver.class).putExtra("aid", id).putExtra("parts", parts.size());
            sentIntents.add(PendingIntent.getBroadcast(ctx, (int) (id * 20 + i), si, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        }
        SMS_PENDING.put(id, new int[]{parts.size(), 0});
        final Context app = ctx;
        MAIN.postDelayed(() -> { if (SMS_PENDING.remove(id) != null) ackAsync(app, id, "failed", "پاسخی از سیستم پیامک نیامد"); }, 60000);
        sm.sendMultipartTextMessage(number, null, parts, sentIntents, null);
    }

    /** از SmsSentReceiver: نتیجهٔ هر تکهٔ پیامک. حتی اگر پروسه بین ارسال و نتیجه مرده باشد، بر پایهٔ همین یک تکه تصمیم می‌گیرد. */
    static void onSmsSent(Context ctx, long id, int parts, int resultCode) {
        ctx = ctx.getApplicationContext();
        int[] st = SMS_PENDING.get(id);
        if (st == null) {                                                           // وضعیت از دست رفته (پروسه دوباره ساخته شده)
            ackAsync(ctx, id, resultCode == android.app.Activity.RESULT_OK ? "sent" : "failed",
                    resultCode == android.app.Activity.RESULT_OK ? "به پیامک‌ساز گوشی تحویل شد" : "خطا در ارسال پیامک (کد " + resultCode + ")");
            return;
        }
        if (resultCode != android.app.Activity.RESULT_OK) st[1]++;
        if (--st[0] <= 0) {
            SMS_PENDING.remove(id);
            ackAsync(ctx, id, st[1] == 0 ? "sent" : "failed", st[1] == 0 ? "به پیامک‌ساز گوشی تحویل شد" : "خطا در ارسال پیامک (کد " + resultCode + ")");
        }
    }

    private static void placeCall(Context ctx, long id, String number, String name) {
        if (number.isEmpty()) { ackAsync(ctx, id, "failed", "شماره خالی بود"); return; }
        Intent dial = new Intent(Intent.ACTION_CALL, Uri.fromParts("tel", number, null)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        // یک اعلان «بزن تا زنگ بخورد» همیشه می‌گذاریم: اگر اندروید شروع تماس از پس‌زمینه را نداد، یک لمس کافی است
        PendingIntent pi = PendingIntent.getActivity(ctx, (int) id, dial, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        postTap(ctx, (int) (5000 + id), "تماس با " + (name.isEmpty() ? number : name), "اگر خودش زنگ نخورد این را بزن", pi);
        if (!has(ctx, Manifest.permission.CALL_PHONE)) { ackAsync(ctx, id, "needs_tap", "مجوز تماس نیست؛ اعلان را بزن"); return; }
        try {
            TelecomManager tm = (TelecomManager) ctx.getSystemService(Context.TELECOM_SERVICE);
            tm.placeCall(Uri.fromParts("tel", number, null), new Bundle());
            ackAsync(ctx, id, "sent", "در حال شماره‌گیری");
        } catch (SecurityException | NullPointerException e) {
            ackAsync(ctx, id, "needs_tap", "اندروید شماره‌گیری از پس‌زمینه را نداد");
        }
    }

    private static void openInstagram(Context ctx, long id, String name, String text) {
        Intent send = new Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text)
                .setPackage("com.instagram.android").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        PendingIntent pi = PendingIntent.getActivity(ctx, (int) id, send, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT);
        postTap(ctx, (int) (5000 + id), "پیام اینستاگرام برای " + name, "بزن، گیرنده را انتخاب کن و ارسال را بزن", pi);
        ackAsync(ctx, id, "needs_tap", "اینستاگرام خودکار نیست؛ اعلان را بزن");
    }

    static void postTap(Context ctx, int nid, String title, String text, PendingIntent pi) {
        try {
            Notification n = new NotificationCompat.Builder(ctx, CH_ACTION)
                    .setSmallIcon(android.R.drawable.sym_action_call).setContentTitle(title).setContentText(text)
                    .setContentIntent(pi).setAutoCancel(true).setPriority(NotificationCompat.PRIORITY_HIGH)
                    .setTimeoutAfter(10 * 60 * 1000L).build();
            NotificationManagerCompat.from(ctx).notify(nid, n);
        } catch (SecurityException ignored) { }
    }

    static void notifyInfo(Context ctx, int nid, String title, String text) {
        try {
            ensureChannels(ctx);
            Notification n = new NotificationCompat.Builder(ctx, CH_ACTION).setSmallIcon(android.R.drawable.stat_notify_error)
                    .setContentTitle(title).setContentText(text).setAutoCancel(true).build();
            NotificationManagerCompat.from(ctx).notify(nid, n);
        } catch (SecurityException ignored) { }
    }

    static void ackAsync(Context ctx, long id, String status, String detail) {
        final Context app = ctx.getApplicationContext();
        new Thread(() -> {
            try {
                Api.call(app, "POST", "/api/phone/actions/" + id + "/ack", new JSONObject().put("status", status).put("detail", detail), 15000);
            } catch (Exception ignored) { }
        }).start();
    }
}
