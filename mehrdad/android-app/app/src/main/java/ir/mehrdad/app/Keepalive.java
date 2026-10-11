package ir.mehrdad.app;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.os.Build;
import android.os.PowerManager;
import android.provider.Settings;

/** کمک برای اینکه سیستم (به‌خصوص MIUI شیائومی) سرویس پس‌زمینه را نکُشد: معافیت از بهینه‌سازی باتری و «شروع خودکار». */
public final class Keepalive {
    private Keepalive() { }

    public static boolean ignoringBattery(Context ctx) {
        PowerManager pm = (PowerManager) ctx.getSystemService(Context.POWER_SERVICE);
        return pm != null && pm.isIgnoringBatteryOptimizations(ctx.getPackageName());
    }

    public static boolean isXiaomi() {
        String m = (Build.MANUFACTURER + " " + Build.BRAND).toLowerCase();
        return m.contains("xiaomi") || m.contains("redmi") || m.contains("poco");
    }

    /** پنجرهٔ مستقیم سیستم: «اجازه بدی همیشه در پس‌زمینه کار کنه؟» (اگر نشد، لیست تنظیمات باتری). */
    public static void requestIgnoreBattery(Activity a) {
        try {
            a.startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:" + a.getPackageName())));
        } catch (Exception e) {
            try { a.startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS)); }
            catch (Exception e2) { openAppDetails(a); }
        }
    }

    /** صفحهٔ «شروع خودکار» (Autostart) سازنده‌های رایج؛ اگر پیدا نشد، اطلاعات برنامه. */
    public static void openAutostart(Activity a) {
        String[][] targets = {
                {"com.miui.securitycenter", "com.miui.permcenter.autostart.AutoStartManagementActivity"},
                {"com.huawei.systemmanager", "com.huawei.systemmanager.startupmgr.ui.StartupNormalAppListActivity"},
                {"com.coloros.safecenter", "com.coloros.safecenter.permission.startup.StartupAppListActivity"},
                {"com.oppo.safe", "com.oppo.safe.permission.startup.StartupAppListActivity"},
                {"com.vivo.permissionmanager", "com.vivo.permissionmanager.activity.BgStartUpManagerActivity"},
                {"com.samsung.android.lool", "com.samsung.android.sm.ui.battery.BatteryActivity"},
        };
        for (String[] t : targets) {
            try {
                a.startActivity(new Intent().setComponent(new ComponentName(t[0], t[1])).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
                return;
            } catch (Exception ignored) { }
        }
        openAppDetails(a);
    }

    /** MIUI: «ذخیرهٔ باتری» همین برنامه ← «بدون محدودیت». */
    public static void openMiuiBattery(Activity a) {
        try {
            Intent i = new Intent().setComponent(new ComponentName("com.miui.powerkeeper", "com.miui.powerkeeper.ui.HiddenAppsConfigActivity"))
                    .putExtra("package_name", a.getPackageName()).putExtra("package_label", "MEHRDAD").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            a.startActivity(i);
        } catch (Exception e) {
            requestIgnoreBattery(a);
        }
    }

    public static void openAppDetails(Activity a) {
        try { a.startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", a.getPackageName(), null))); }
        catch (Exception ignored) { }
    }
}
