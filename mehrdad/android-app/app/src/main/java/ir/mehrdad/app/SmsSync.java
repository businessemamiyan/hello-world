package ir.mehrdad.app;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.provider.Telephony;

import androidx.core.content.ContextCompat;

import org.json.JSONArray;
import org.json.JSONObject;

/** پیامک‌های دریافتی و ارسالی چند روز اخیر را به صندوق مهرداد می‌فرستد تا بتواند دربارهٔ‌شان جواب بدهد. رمز یک‌بارمصرف هرگز نمی‌رود. */
public class SmsSync {
    public static boolean hasPermission(Context ctx) {
        return ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_SMS) == PackageManager.PERMISSION_GRANTED;
    }

    /** → تعداد پیامک‌های جدیدی که سرور ذخیره کرد، یا -1 اگر مجوز/جفت‌سازی/اتصال نبود. */
    public static int run(Context ctx, int days) {
        if (!hasPermission(ctx) || !Prefs.isPaired(ctx)) return -1;
        long since = System.currentTimeMillis() - Math.max(1, Math.min(days, 365)) * 86400000L;
        String[] proj = {Telephony.Sms._ID, Telephony.Sms.ADDRESS, Telephony.Sms.BODY, Telephony.Sms.DATE, Telephony.Sms.TYPE};
        int stored = 0;
        JSONArray batch = new JSONArray();
        try (Cursor c = ctx.getContentResolver().query(Uri.parse("content://sms"), proj, Telephony.Sms.DATE + ">=?",
                new String[]{String.valueOf(since)}, Telephony.Sms.DATE + " DESC")) {
            if (c == null) return -1;
            int n = 0;
            while (c.moveToNext() && n < 3000) {
                int type = c.getInt(4);
                String body = c.getString(2);
                if ((type != Telephony.Sms.MESSAGE_TYPE_INBOX && type != Telephony.Sms.MESSAGE_TYPE_SENT) || body == null || body.trim().isEmpty()) continue;
                if (Filters.isSensitive(body)) continue;
                JSONObject o = new JSONObject();
                o.put("id", c.getString(0));
                o.put("address", c.getString(1) == null ? "" : c.getString(1));
                o.put("body", body.length() > 1500 ? body.substring(0, 1500) : body);
                o.put("ts", c.getLong(3) / 1000.0);
                o.put("box", type == Telephony.Sms.MESSAGE_TYPE_SENT ? "sent" : "inbox");
                batch.put(o);
                n++;
                if (batch.length() >= 100) {
                    int s = post(ctx, batch);
                    if (s < 0) return -1;
                    stored += s;
                    batch = new JSONArray();
                }
            }
            if (batch.length() > 0) {
                int s = post(ctx, batch);
                if (s < 0) return -1;
                stored += s;
            }
        } catch (Exception e) {
            return -1;
        }
        Prefs.markSmsSynced(ctx);
        return stored;
    }

    private static int post(Context ctx, JSONArray batch) throws Exception {
        Api.Result r = Api.call(ctx, "POST", "/api/sms/sync", new JSONObject().put("messages", batch), 45000);
        return r.ok() ? r.json().optInt("stored", 0) : -1;
    }
}
