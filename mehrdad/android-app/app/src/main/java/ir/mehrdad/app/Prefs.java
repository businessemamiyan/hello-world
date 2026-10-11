package ir.mehrdad.app;

import android.content.Context;
import android.content.SharedPreferences;

/** تنظیمات روی گوشی: آدرس سرور (پیش‌فرض داخل اپ) و توکن اختصاصی این دستگاه (بعد از جفت‌سازی). */
public class Prefs {
    /** آدرس پیش‌فرض: کاربر نیازی به تایپ آدرس ندارد. */
    public static final String DEFAULT_SERVER = "https://mehrdad.vistaquantum.ir";

    private static final String FILE = "mehrdad_prefs";
    private static final String SERVER_URL = "server_url";
    private static final String TOKEN = "device_token";
    private static final String LAST_UPDATE_CHECK = "last_update_check";
    private static final String PHONE_SERVICE = "phone_service";
    private static final String SMS_ALL = "sms_all";
    private static final String LAST_CONTACTS = "last_contacts_sync";
    private static final String LAST_SMS = "last_sms_sync";

    private static SharedPreferences get(Context ctx) {
        return ctx.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public static String serverUrl(Context ctx) {
        String u = get(ctx).getString(SERVER_URL, "");
        if (u == null || u.trim().isEmpty()) u = DEFAULT_SERVER;
        u = u.trim();
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    public static String token(Context ctx) {
        String t = get(ctx).getString(TOKEN, "");
        return t == null ? "" : t;
    }

    public static boolean isPaired(Context ctx) {
        return serverUrl(ctx).startsWith("https://") && !token(ctx).isEmpty();
    }

    public static void savePairing(Context ctx, String serverUrl, String token) {
        get(ctx).edit().putString(SERVER_URL, serverUrl).putString(TOKEN, token).apply();
    }

    public static void clearToken(Context ctx) {
        get(ctx).edit().remove(TOKEN).apply();
    }

    /** کنترل گوشی (سرویس پس‌زمینه برای پیامک/تماس تأییدشده) روشن است؟ */
    public static boolean phoneService(Context ctx) { return get(ctx).getBoolean(PHONE_SERVICE, false); }

    public static void setPhoneService(Context ctx, boolean on) { get(ctx).edit().putBoolean(PHONE_SERVICE, on).apply(); }

    /** همهٔ پیامک‌های تازه (نه فقط مالی) هم به صندوق مهرداد برود؟ (رمز یک‌بارمصرف همیشه حذف می‌شود) */
    public static boolean smsAll(Context ctx) { return get(ctx).getBoolean(SMS_ALL, false); }

    public static void setSmsAll(Context ctx, boolean on) { get(ctx).edit().putBoolean(SMS_ALL, on).apply(); }

    public static long lastContactsSync(Context ctx) { return get(ctx).getLong(LAST_CONTACTS, 0L); }

    public static void markContactsSynced(Context ctx) { get(ctx).edit().putLong(LAST_CONTACTS, System.currentTimeMillis()).apply(); }

    public static long lastSmsSync(Context ctx) { return get(ctx).getLong(LAST_SMS, 0L); }

    public static void markSmsSynced(Context ctx) { get(ctx).edit().putLong(LAST_SMS, System.currentTimeMillis()).apply(); }

    public static long lastUpdateCheck(Context ctx) {
        return get(ctx).getLong(LAST_UPDATE_CHECK, 0L);
    }

    public static void markUpdateChecked(Context ctx) {
        get(ctx).edit().putLong(LAST_UPDATE_CHECK, System.currentTimeMillis()).apply();
    }
}
