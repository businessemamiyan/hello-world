package ir.mehrdad.app;

import android.content.Context;

import androidx.annotation.NonNull;
import androidx.work.Constraints;
import androidx.work.ExistingPeriodicWorkPolicy;
import androidx.work.ExistingWorkPolicy;
import androidx.work.NetworkType;
import androidx.work.OneTimeWorkRequest;
import androidx.work.PeriodicWorkRequest;
import androidx.work.WorkManager;
import androidx.work.Worker;
import androidx.work.WorkerParameters;

import org.json.JSONObject;

import java.util.concurrent.TimeUnit;

/**
 * شبکهٔ امن «کنترل گوشی»: هر ~۱۵ دقیقه (و بلافاصله وقتی سرویس بسته شد) چک می‌کند.
 *  ۱) اگر سرویس پیش‌زمینه مرده، تلاش می‌کند دوباره بالایش بیاورد؛
 *  ۲) اگر هنوز بالا نیست، خودش یک‌بار از سرور می‌پرسد و اقدام‌های تأییدشده را (پیامک/تماس/…) اجرا می‌کند.
 * سرعتش به اندازهٔ سرویس نیست؛ فقط برای وقتی است که سیستم سرویس را کشته.
 */
public class PhoneWorker extends Worker {
    private static final String PERIODIC = "mehrdad-phone-keepalive";
    private static final String SOON = "mehrdad-phone-soon";

    public PhoneWorker(@NonNull Context context, @NonNull WorkerParameters params) {
        super(context, params);
    }

    private static Constraints net() {
        return new Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build();
    }

    /** روشن بودن «کنترل گوشی»: چک دوره‌ای ثبت شود. */
    public static void schedule(Context ctx) {
        PeriodicWorkRequest req = new PeriodicWorkRequest.Builder(PhoneWorker.class, 15, TimeUnit.MINUTES).setConstraints(net()).build();
        WorkManager.getInstance(ctx.getApplicationContext()).enqueueUniquePeriodicWork(PERIODIC, ExistingPeriodicWorkPolicy.KEEP, req);
    }

    public static void cancel(Context ctx) {
        WorkManager wm = WorkManager.getInstance(ctx.getApplicationContext());
        wm.cancelUniqueWork(PERIODIC);
        wm.cancelUniqueWork(SOON);
    }

    /** یک چک فوری (مثلاً وقتی سرویس بسته شد یا کاربر اپ را از اخیرها کشید). */
    public static void runSoon(Context ctx) {
        try {
            OneTimeWorkRequest req = new OneTimeWorkRequest.Builder(PhoneWorker.class).setConstraints(net()).setInitialDelay(5, TimeUnit.SECONDS).build();
            WorkManager.getInstance(ctx.getApplicationContext()).enqueueUniqueWork(SOON, ExistingWorkPolicy.REPLACE, req);
        } catch (Exception ignored) { }
    }

    @NonNull
    @Override
    public Result doWork() {
        Context ctx = getApplicationContext();
        if (!Prefs.isPaired(ctx) || !Prefs.phoneService(ctx)) return Result.success();
        if (PhoneService.isAlive()) return Result.success();
        PhoneService.ensure(ctx);                                           // اگر سیستم اجازه بدهد، سرویس دوباره بالا می‌آید
        for (int i = 0; i < 5; i++) {                                       // و هر چه منتظر مانده را همین‌جا بردار
            Api.Result r = Api.call(ctx, "GET", "/api/phone/next?wait=0", null, 20000);
            if (r.code == 200) {
                JSONObject a = r.json();
                PhoneActions.handle(ctx, a);
            } else if (r.code == 401) {
                Prefs.setPhoneService(ctx, false);
                PhoneActions.notifyInfo(ctx, 4002, "اتصال گوشی قطع شد", "این دستگاه در تلگرام قطع شده؛ دوباره جفتش کن.");
                return Result.success();
            } else if (r.code == 204) {
                break;
            } else {
                return Result.retry();
            }
        }
        return Result.success();
    }
}
