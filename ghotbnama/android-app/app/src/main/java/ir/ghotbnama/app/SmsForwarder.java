package ir.ghotbnama.app;

import android.content.Context;
import android.util.Log;

import org.json.JSONObject;

import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** یک پیامک را به /sms/<SMS_TOKEN> سرور می‌فرستد. بدون هیچ کتابخانه اضافه (فقط HttpURLConnection). */
public class SmsForwarder {
    private static final String TAG = "GhotbSmsForwarder";
    private static final ExecutorService POOL = Executors.newSingleThreadExecutor();

    public static void send(Context ctx, String from, String text) {
        String base = Prefs.serverUrl(ctx);
        String token = Prefs.smsToken(ctx);
        if (base.isEmpty() || token.isEmpty()) {
            Log.w(TAG, "تنظیم نشده؛ پیامک فرستاده نشد.");
            return;
        }
        final String urlStr = base + "/sms/" + token;
        POOL.submit(() -> {
            HttpURLConnection c = null;
            try {
                JSONObject body = new JSONObject();
                body.put("from", from == null ? "" : from);
                body.put("text", text == null ? "" : text);
                byte[] data = body.toString().getBytes(StandardCharsets.UTF_8);

                c = (HttpURLConnection) new URL(urlStr).openConnection();
                c.setRequestMethod("POST");
                c.setConnectTimeout(15000);
                c.setReadTimeout(15000);
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                try (OutputStream os = c.getOutputStream()) {
                    os.write(data);
                }
                int code = c.getResponseCode();
                Log.i(TAG, "sms forward status=" + code);
            } catch (Exception e) {
                Log.w(TAG, "sms forward failed: " + e.getMessage());
            } finally {
                if (c != null) c.disconnect();
            }
        });
    }
}
