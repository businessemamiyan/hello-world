package ir.mehrdad.app;

import android.Manifest;
import android.annotation.SuppressLint;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.media.AudioManager;
import android.os.Handler;
import android.os.Looper;
import android.provider.MediaStore;
import android.speech.RecognitionListener;
import android.speech.SpeechRecognizer;
import android.view.Gravity;
import android.webkit.ValueCallback;
import android.widget.LinearLayout;
import android.widget.TextView;
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

import androidx.core.content.FileProvider;

import org.json.JSONObject;

import java.io.File;
import java.io.IOException;
import java.util.ArrayList;

/**
 * پوستهٔ بومی مهرداد: داشبورد همان اپ وب سرور (/app) است، پس هر تغییر ظاهر بدون APK جدید می‌آید.
 * فقط چیزهایی بومی‌اند که وب نمی‌تواند: پیامک، اعلان‌ها، صدای گوشی، و به‌روزرسانی خود APK.
 */
public class MainActivity extends AppCompatActivity {
    private WebView web;
    private ActivityResultLauncher<Intent> speech;
    private ActivityResultLauncher<String> smsPermission;
    private ActivityResultLauncher<String> micPermission;
    private ActivityResultLauncher<Intent> fileChooser;
    private ValueCallback<Uri[]> filePathCb;
    private Uri cameraUri;
    private Voice voice;

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

