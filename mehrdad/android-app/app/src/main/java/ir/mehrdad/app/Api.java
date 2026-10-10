package ir.mehrdad.app;

import android.content.Context;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;

/** کلاینت ساده‌ی HTTPS برای سرور مهرداد؛ بدون هیچ کتابخانهٔ اضافه. فقط از رشته‌ی پس‌زمینه صدا بزن. */
public class Api {
    public static class Result {
        public final int code;        // 0 = خطای شبکه
        public final String body;
        Result(int code, String body) { this.code = code; this.body = body; }
        public boolean ok() { return code >= 200 && code < 300; }
        public JSONObject json() {
            try { return new JSONObject(body); } catch (Exception e) { return new JSONObject(); }
        }
    }

    /** method: GET یا POST؛ withAuth: توکن دستگاه را بفرست. */
    public static Result call(Context ctx, String base, String method, String path, JSONObject json,
                              boolean withAuth, int readTimeoutMs) {
        HttpURLConnection c = null;
        try {
            if (base == null || !base.startsWith("https://")) return new Result(0, "server url must be https");
            c = (HttpURLConnection) new URL(base + path).openConnection();
            c.setRequestMethod(method);
            c.setConnectTimeout(15000);
            c.setReadTimeout(readTimeoutMs);
            c.setRequestProperty("Accept", "application/json");
            if (withAuth) c.setRequestProperty("Authorization", "Bearer " + Prefs.token(ctx));
            if (json != null) {
                byte[] data = json.toString().getBytes(StandardCharsets.UTF_8);
                c.setDoOutput(true);
                c.setRequestProperty("Content-Type", "application/json; charset=utf-8");
                try (OutputStream os = c.getOutputStream()) { os.write(data); }
            }
            int code = c.getResponseCode();
            InputStream in = code >= 400 ? c.getErrorStream() : c.getInputStream();
            return new Result(code, in == null ? "" : readAll(in));
        } catch (Exception e) {
            return new Result(0, String.valueOf(e.getMessage()));
        } finally {
            if (c != null) c.disconnect();
        }
    }

    public static Result call(Context ctx, String method, String path, JSONObject json, int readTimeoutMs) {
        return call(ctx, Prefs.serverUrl(ctx), method, path, json, true, readTimeoutMs);
    }

    private static String readAll(InputStream in) throws Exception {
        try (InputStream is = in; ByteArrayOutputStream out = new ByteArrayOutputStream()) {
            byte[] buf = new byte[4096];
            int n;
            while ((n = is.read(buf)) > 0) out.write(buf, 0, n);
            return out.toString("UTF-8");
        }
    }
}
