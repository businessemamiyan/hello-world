package ir.mehrdad.app;

import android.app.Notification;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.service.notification.NotificationListenerService;
import android.service.notification.StatusBarNotification;

/** اعلان‌های گوشی: فقط آن‌هایی که مالی‌اند و رمز یک‌بارمصرف نیستند به صف می‌روند؛ باقی هیچ‌وقت از گوشی خارج نمی‌شود. */
public class NotifListener extends NotificationListenerService {
    @Override
    public void onNotificationPosted(StatusBarNotification sbn) {
        try {
            if (!Prefs.isPaired(this) || sbn == null) return;
            if (getPackageName().equals(sbn.getPackageName())) return;      // اعلان‌های خود مهرداد
            Notification n = sbn.getNotification();
            if (n == null || sbn.isOngoing()) return;
            if ((n.flags & Notification.FLAG_GROUP_SUMMARY) != 0) return;

            Bundle e = n.extras;
            if (e == null) return;
            CharSequence title = e.getCharSequence(Notification.EXTRA_TITLE);
            CharSequence big = e.getCharSequence(Notification.EXTRA_BIG_TEXT);
            CharSequence text = big != null ? big : e.getCharSequence(Notification.EXTRA_TEXT);
            String body = ((title == null ? "" : title + "\n") + (text == null ? "" : text)).trim();
            if (!Filters.shouldForward(body)) return;

            Outbox.add(this, "notification", appLabel(sbn.getPackageName()), body);
        } catch (Exception ignored) { }
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