        micPermission = registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> {
            if (granted) startVoice();
            else Toast.makeText(this, "بدون مجوز میکروفون نمی‌شود حرف زد", Toast.LENGTH_LONG).show();
        });
        fileChooser = registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
            if (filePathCb == null) return;
            Uri[] res = null;
            if (result.getResultCode() == RESULT_OK) {
                Intent d = result.getData();
                if (d != null && d.getData() != null) res = new Uri[]{d.getData()};
                else if (cameraUri != null) {
                    File f = new File(getCacheDir(), "images/" + cameraUri.getLastPathSegment());
                    if (f.exists() && f.length() > 0) res = new Uri[]{cameraUri};
                }
            }
            filePathCb.onReceiveValue(res);
            filePathCb = null;
        });

        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (web.canGoBack()) web.goBack(); else finish();
            }
        });

        web.loadUrl(Prefs.serverUrl(this) + "/app/");
    }

    @Override
    protected void onDestroy() {
        if (voice != null) voice.finish(false);
        super.onDestroy();
    }

    /** ویس پیوسته: تشخیص گفتار را بعد از هر مکث دوباره شروع می‌کند تا کاربر حرفش را کامل بزند؛ فقط با «تمام» تمام می‌شود. */
    private class Voice implements RecognitionListener {
        private final SpeechRecognizer sr = SpeechRecognizer.createSpeechRecognizer(MainActivity.this);
        private final Handler h = new Handler(Looper.getMainLooper());
        private final StringBuilder done = new StringBuilder();
        private String partial = "";
        private boolean active = true;
        private int fails = 0;
        private AlertDialog dlg;
        private TextView live;
        private final AudioManager am = (AudioManager) getSystemService(AUDIO_SERVICE);
        private final int[] streams = {AudioManager.STREAM_NOTIFICATION, AudioManager.STREAM_SYSTEM, AudioManager.STREAM_MUSIC};

        void begin() {
            sr.setRecognitionListener(this);
            LinearLayout box = new LinearLayout(MainActivity.this);
            box.setOrientation(LinearLayout.VERTICAL);
            box.setPadding(48, 32, 48, 8);
            TextView hint = new TextView(MainActivity.this);
            hint.setText("🎤 هر قدر می‌خواهی حرف بزن؛ مکث مهم نیست.\nوقتی تمام شد «تمام» را بزن.");
            hint.setGravity(Gravity.CENTER);
            live = new TextView(MainActivity.this);
            live.setTextSize(17);
            live.setPadding(0, 24, 0, 8);
            live.setMinLines(3);
            box.addView(hint);
            box.addView(live);
            dlg = new AlertDialog.Builder(MainActivity.this).setView(box).setCancelable(false)
                    .setPositiveButton("تمام", (d, w) -> finish(true))
                    .setNegativeButton("لغو", (d, w) -> finish(false)).show();
            mute(true);
            listen();
        }

        private void mute(boolean on) {
            for (int s : streams) {
                try { am.adjustStreamVolume(s, on ? AudioManager.ADJUST_MUTE : AudioManager.ADJUST_UNMUTE, 0); } catch (Exception ignored) { }
            }
        }

        private void listen() {
            if (!active) return;
            Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fa-IR");
            i.putExtra(RecognizerIntent.EXTRA_PARTIAL_RESULTS, true);
            i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_COMPLETE_SILENCE_LENGTH_MILLIS, 15000L);
            i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_POSSIBLY_COMPLETE_SILENCE_LENGTH_MILLIS, 15000L);
            i.putExtra(RecognizerIntent.EXTRA_SPEECH_INPUT_MINIMUM_LENGTH_MILLIS, 60000L);
            i.putExtra(RecognizerIntent.EXTRA_CALLING_PACKAGE, getPackageName());
            try { sr.startListening(i); } catch (Exception e) { finish(true); }
        }

        private void show() {
            String t = (done + " " + partial).trim();
            if (live != null) live.setText(t.isEmpty() ? "…" : t);
        }

        private void append(ArrayList<String> r) {
            if (r != null && !r.isEmpty() && !r.get(0).trim().isEmpty()) {
                if (done.length() > 0) done.append(' ');
                done.append(r.get(0).trim());
            }
            partial = "";
            show();
        }

        void finish(boolean deliver) {
            if (!active) return;
            active = false;
            h.removeCallbacksAndMessages(null);
            try { sr.cancel(); sr.destroy(); } catch (Exception ignored) { }
            mute(false);
            try { if (dlg != null) dlg.dismiss(); } catch (Exception ignored) { }
            voice = null;
            String text = (done + " " + partial).trim();
            if (deliver && !text.isEmpty()) web.evaluateJavascript("window.onVoiceText && window.onVoiceText(" + JSONObject.quote(text) + ")", null);
        }

        @Override public void onResults(Bundle b) {
            append(b == null ? null : b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION));
            fails = 0;
            h.postDelayed(this::listen, 120);
        }
        @Override public void onPartialResults(Bundle b) {
            ArrayList<String> r = b == null ? null : b.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
            if (r != null && !r.isEmpty()) { partial = r.get(0); show(); }
        }
        @Override public void onError(int error) {
            if (!active) return;
            if (!partial.isEmpty()) { done.append(done.length() > 0 ? " " : "").append(partial); partial = ""; show(); }
            if (error == SpeechRecognizer.ERROR_NO_MATCH || error == SpeechRecognizer.ERROR_SPEECH_TIMEOUT) { h.postDelayed(this::listen, 150); return; }
            if (error == SpeechRecognizer.ERROR_RECOGNIZER_BUSY && fails++ < 5) { try { sr.cancel(); } catch (Exception ignored) { } h.postDelayed(this::listen, 500); return; }
            if (error == SpeechRecognizer.ERROR_INSUFFICIENT_PERMISSIONS) { Toast.makeText(MainActivity.this, "مجوز میکروفون لازم است", Toast.LENGTH_LONG).show(); finish(false); return; }
            if (error == SpeechRecognizer.ERROR_NETWORK || error == SpeechRecognizer.ERROR_NETWORK_TIMEOUT || error == SpeechRecognizer.ERROR_SERVER) {
                if (fails++ < 3) { h.postDelayed(this::listen, 800); return; }
                Toast.makeText(MainActivity.this, "تشخیص گفتار به اینترنت/فیلترشکن نیاز دارد", Toast.LENGTH_LONG).show();
            }
            finish(true);
        }
        @Override public void onReadyForSpeech(Bundle p) { }
        @Override public void onBeginningOfSpeech() { }
        @Override public void onRmsChanged(float v) { }
        @Override public void onBufferReceived(byte[] b) { }
        @Override public void onEndOfSpeech() { }
        @Override public void onEvent(int t, Bundle b) { }
    }

    private void startVoice() {
        if (voice != null) return;
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            micPermission.launch(Manifest.permission.RECORD_AUDIO);
            return;
        }
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {          // بدون سرویس Google: همان پنجرهٔ قدیمی سیستم
            Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
            i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fa-IR");
            try { speech.launch(i); } catch (ActivityNotFoundException e) {
                Toast.makeText(this, "تشخیص گفتار در این گوشی نیست (برنامهٔ Google لازم است؛ شاید فیلترشکن هم).", Toast.LENGTH_LONG).show();
            }
            return;
        }
        voice = new Voice();
        voice.begin();
    }

    /** راهنمای «Restricted setting»: اندروید ۱۳+ برای اپ‌های خارج از فروشگاه، دسترسی اعلان‌ها را تا تأیید دستی قفل می‌کند. */
    private void showNotificationAccessGuide() {
        new AlertDialog.Builder(this)
                .setTitle("دسترسی اعلان‌ها")
                .setMessage("اگر پیام «Restricted setting» دیدی، یک‌بار این کار لازم است:\n\n"
                        + "۱) «اطلاعات برنامه» را باز کن\n"
                        + "۲) سه‌نقطهٔ بالا-راست ⋮ را بزن\n"
                        + "۳) «Allow restricted settings» (اجازهٔ تنظیمات محدودشده) را بزن و تأیید کن\n"
                        + "۴) برگرد و دوباره «دسترسی اعلان‌ها» را بزن و MEHRDAD را روشن کن")
                .setPositiveButton("اطلاعات برنامه", (d, w) -> startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS,
                        Uri.fromParts("package", getPackageName(), null))))
                .setNeutralButton("دسترسی اعلان‌ها", (d, w) -> startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)))
                .setNegativeButton("بستن", null).show();
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
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> callback, FileChooserParams params) {
            if (filePathCb != null) filePathCb.onReceiveValue(null);
            filePathCb = callback;
            Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
            pick.addCategory(Intent.CATEGORY_OPENABLE);
            pick.setType("image/*");
            Intent chooser = Intent.createChooser(pick, "عکس فیش / رسید");
            cameraUri = null;
            try {
                File dir = new File(getCacheDir(), "images");
                //noinspection ResultOfMethodCallIgnored
                dir.mkdirs();
                File f = File.createTempFile("cam", ".jpg", dir);
                cameraUri = FileProvider.getUriForFile(MainActivity.this, getPackageName() + ".fileprovider", f);
                Intent cam = new Intent(MediaStore.ACTION_IMAGE_CAPTURE).putExtra(MediaStore.EXTRA_OUTPUT, cameraUri);
                chooser.putExtra(Intent.EXTRA_INITIAL_INTENTS, new Intent[]{cam});
            } catch (IOException ignored) { }
            try {
                fileChooser.launch(chooser);
            } catch (ActivityNotFoundException e) {
                filePathCb = null;
                callback.onReceiveValue(null);
                return false;
            }
            return true;
        }

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
        public void startVoice() { runOnUiThread(MainActivity.this::startVoice); }

        @JavascriptInterface
        public void requestSmsPermission() { runOnUiThread(MainActivity.this::requestSms); }

        @JavascriptInterface
        public void openNotificationAccess() {
            runOnUiThread(MainActivity.this::showNotificationAccessGuide);
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
