package ir.mehrdad.app;

import android.app.Activity;
import android.content.Intent;
import android.content.pm.PackageInfo;
import android.net.Uri;
import android.provider.Settings;
import android.widget.Toast;

import androidx.appcompat.app.AlertDialog;
import androidx.core.content.FileProvider;

import org.json.JSONObject;

import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;

/**
 * به‌روزرسانی از داخل خود اپ: نسخهٔ سرور (/api/app/version) رو می‌خونه؛ اگه جدیدتر بود APK رو دانلود،
 * SHA-256 رو چک و نصب‌کنندهٔ اندروید رو باز می‌کنه. اندروید فقط APK هم‌امضا (همون کلید) رو روی نسخهٔ فعلی می‌نشونه.
 */
public class Updater {
    private static final long CHECK_EVERY_MS = 6L * 3600 * 1000;
    private static volatile boolean running = false;

    public static long installedVersionCode(Activity a) {
        try {
            PackageInfo p = a.getPackageManager().getPackageInfo(a.getPackageName(), 0);
            return p.getLongVersionCode();
        } catch (Exception e) {
            return 0;
        }
    }

    public static String installedVersionName(Activity a) {
        try {
            return a.getPackageManager().getPackageInfo(a.getPackageName(), 0).versionName;
        } catch (Exception e) {
            return "?";
        }
    }

    /** manual=true: همیشه نتیجه رو نشان بده؛ false: بی‌صدا و حداکثر هر ۶ ساعت. */
    public static void check(Activity act, boolean manual) {
        if (running) return;
        if (!manual && System.currentTimeMillis() - Prefs.lastUpdateCheck(act) < CHECK_EVERY_MS) return;
        running = true;
        new Thread(() -> {
            try {
                Api.Result r = Api.call(act, Prefs.serverUrl(act), "GET", "/api/app/version", null, false, 15000);
                if (!r.ok()) {
                    if (manual) toast(act, "سرور جواب نمی‌ده (" + r.code + ")");
                    return;
                }
                Prefs.markUpdateChecked(act);
                JSONObject v = r.json();
                long remote = v.optLong("versionCode", 0);
                if (remote <= installedVersionCode(act)) {
                    if (manual) toast(act, "اپت به‌روزه (نسخهٔ " + installedVersionName(act) + ")");
                    return;
                }
                final String name = v.optString("versionName", String.valueOf(remote));
                final String notes = v.optString("notes", "");
                final String sha = v.optString("sha256", "");
                final String url = Prefs.serverUrl(act) + v.optString("url", "/download/mehrdad.apk");
                act.runOnUiThread(() -> new AlertDialog.Builder(act)
                        .setTitle("نسخهٔ جدید مهرداد " + name)
                        .setMessage(notes.isEmpty() ? "یه نسخهٔ تازه آماده‌ست." : notes)
                        .setPositiveButton("به‌روزرسانی", (d, w) -> download(act, url, sha))
                        .setNegativeButton("بعداً", null)
                        .show());
            } finally {
                running = false;
            }
        }).start();
    }

    private static void download(Activity act, String url, String expectedSha) {
        AlertDialog[] dlg = new AlertDialog[1];
        act.runOnUiThread(() -> dlg[0] = new AlertDialog.Builder(act).setTitle("در حال دانلود…")
                .setMessage("یه لحظه صبر کن").setCancelable(false).show());
        new Thread(() -> {
            File out = null;
            try {
                File dir = new File(act.getCacheDir(), "updates");
                //noinspection ResultOfMethodCallIgnored
                dir.mkdirs();
                out = new File(dir, "mehrdad-update.apk");
                HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
                c.setConnectTimeout(20000);
                c.setReadTimeout(60000);
                if (c.getResponseCode() != 200) throw new Exception("HTTP " + c.getResponseCode());
                MessageDigest md = MessageDigest.getInstance("SHA-256");
                try (InputStream in = c.getInputStream(); FileOutputStream fo = new FileOutputStream(out)) {
                    byte[] buf = new byte[16384];
                    int n;
                    while ((n = in.read(buf)) > 0) {
                        fo.write(buf, 0, n);
                        md.update(buf, 0, n);
                    }
                }
                StringBuilder hex = new StringBuilder();
                for (byte b : md.digest()) hex.append(String.format("%02x", b));
                if (!expectedSha.isEmpty() && !hex.toString().equalsIgnoreCase(expectedSha))
                    throw new Exception("checksum mismatch");
                final File apk = out;
                act.runOnUiThread(() -> {
                    if (dlg[0] != null) dlg[0].dismiss();
                    install(act, apk);
                });
            } catch (Exception e) {
                if (out != null) //noinspection ResultOfMethodCallIgnored
                    out.delete();
                act.runOnUiThread(() -> {
                    if (dlg[0] != null) dlg[0].dismiss();
                    Toast.makeText(act, "دانلود نشد: " + e.getMessage(), Toast.LENGTH_LONG).show();
                });
            }
        }).start();
    }

    private static void install(Activity act, File apk) {
        if (!act.getPackageManager().canRequestPackageInstalls()) {
            Toast.makeText(act, "اجازهٔ «نصب برنامه‌های ناشناس» رو برای مهرداد روشن کن و دوباره به‌روزرسانی رو بزن", Toast.LENGTH_LONG).show();
            act.startActivity(new Intent(Settings.ACTION_MANAGE_UNKNOWN_APP_SOURCES, Uri.parse("package:" + act.getPackageName())));
            return;
        }
        Uri uri = FileProvider.getUriForFile(act, act.getPackageName() + ".fileprovider", apk);
        Intent i = new Intent(Intent.ACTION_VIEW);
        i.setDataAndType(uri, "application/vnd.android.package-archive");
        i.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_ACTIVITY_NEW_TASK);
        act.startActivity(i);
    }

    private static void toast(Activity a, String m) {
        a.runOnUiThread(() -> Toast.makeText(a, m, Toast.LENGTH_LONG).show());
    }
}
