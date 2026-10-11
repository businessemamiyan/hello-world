package ir.mehrdad.app;

import android.Manifest;
import android.content.Context;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.provider.ContactsContract;

import androidx.core.content.ContextCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** مخاطبین گوشی (نام + شماره‌ها) را به سرور شخصی مهرداد می‌فرستد تا «به علی پیامک بزن» بفهمد علی کیست. فقط از رشتهٔ پس‌زمینه صدا بزن. */
public class ContactsSync {
    public static boolean hasPermission(Context ctx) {
        return ContextCompat.checkSelfPermission(ctx, Manifest.permission.READ_CONTACTS) == PackageManager.PERMISSION_GRANTED;
    }

    /** → تعداد مخاطب‌های ارسال‌شده، یا -1 اگر مجوز/جفت‌سازی/اتصال نبود. */
    public static int run(Context ctx) {
        if (!hasPermission(ctx) || !Prefs.isPaired(ctx)) return -1;
        Map<String, JSONObject> byId = new LinkedHashMap<>();
        String[] proj = {ContactsContract.CommonDataKinds.Phone.CONTACT_ID, ContactsContract.CommonDataKinds.Phone.DISPLAY_NAME,
                ContactsContract.CommonDataKinds.Phone.NUMBER};
        try (Cursor c = ctx.getContentResolver().query(ContactsContract.CommonDataKinds.Phone.CONTENT_URI, proj, null, null, null)) {
            if (c == null) return -1;
            while (c.moveToNext()) {
                String id = c.getString(0), name = c.getString(1), num = c.getString(2);
                if (id == null || name == null || num == null || num.trim().isEmpty()) continue;
                JSONObject o = byId.get(id);
                if (o == null) {
                    o = new JSONObject();
                    o.put("key", id);
                    o.put("name", name.length() > 100 ? name.substring(0, 100) : name);
                    o.put("numbers", new JSONArray());
                    byId.put(id, o);
                }
                JSONArray nums = o.getJSONArray("numbers");
                if (nums.length() < 6) nums.put(num.trim().length() > 32 ? num.trim().substring(0, 32) : num.trim());
            }
        } catch (Exception e) {
            return -1;
        }
        List<JSONObject> all = new ArrayList<>(byId.values());
        if (all.size() > 5000) all = all.subList(0, 5000);
        try {
            for (int i = 0; i < Math.max(1, all.size()); i += 300) {
                JSONArray chunk = new JSONArray();
                for (int j = i; j < Math.min(all.size(), i + 300); j++) chunk.put(all.get(j));
                JSONObject body = new JSONObject();
                body.put("contacts", chunk);
                body.put("replace", i == 0);            // تکهٔ اول همه‌چیز قبلی را جایگزین می‌کند (مخاطب حذف‌شده هم از سرور می‌رود)
                Api.Result r = Api.call(ctx, "PUT", "/api/contacts", body, 30000);
                if (!r.ok()) return -1;
            }
        } catch (Exception e) {
            return -1;
        }
        Prefs.markContactsSynced(ctx);
        return all.size();
    }
}
