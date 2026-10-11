package ir.mehrdad.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** بعد از روشن‌شدن گوشی یا به‌روزرسانی اپ، اگر «کنترل گوشی» روشن بود سرویس دوباره بالا می‌آید. */
public class BootReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        try {
            if (Prefs.isPaired(context) && Prefs.phoneService(context)) {
                PhoneWorker.schedule(context);
                PhoneService.ensure(context);
            }
        } catch (Exception ignored) { }
    }
}
