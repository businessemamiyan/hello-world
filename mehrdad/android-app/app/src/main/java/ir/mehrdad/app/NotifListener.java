package ir.mehrdad.app;

import android.app.Notification;
import android.app.PendingIntent;
import android.app.RemoteInput;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Build;
import android.os.Bundle;
import android.os.Parcelable;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;

/**
 * اعلان‌های گوشی:
 *  - همیشه: فقط اعلان‌های مالی (و بدون رمز یک‌بارمصرف) به صف می‌روند؛ باقی هیچ‌وقت از گوشی خارج نمی‌شود.
 *  - اگر کاربر در تنظیمات «پیام‌های پیام‌رسان‌ها» را روشن کرده باشد: اعلان تلگرام/واتس‌اپ/اینستاگرام/بله هم (فرستنده + متن) برای مهرداد ثبت می‌شود،
 *    و دکمهٔ «پاسخ» اعلان نگه داشته می‌شود تا مهرداد با تأیید خودِ کاربر بتواند جواب بدهد (RemoteInput، بدون هیچ API غیررسمی).
 */
public class NotifListener extends NotificationListenerService {
    static final Map<String, String> MESSENGERS = new HashMap<>();
    static {
        MESSENGERS.put("org.telegram.messenger", "تلگرام");
        MESSENGERS.put("org.telegram.messenger.web", "تلگرام");
        MESSENGERS.put("org.thunderdog.challegram", "تلگرام");
        MESSENGERS.put("com.whatsapp", "واتس‌اپ");
        MESSENGERS.put("com.whatsapp.w4b", "واتس‌اپ");
        MESSENGERS.put("com.instagram.android", "اینستاگرام");
        MESSENGERS.put("ir.nasim", "بله");
    }

    private static final long REPLY_TTL_MS = 3L * 3600 * 1000;

    static class Reply {
        final PendingIntent pi;
        final RemoteInput ri;
        final long ts;
        Reply(PendingIntent pi, RemoteInput ri) { this.pi = pi; this.ri = ri; this.ts = System.currentTimeMillis(); }
    }

    /** کلید گفتگو (بسته|نام) → آخرین دکمهٔ پاسخ آن اعلان. */
    static final Map<String, Reply> REPLIES = new ConcurrentHashMap<>();

    @Override
    public void onListenerConnected() {
        super.onListenerConnected();
        PhoneService.ensure(this);                 // سیستم دوباره به شنونده وصل شده؛ اگر سرویس کنترل گوشی مرده بود بالایش بیاور
    }

    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            if (!Prefs.isPaired(this) || sbn == null) return;
            if (!PhoneService.isAlive()) PhoneService.ensure(this);
            if (getPackageName().equals(sbn.getPackageName())) return;      // اعلان‌های خود مهرداد
            Notification n = sbn.getNotification();
            if (n == null || sbn.isOngoing()) return;
            if ((n.flags & Notification.FLAG_GROUP_SUMMARY) != 0) return;

            Bundle e = n.extras;
            if (e == null) return;
            String label = MESSENGERS.get(sbn.getPackageName());
            if (label != null && Prefs.msgrCapture(this)) {
                handleMessenger(sbn, n, e, label);
                return;
            }
            CharSequence title = e.getCharSequence(Notification.EXTRA_TITLE);
            CharSequence big = e.getCharSequence(Notification.EXTRA_BIG_TEXT);
            CharSequence text = big != null ? big : e.getCharSequence(Notification.EXTRA_TEXT);
            String body = ((title == null ? "" : title + "\n") + (text == null ? "" : text)).trim();
            if (!Filters.shouldForward(body)) return;

