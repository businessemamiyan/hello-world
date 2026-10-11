package ir.mehrdad.app;

import android.Manifest;
import android.content.ContentUris;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.net.Uri;
import android.provider.CalendarContract;

import androidx.core.content.ContextCompat;

import org.json.JSONArray;
import org.json.JSONObject;

/** رویدادهای تقویم گوشی در ۱۴ روز آینده را به مهرداد می‌دهد تا برنامه‌ریزی و مربی از جلسه‌هایت خبر داشته باشند. */
public class CalendarSync {
    public static boolean hasPermission(Context ctx) {
        return ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CALENDAR) == PackageManager.PERMISSION_GRANTED;
    }

    /** → تعداد رویداد، یا -1 اگر مجوز/جفت‌سازی/اتصال نبود. */
    public static int run(Context ctx) {
        if (!hasPermission(ctx) || !Prefs.isPaired(ctx)) return -1;
        long now = System.currentTimeMillis();
        Uri.Builder b = CalendarContract.Instances.CONTENT_URI.buildUpon();
        ContentUris.appendId(b, now - 3600_000L);
        ContentUris.appendId(b, now + 14L * 86400000L);
        String[] proj = {CalendarContract.Instances.EVENT_ID, CalendarContract.Instances.TITLE, CalendarContract.Instances.BEGIN,
                CalendarContract.Instances.END, CalendarContract.Instances.EVENT_LOCATION};
        JSONArray events = new JSONArray();
        try (Cursor c = ctx.getContentResolver().query(b.build(), proj, null, null, CalendarContract.Instances.BEGIN + " ASC")) {
            if (c == null) return -1;
            while (c.moveToNext() && events.length() < 300) {
                JSONObject o = new JSONObject();
                o.put("id", c.getString(0) + ":" + c.getLong(2));
                o.put("title", c.getString(1) == null ? "" : c.getString(1));
                o.put("start", c.getLong(2) / 1000.0);
                o.put("end", c.getLong(3) / 1000.0);
                o.put("location", c.getString(4) == null ? "" : c.getString(4));
                events.put(o);
            }
            Api.Result r = Api.call(ctx, "POST", "/api/calendar/sync", new JSONObject().put("events", events), 30000);
            if (!r.ok()) return -1;
        } catch (Exception e) {
            return -1;
        }
        Prefs.markCalendarSynced(ctx);
        return events.length();
    }
}
