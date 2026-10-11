package ir.mehrdad.app;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.provider.CallLog;

import androidx.core.content.ContextCompat;

import org.json.JSONArray;
import org.json.JSONObject;

/** تاریخچهٔ تماس‌های چند روز اخیر (ورودی/خروجی/از دست رفته) برای اینکه مهرداد بداند چه کسی زنگ زده. فقط از رشتهٔ پس‌زمینه. */
public class CallLogSync {
    public static boolean hasPermission(Context ctx) {
        return ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CALL_LOG) == PackageManager.PERMISSION_GRANTED;
    }

    /** → تعداد تماس جدید ذخیره‌شده، یا -1 اگر مجوز/جفت‌سازی/اتصال نبود. */
    public static int run(Context ctx, int days) {
        if (!hasPermission(ctx) || !Prefs.isPaired(ctx)) return -1;
        long since = System.currentTimeMillis() - Math.max(1, Math.min(days, 90)) * 86400000L;
        String[] proj = {CallLog.Calls._ID, CallLog.Calls.NUMBER, CallLog.Calls.CACHED_NAME, CallLog.Calls.TYPE, CallLog.Calls.DATE, CallLog.Calls.DURATION};
        int stored = 0;
        JSONArray batch = new JSONArray();
        try (Cursor c = ctx.getContentResolver().query(CallLog.Calls.CONTENT_URI, proj, CallLog.Calls.DATE + ">=?",
                new String[]{String.valueOf(since)}, CallLog.Calls.DATE + " DESC")) {
            if (c == null) return -1;
            int n = 0;
            while (c.moveToNext() && n < 500) {
                String type;
                switch (c.getInt(3)) {
                    case CallLog.Calls.INCOMING_TYPE: type = "incoming"; break;
                    case CallLog.Calls.OUTGOING_TYPE: type = "outgoing"; break;
                    case CallLog.Calls.MISSED_TYPE: type = "missed"; break;
                    case CallLog.Calls.REJECTED_TYPE: type = "rejected"; break;
                    default: continue;
                }
                JSONObject o = new JSONObject();
                o.put("id", c.getString(0));
                o.put("number", c.getString(1) == null ? "" : c.getString(1));
                o.put("name", c.getString(2) == null ? "" : c.getString(2));
                o.put("type", type);
                o.put("ts", c.getLong(4) / 1000.0);
                o.put("duration", Math.max(0, c.getInt(5)));
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
        Prefs.markCallsSynced(ctx);
        return stored;
    }

    private static int post(Context ctx, JSONArray batch) throws Exception {
        Api.Result r = Api.call(ctx, "POST", "/api/calls/sync", new JSONObject().put("calls", batch), 30000);
        return r.ok() ? r.json().optInt("stored", 0) : -1;
    }
}
