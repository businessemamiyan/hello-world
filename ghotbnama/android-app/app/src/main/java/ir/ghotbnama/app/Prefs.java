package ir.ghotbnama.app;

import android.content.Context;
import android.content.SharedPreferences;

/** تنظیمات ذخیره‌شده روی گوشی: آدرس سرور، کلید ورود اپ، توکن پیامک. */
public class Prefs {
    private static final String FILE = "ghotbnama_prefs";
    public static final String SERVER_URL = "server_url";   // مثلاً https://ghotb.example.ir
    public static final String APP_KEY = "app_key";         // از .env سرور: APP_KEY
    public static final String SMS_TOKEN = "sms_token";     // از .env سرور: SMS_TOKEN

    public static SharedPreferences get(Context ctx) {
        return ctx.getSharedPreferences(FILE, Context.MODE_PRIVATE);
    }

    public static boolean isConfigured(Context ctx) {
        SharedPreferences p = get(ctx);
        String url = p.getString(SERVER_URL, "");
        return url != null && url.startsWith("https://");
    }

    public static String serverUrl(Context ctx) {
        String u = get(ctx).getString(SERVER_URL, "");
        if (u == null) return "";
        while (u.endsWith("/")) u = u.substring(0, u.length() - 1);
        return u;
    }

    public static String appKey(Context ctx) {
        return get(ctx).getString(APP_KEY, "");
    }

    public static String smsToken(Context ctx) {
        return get(ctx).getString(SMS_TOKEN, "");
    }
}
