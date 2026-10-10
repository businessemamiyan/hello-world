package ir.mehrdad.app;

import android.content.Context;

import androidx.work.BackoffPolicy;
import androidx.work.Constraints;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.WorkManager;

import org.json.JSONArray;
import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.FileInputStream;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.TimeUnit;

/**
 * صف ماندگار پیامک/اعلان‌های در انتظار ارسال (فایل JSON داخل حافظهٔ خصوصی اپ).
 * اگر اینترنت یا سرور نبود، چیزی گم نمی‌شود؛ WorkManager با backoff دوباره تلاش می‌کند.
 */
public class Outbox {
    private static final String FILE = "outbox.json";
    private static final int MAX_ITEMS = 500;
    private static final Object LOCK = new Object();

    public static void add(Context ctx, String kind, String source, String text) {
        try {
            JSONObject item = new JSONObject();
            item.put("kind", kind);
            item.put("source", source == null ? "" : source);
            item.put("text", text);
            item.put("ts", System.currentTimeMillis() / 1000.0);
            synchronized (LOCK) {
                JSONArray all = load(ctx);
                all.put(item);
                if (all.length() > MAX_ITEMS) {              // قدیمی‌ترین‌ها را دور بریز
                    JSONArray trimmed = new JSONArray();
                    for (int i = all.length() - MAX_ITEMS; i < all.length(); i++) trimmed.put(all.get(i));
                    all = trimmed;
                }
                save(ctx, all);
            }
            schedule(ctx);
        } catch (Exception ignored) { }
    }

    /** تا max مورد از ابتدای صف (بدون حذف). */
    public static JSONArray peek(Context ctx, int max) {
        synchronized (LOCK) {
            JSONArray all = load(ctx);
            JSONArray out = new JSONArray();
            try {
                for (int i = 0; i < Math.min(max, all.length()); i++) out.put(all.get(i));
            } catch (Exception ignored) { }
            return out;
        }
    }

    /** n مورد اول صف را بعد از ارسال موفق حذف کن. */
    public static void drop(Context ctx, int n) {
        synchronized (LOCK) {
            JSONArray all = load(ctx);
            JSONArray rest = new JSONArray();
            try {
                for (int i = n; i < all.length(); i++) rest.put(all.get(i));
            } catch (Exception ignored) { }
            save(ctx, rest);
        }
    }

    public static int size(Context ctx) {
        synchronized (LOCK) { return load(ctx).length(); }
    }

    public static void schedule(Context ctx) {
        Constraints net = new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
        OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(UploadWorker.class)
                .setConstraints(net)
                .setBackoffCriteria(BackoffPolicy.EXPONENTIAL, 30, TimeUnit.SECONDS)
                .build();
        WorkManager.getInstance(ctx.getApplicationContext())
                .enqueueUniqueWork("mehrdad-upload", ExistingWorkPolicy.APPEND_OR_REPLACE, req);
    }

    private static JSONArray load(Context ctx) {
        File f = new File(ctx.getFilesDir(), FILE);
        if (!f.exists()) return new JSONArray();
        try (FileInputStream in = new FileInputStream(f)) {
            byte[] b = new byte[(int) f.length()];
            int off = 0;
            while (off < b.length) {
                int n = in.read(b, off, b.length - off);
                if (n < 0) break;
                off += n;
            }
            return new JSONArray(new String(b, 0, off, StandardCharsets.UTF_8));
        } catch (Exception e) {
            return new JSONArray();
        }
    }

    private static void save(Context ctx, JSONArray arr) {
        File f = new File(ctx.getFilesDir(), FILE);
        File tmp = new File(ctx.getFilesDir(), FILE + ".tmp");
        try (FileOutputStream out = new FileOutputStream(tmp)) {
            out.write(arr.toString().getBytes(StandardCharsets.UTF_8));
        } catch (Exception e) {
            return;
        }
        //noinspection ResultOfMethodCallIgnored
        tmp.renameTo(f);
    }
}