            Outbox.add(this, "notification", appLabel(sbn.getPackageName()), body);
        } catch (Exception ignored) { }
    }

    private void handleMessenger(StatusBarNotification sbn, Notification n, Bundle e, String label) {
        if (Notification.CATEGORY_CALL.equals(n.category)) return;
        CharSequence title = e.getCharSequence(Notification.EXTRA_TITLE);
        CharSequence convTitle = Build.VERSION.SDK_INT >= 28 ? e.getCharSequence(Notification.EXTRA_CONVERSATION_TITLE) : null;
        String text = null, sender = null;
        Parcelable[] msgs = e.getParcelableArray(Notification.EXTRA_MESSAGES);
        if (msgs != null && msgs.length > 0 && msgs[msgs.length - 1] instanceof Bundle) {       // MessagingStyle: آخرین پیام + فرستنده‌اش
            Bundle last = (Bundle) msgs[msgs.length - 1];
            CharSequence t = last.getCharSequence("text");
            CharSequence s = last.getCharSequence("sender");
            if (t != null) text = t.toString();
            if (s != null) sender = s.toString();
        }
        if (text == null) {
            CharSequence big = e.getCharSequence(Notification.EXTRA_BIG_TEXT);
            CharSequence t = big != null ? big : e.getCharSequence(Notification.EXTRA_TEXT);
            if (t != null) text = t.toString();
        }
        if (text == null || text.trim().length() < 1) return;
        String name = (convTitle != null ? convTitle : (title == null ? "" : title)).toString().trim();
        if (name.isEmpty()) return;
        String body = (convTitle != null && sender != null && !sender.isEmpty() ? sender + ": " : "") + text.trim();
        if (body.length() > 1500) body = body.substring(0, 1500);
        if (Filters.isSensitive(body)) return;

        String key = sbn.getPackageName() + "|" + (name.length() > 80 ? name.substring(0, 80) : name);
        cacheReply(key, n);
        Prefs.markNotif(this);
        Outbox.add(this, "notification", label, body, label, key, name);
    }

    /** دکمهٔ «پاسخ» (اکشن دارای RemoteInput) این اعلان را برای جواب‌دادن بعدی نگه می‌داریم. */
    private void cacheReply(String key, Notification n) {
        if (n.actions == null) return;
        Reply found = null;
        for (Notification.Action a : n.actions) {
            RemoteInput[] ris = a.getRemoteInputs();
            if (ris == null || ris.length == 0 || a.actionIntent == null) continue;
            boolean semantic = Build.VERSION.SDK_INT >= 28 && a.getSemanticAction() == Notification.Action.SEMANTIC_ACTION_REPLY;
            if (found == null || semantic) found = new Reply(a.actionIntent, ris[0]);
            if (semantic) break;
        }
        if (found != null) {
            REPLIES.put(key, found);
            long now = System.currentTimeMillis();
            for (Map.Entry<String, Reply> en : REPLIES.entrySet()) if (now - en.getValue().ts > REPLY_TTL_MS) REPLIES.remove(en.getKey());
        }
    }

    /** جواب‌دادن از طریق همان دکمهٔ «پاسخ» اعلان. null = انجام شد، وگرنه علت خطا. */
    public static String sendReply(Context ctx, String key, String text) {
        Reply r = REPLIES.get(key);
        if (r == null || System.currentTimeMillis() - r.ts > REPLY_TTL_MS) return "اعلان اون گفتگو دیگه روی گوشی نیست؛ باید پیام تازه‌ای بیاد";
        try {
            Intent fill = new Intent();
            Bundle b = new Bundle();
            b.putCharSequence(r.ri.getResultKey(), text);
            RemoteInput.addResultsToIntent(new RemoteInput[]{r.ri}, fill, b);
            r.pi.send(ctx, 0, fill);
            return null;
        } catch (PendingIntent.CanceledException ex) {
            REPLIES.remove(key);
            return "اعلان بسته شده بود؛ باید پیام تازه‌ای بیاد";
        } catch (Exception ex) {
            return ex.getClass().getSimpleName();
        }
    }

    private String appLabel(String pkg) {
        try {
            PackageManager pm = getPackageManager();
            ApplicationInfo ai = pm.getApplicationInfo(pkg, 0);
            return String.valueOf(pm.getApplicationLabel(ai));
        } catch (Exception e) {
            return pkg;
        }
    }
}
