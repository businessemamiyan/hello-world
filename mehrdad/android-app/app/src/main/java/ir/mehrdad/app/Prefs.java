package ir.mehrdad.app;

import android.content.Context;
import android.content.SharedPreferences;

/** تنظیمات روی گوشی: آدرس سرور و توکن اختصاصی این دستگاه (بعد از جفت‌سازی با کد تلگرام). */
public class Prefs {
    private static final String FILE = "mehrdad_prefs";
    private static final String SERVER_URL = "server_url";
    private static final String TOKEN = "device_token";

    private static SharedPreferences get(Context ctx) {
        return ctx.getApplicationContext().getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public static String serverUrl(Context ctx) {
        String u = get(ctx).getString(SERVER_URL, "");
        if (u == null) return "";
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
}
