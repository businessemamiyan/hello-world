package ir.mehrdad.app;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONArray;
import org.json.JSONObject;

/** صف Outbox را دسته‌ای (حداکثر ۵۰ مورد) به /api/ingest می‌فرستد. */
public class UploadWorker extends Worker {
    public UploadWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    @NonNull
    @Override
    public Result doWork() {
        Context ctx = getApplicationContext();
        if (!Prefs.isPaired(ctx)) return Result.success();   // هنوز جفت نشده؛ صف می‌ماند
        while (true) {
            JSONArray batch = Outbox.peek(ctx, 50);
            if (batch.length() == 0) return Result.success();
            try {
                JSONObject body = new JSONObject().put("items", batch);
                Api.Result r = Api.call(ctx, "POST", "/api/ingest", body, 30000);
                if (r.ok()) {
                    Outbox.drop(ctx, batch.length());
                } else if (r.code == 401) {
                    Prefs.clearToken(ctx);                   // دستگاه در تلگرام قطع شده؛ دیگر نفرست
                    return Result.success();
                } else if (r.code == 422) {
                    Outbox.drop(ctx, batch.length());        // دادهٔ نامعتبر؛ صف را گیر نینداز
                } else {
                    return Result.retry();                   // شبکه/سرور؛ بعداً با backoff
                }
            } catch (Exception e) {
                return Result.retry();
            }
        }
    }
}
