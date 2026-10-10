package ir.mehrdad.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.provider.Settings;
import android.speech.RecognizerIntent;
import android.view.ViewGroup;
import android.webkit.JavascriptInterface;
import android.webkit.JsPromptResult;
import android.webkit.JsResult;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.Toast;

import androidx.activity.OnBackPressedCallback;
import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import org.json.JSONObject;

import java.util.ArrayList;

/**
 * پوستهٔ بومی مهرداد: داشبورد همان اپ وب سرور (/app) است، پس هر تغییر ظاهر بدون APK جدید می‌آید.
 * فقط چیزهایی بومی‌اند که وب نمی‌تواند: پیامک، اعلان‌ها، صدای گوشی، و به‌روزرسانی خود APK.
 */
public class MainActivity extends AppCompatActivity {
    private WebView web;
    private ActivityResultLauncher<Intent> speech;
    private ActivityResultLauncher<String> smsPermission;

    @SuppressLint({"SetJavaScriptEnabled", "AddJavascriptInterface"})
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setBackgroundColor(Color.parseColor("#0A0F18"));
        root.setFitsSystemWindows(true);

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0A0F18"));
        web.setLayoutParams(new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        WebSettings ws = web.getSettings();
        ws.setJavaScriptEnabled(true);
        ws.setDomStorageEnabled(true);
        ws.setAllowFileAccess(false);
        ws.setAllowContentAccess(false);
        ws.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        ws.setCacheMode(WebSettings.LOAD_DEFAULT);
        web.addJavascriptInterface(new Bridge(), "MehrdadNative");
        web.setWebViewClient(new Client());
        web.setWebChromeClient(new Chrome());
        root.addView(web);
        setContentView(root);

        speech = registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
            Intent data = result.getData();
            if (result.getResultCode() != RESULT_OK || data == null) return;
            ArrayList<String> r = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
            if (r != null && !r.isEmpty()) {
                String js = "window.onVoiceText && window.onVoiceText(" + JSONObject.quote(r.get(0)) + ")";
                web.evaluateJavascript(js, null);
            }
        });
        smsPermission = registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted ->
                Toast.makeText(this, granted ? "دریافت پیامک بانکی فعال شد" : "بدون مجوز پیامک، پیامک بانکی ثبت نمی‌شود",
                        Toast.LENGTH_LONG).show());

        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (web.canGoBack()) web.goBack(); else finish();
            }
        });

        web.loadUrl(Prefs.serverUrl(this) + "/app/");
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (Prefs.isPaired(this)) {
            Outbox.schedule(this);               // صف پیامک/اعلان معوق را دوباره امتحان کن
            Updater.check(this, false);          // بی‌صدا، حداکثر هر ۶ ساعت
        }
    }

    private boolean sameOrigin(Uri u) {
        Uri base = Uri.parse(Prefs.serverUrl(this));
        return u != null && "https".equals(u.getScheme()) && base.getHost() != null && base.getHost().equals(u.getHost());
    }

    private class Client extends WebViewClient {
        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
            Uri u = request.getUrl();
            if (sameOrigin(u)) return false;
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, u));   // لینک بیرونی: مرورگر، نه داخل اپ (پل بومی فقط برای سرور خودمان)
            } catch (ActivityNotFoundException ignored) { }
            return true;
        }

        @Override
        public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
            if (!request.isForMainFrame()) return;
            String base = Prefs.serverUrl(MainActivity.this) + "/app/";
            String html = "<html dir='rtl' lang='fa'><meta name='viewport' content='width=device-width,initial-scale=1'>"
                    + "<body style='background:#0A0F18;color:#E8EDF5;font-family:sans-serif;text-align:center;padding:48px 24px'>"
                    + "<h2>اتصال برقرار نشد</h2><p style='color:#A7B3C5'>اینترنت یا فیلترشکن را چک کن.</p>"
                    + "<p><a style='display:inline-block;margin-top:16px;padding:12px 24px;border-radius:12px;background:#E3B35C;color:#1A1405;"
                    + "text-decoration:none;font-weight:bold' href='" + base + "'>تلاش دوباره</a></p></body></html>";
            view.loadDataWithBaseURL(null, html, "text/html", "UTF-8", null);
        }
    }

    /** مرورگر داخلی confirm/prompt/alert جاوااسکریپت را نشان نمی‌دهد مگر اینجا پیاده شود (اپ وب از آن‌ها استفاده می‌کند). */
    private class Chrome extends WebChromeClient {
        @Override
        public boolean onJsAlert(WebView view, String url, String message, JsResult result) {
            new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setPositiveButton("باشه", (d, w) -> result.confirm()).setOnCancelListener(d -> result.cancel()).show();
            return true;
        }

        @Override
        public boolean onJsConfirm(WebView view, String url, String message, JsResult result) {
            new AlertDialog.Builder(MainActivity.this).setMessage(message)
                    .setPositiveButton("تأیید", (d, w) -> result.confirm())
                    .setNegativeButton("لغو", (d, w) -> result.cancel())
                    .setOnCancelListener(d -> result.cancel()).show();
            return true;
        }

        @Override
        public boolean onJsPrompt(WebView view, String url, String message, String defaultValue, JsPromptResult result) {
            EditText input = new EditText(MainActivity.this);
            input.setText(defaultValue);
            new AlertDialog.Builder(MainActivity.this).setMessage(message).setView(input)
                    .setPositiveButton("تأیید", (d, w) -> result.confirm(input.getText().toString()))
                    .setNegativeButton("لغو", (d, w) -> result.cancel())
                    .setOnCancelListener(d -> result.cancel()).show();
            return true;
        }
    }

    /** پل بومی برای اپ وب (فقط صفحات همین سرور داخل WebView بارگذاری می‌شوند). */
    private class Bridge {
        @JavascriptInterface
        public String getToken() { return Prefs.token(MainActivity.this); }

        @JavascriptInterface
        public void savePairing(String url, String token) {
            if (url == null || !url.startsWith("https://") || token == null || token.isEmpty()) return;
            Prefs.savePairing(MainActivity.this, url, token);
            runOnUiThread(() -> {
                Outbox.schedule(MainActivity.this);
                requestSms();
            });
        }

        @JavascriptInterface
        public void clearToken() { Prefs.clearToken(MainActivity.this); }

        @JavascriptInterface
        public void startVoice() {
            runOnUiThread(() -> {
                Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
                i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fa-IR");
                i.putExtra(RecognizerIntent.EXTRA_PROMPT, "بگو…");
                try {
                    speech.launch(i);
                } catch (ActivityNotFoundException e) {
                    Toast.makeText(MainActivity.this, "تشخیص گفتار در این گوشی نیست (برنامهٔ Google لازم است؛ شاید فیلترشکن هم).", Toast.LENGTH_LONG).show();
                }
            });
        }

        @JavascriptInterface
        public void requestSmsPermission() { runOnUiThread(MainActivity.this::requestSms); }

        @JavascriptInterface
        public void openNotificationAccess() {
            runOnUiThread(() -> startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)));
        }

        @JavascriptInterface
        public void checkUpdate() { runOnUiThread(() -> Updater.check(MainActivity.this, true)); }

        @JavascriptInterface
        public String status() {
            try {
                boolean sms = ContextCompat.checkSelfPermission(MainActivity.this, Manifest.permission.RECEIVE_SMS)
                        == PackageManager.PERMISSION_GRANTED;
                boolean notif = NotificationManagerCompat.getEnabledListenerPackages(MainActivity.this)
                        .contains(getPackageName());
                return new JSONObject().put("sms", sms).put("notif", notif).put("queue", Outbox.size(MainActivity.this))
                        .put("version", Updater.installedVersionName(MainActivity.this))
                        .put("code", Updater.installedVersionCode(MainActivity.this)).toString();
            } catch (Exception e) {
                return "{}";
            }
        }
    }

    private void requestSms() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS) != PackageManager.PERMISSION_GRANTED)
            smsPermission.launch(Manifest.permission.RECEIVE_SMS);
    }
}
