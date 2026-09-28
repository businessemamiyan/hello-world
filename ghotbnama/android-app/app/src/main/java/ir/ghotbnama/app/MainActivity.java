package ir.ghotbnama.app;

import android.Manifest;
import android.app.AlertDialog;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.text.InputType;
import android.view.Menu;
import android.view.MenuItem;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.ActivityCompat;
import androidx.core.content.ContextCompat;
import androidx.swiperefreshlayout.widget.SwipeRefreshLayout;

/**
 * اپ قطب‌نما روی اندروید: یک WebView به سرور شخصی کاربر + دریافت خودکار پیامک بانک.
 * هیچ محتوایی داخل اپ بسته‌بندی نشده؛ همه‌چیز از سرور خود کاربر می‌آید (Mini App همان اپ وب).
 */
public class MainActivity extends AppCompatActivity {
    private static final int REQ_SMS = 1001;
    private WebView webView;
    private SwipeRefreshLayout refresh;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        webView = new WebView(this);
        webView.setLayoutParams(new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        webView.setBackgroundColor(Color.parseColor("#0A0F18"));
        WebSettings ws = webView.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setDatabaseEnabled(true);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        ws.setCacheMode(WebSettings.LOAD_DEFAULT);
        webView.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, String url) {
                String base = Prefs.serverUrl(MainActivity.this);
                if (url != null && !base.isEmpty() && url.startsWith(base)) {
                    return false; // همان دامنه سرور: داخل اپ باز شود
                }
                try {
                    startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                } catch (Exception ignored) { }
                return true;
            }
        });

        refresh = new SwipeRefreshLayout(this);
        refresh.setLayoutParams(new ViewGroup.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        refresh.addView(webView);
        refresh.setOnRefreshListener(() -> { webView.reload(); refresh.setRefreshing(false); });
        setContentView(refresh);

        if (Prefs.isConfigured(this)) {
            loadApp();
        } else {
            showSetupDialog(true);
        }
        requestSmsPermissionIfNeeded();
    }

    private void loadApp() {
        String url = Prefs.serverUrl(this) + "/app";
        String key = Prefs.appKey(this);
        if (!key.isEmpty()) url += "?key=" + Uri.encode(key);
        webView.loadUrl(url);
    }

    /** دیالوگ تنظیم آدرس سرور، کلید ورود اپ و توکن پیامک — مقادیر از فایل .env سرور (server/.env) می‌آیند. */
    private void showSetupDialog(boolean firstRun) {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        int pad = (int) (20 * getResources().getDisplayMetrics().density);
        box.setPadding(pad, pad, pad, pad);

        TextView help = new TextView(this);
        help.setText("این سه مقدار را از فایل .env سرورت (ghotbnama/server/.env) کپی کن:");
        help.setPadding(0, 0, 0, pad / 2);
        box.addView(help);

        EditText urlEdit = field("آدرس سرور (مثل https://ghotb.example.ir)", Prefs.serverUrl(this), InputType.TYPE_TEXT_VARIATION_URI);
        EditText keyEdit = field("APP_KEY", Prefs.appKey(this), InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        EditText smsEdit = field("SMS_TOKEN", Prefs.smsToken(this), InputType.TYPE_TEXT_VARIATION_VISIBLE_PASSWORD);
        box.addView(urlEdit);
        box.addView(keyEdit);
        box.addView(smsEdit);

        AlertDialog.Builder b = new AlertDialog.Builder(this)
                .setTitle("تنظیمات سرور")
                .setView(box)
                .setCancelable(!firstRun)
                .setPositiveButton("ذخیره", (d, w) -> {
                    String url = urlEdit.getText().toString().trim();
                    while (url.endsWith("/")) url = url.substring(0, url.length() - 1);
                    if (!url.startsWith("https://")) {
                        Toast.makeText(this, "آدرس باید با https:// شروع شود.", Toast.LENGTH_LONG).show();
                        showSetupDialog(firstRun);
                        return;
                    }
                    SharedPreferences.Editor e = Prefs.get(this).edit();
                    e.putString(Prefs.SERVER_URL, url);
                    e.putString(Prefs.APP_KEY, keyEdit.getText().toString().trim());
                    e.putString(Prefs.SMS_TOKEN, smsEdit.getText().toString().trim());
                    e.apply();
                    loadApp();
                });
        if (!firstRun) b.setNegativeButton("انصراف", null);
        b.show();
    }

    private EditText field(String hint, String value, int inputType) {
        EditText e = new EditText(this);
        e.setHint(hint);
        e.setText(value);
        e.setInputType(InputType.TYPE_CLASS_TEXT | inputType);
        e.setSingleLine(true);
        return e;
    }

    private void requestSmsPermissionIfNeeded() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) == PackageManager.PERMISSION_GRANTED) {
            return;
        }
        new AlertDialog.Builder(this)
                .setTitle("دسترسی به پیامک")
                .setMessage("برای ثبت خودکار پیامک‌های بانک (واریز/برداشت)، قطب‌نما به مجوز خواندن پیامک نیاز دارد. اگر اجازه ندهی، بقیه اپ عادی کار می‌کند و فقط این بخش غیرفعال می‌ماند.")
                .setPositiveButton("اجازه بده", (d, w) -> ActivityCompat.requestPermissions(this,
                        new String[]{Manifest.permission.RECEIVE_SMS, Manifest.permission.READ_SMS}, REQ_SMS))
                .setNegativeButton("فعلاً نه", null)
                .show();
    }

    @Override
    public void onRequestPermissionsResult(int requestCode, @NonNull String[] permissions, @NonNull int[] grantResults) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults);
        if (requestCode == REQ_SMS) {
            boolean granted = grantResults.length > 0 && grantResults[0] == PackageManager.PERMISSION_GRANTED;
            Toast.makeText(this, granted ? "دسترسی پیامک فعال شد." : "دسترسی پیامک رد شد؛ بعداً از تنظیمات اندروید قابل تغییر است.", Toast.LENGTH_LONG).show();
        }
    }

    @Override
    public boolean onCreateOptionsMenu(Menu menu) {
        menu.add(0, 1, 0, "تنظیمات سرور");
        menu.add(0, 2, 1, "بارگذاری دوباره");
        return true;
    }

    @Override
    public boolean onOptionsItemSelected(MenuItem item) {
        if (item.getItemId() == 1) { showSetupDialog(false); return true; }
        if (item.getItemId() == 2) { webView.reload(); return true; }
        return super.onOptionsItemSelected(item);
    }

    @Override
    public void onBackPressed() {
        if (webView.canGoBack()) webView.goBack();
        else super.onBackPressed();
    }
}
