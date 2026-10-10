package ir.mehrdad.app;

import android.Manifest;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.drawable.GradientDrawable;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.provider.Settings;
import android.speech.RecognizerIntent;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.PopupMenu;
import android.widget.ScrollView;
import android.widget.TextView;
import android.widget.Toast;

import androidx.activity.result.ActivityResultLauncher;
import androidx.activity.result.contract.ActivityResultContracts;
import androidx.appcompat.app.AlertDialog;
import androidx.appcompat.app.AppCompatActivity;
import androidx.core.app.NotificationManagerCompat;
import androidx.core.content.ContextCompat;

import org.json.JSONArray;
import org.json.JSONObject;

import java.util.ArrayList;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** چت مهرداد روی گوشی + ورودی صوتی + جفت‌سازی. حافظه و مغز همان سرور تلگرام است؛ اپ فقط یک دریچهٔ دیگر است. */
public class MainActivity extends AppCompatActivity {
    private static final int BG = Color.parseColor("#0B1220");
    private static final int TEXT = Color.parseColor("#E6EDF3");
    private static final int MUTED = Color.parseColor("#8B98A9");
    private static final int USER_BUBBLE = Color.parseColor("#1F4E4A");
    private static final int BOT_BUBBLE = Color.parseColor("#1A2433");

    private final ExecutorService io = Executors.newSingleThreadExecutor();
    private final Handler ui = new Handler(Looper.getMainLooper());

    private LinearLayout messages;
    private ScrollView scroll;
    private EditText input;
    private Button sendBtn;
    private TextView status;
    private boolean busy = false;

    private ActivityResultLauncher<Intent> speech;
    private ActivityResultLauncher<String> smsPermission;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        buildUi();

        speech = registerForActivityResult(new ActivityResultContracts.StartActivityForResult(), result -> {
            Intent data = result.getData();
            if (result.getResultCode() != RESULT_OK || data == null) return;
            ArrayList<String> r = data.getStringArrayListExtra(RecognizerIntent.EXTRA_RESULTS);
            if (r != null && !r.isEmpty()) {
                input.setText(r.get(0));
                input.setSelection(input.getText().length());
            }
        });
        smsPermission = registerForActivityResult(new ActivityResultContracts.RequestPermission(), granted -> {
            toast(granted ? "دریافت پیامک بانکی فعال شد" : "بدون مجوز پیامک، پیامک بانکی ثبت نمی‌شود");
            refreshStatus();
        });

        if (Prefs.isPaired(this)) {
            loadHistory();
            requestSmsIfNeeded();
        } else {
            showPairDialog();
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        refreshStatus();
        if (Prefs.isPaired(this)) Outbox.schedule(this);   // صف معوق را همین حالا دوباره امتحان کن
    }

    // ---------------------------------------------------------------- UI
    private void buildUi() {
        LinearLayout root = new LinearLayout(this);
        root.setOrientation(LinearLayout.VERTICAL);
        root.setBackgroundColor(BG);
        root.setFitsSystemWindows(true);
        root.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        LinearLayout top = new LinearLayout(this);
        top.setOrientation(LinearLayout.HORIZONTAL);
        top.setGravity(Gravity.CENTER_VERTICAL);
        top.setPadding(dp(16), dp(10), dp(8), dp(6));
        TextView title = new TextView(this);
        title.setText("مهرداد");
        title.setTextColor(TEXT);
        title.setTextSize(20);
        title.setTypeface(null, android.graphics.Typeface.BOLD);
        top.addView(title, new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f));
        Button menu = new Button(this);
        menu.setText("⋮");
        menu.setTextColor(TEXT);
        menu.setTextSize(20);
        menu.setBackgroundColor(Color.TRANSPARENT);
        menu.setOnClickListener(this::showMenu);
        top.addView(menu, new LinearLayout.LayoutParams(dp(48), dp(48)));
        root.addView(top);

        status = new TextView(this);
        status.setTextColor(MUTED);
        status.setTextSize(12);
        status.setPadding(dp(16), 0, dp(16), dp(6));
        root.addView(status);

        scroll = new ScrollView(this);
        messages = new LinearLayout(this);
        messages.setOrientation(LinearLayout.VERTICAL);
        messages.setPadding(dp(10), dp(4), dp(10), dp(8));
        scroll.addView(messages);
        root.addView(scroll, new LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, 0, 1f));

        LinearLayout bar = new LinearLayout(this);
        bar.setOrientation(LinearLayout.HORIZONTAL);
        bar.setGravity(Gravity.CENTER_VERTICAL);
        bar.setPadding(dp(8), dp(6), dp(8), dp(8));

        Button mic = new Button(this);
        mic.setText("🎤");
        mic.setOnClickListener(v -> startVoice());
        bar.addView(mic, new LinearLayout.LayoutParams(dp(56), dp(48)));

        input = new EditText(this);
        input.setHint("بنویس یا با 🎤 بگو…");
        input.setHintTextColor(MUTED);
        input.setTextColor(TEXT);
        input.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_MULTI_LINE);
        input.setMaxLines(4);
        LinearLayout.LayoutParams lpIn = new LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f);
        lpIn.setMargins(dp(6), 0, dp(6), 0);
        bar.addView(input, lpIn);

        sendBtn = new Button(this);
        sendBtn.setText("ارسال");
        sendBtn.setOnClickListener(v -> {
            String t = input.getText().toString().trim();
            if (!t.isEmpty()) sendMessage(t);
        });
        bar.addView(sendBtn, new LinearLayout.LayoutParams(dp(72), dp(48)));
        root.addView(bar);

        setContentView(root);
    }

    private TextView addBubble(String text, boolean mine) {
        TextView tv = new TextView(this);
        tv.setText(text);
        tv.setTextColor(TEXT);
        tv.setTextSize(16);
        tv.setTextIsSelectable(true);
        tv.setPadding(dp(12), dp(8), dp(12), dp(8));
        tv.setMaxWidth((int) (getResources().getDisplayMetrics().widthPixels * 0.82));
        GradientDrawable bg = new GradientDrawable();
        bg.setColor(mine ? USER_BUBBLE : BOT_BUBBLE);
        bg.setCornerRadius(dp(14));
        tv.setBackground(bg);
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT);
        lp.setMargins(0, dp(3), 0, dp(3));
        lp.gravity = mine ? Gravity.START : Gravity.END;
        messages.addView(tv, lp);
        scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
        return tv;
    }

    private void showMenu(View anchor) {
        PopupMenu m = new PopupMenu(this, anchor);
        m.getMenu().add(0, 1, 0, "اتصال / جفت‌سازی");
        m.getMenu().add(0, 2, 1, "دسترسی به اعلان‌ها");
        m.getMenu().add(0, 3, 2, "مجوز پیامک");
        m.getMenu().add(0, 4, 3, "دریافت دوباره‌ی تاریخچه");
        m.getMenu().add(0, 5, 4, "قطع اتصال این گوشی");
        m.setOnMenuItemClickListener(item -> {
            switch (item.getItemId()) {
                case 1: showPairDialog(); return true;
                case 2: startActivity(new Intent(Settings.ACTION_NOTIFICATION_LISTENER_SETTINGS)); return true;
                case 3: requestSmsIfNeeded(); return true;
                case 4: loadHistory(); return true;
                case 5:
                    Prefs.clearToken(this);
                    toast("قطع شد. برای وصل‌شدن دوباره /pair بزن.");
                    refreshStatus();
                    return true;
                default: return false;
            }
        });
        m.show();
    }

    private void refreshStatus() {
        boolean sms = ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS)
                == PackageManager.PERMISSION_GRANTED;
        boolean notif = NotificationManagerCompat.getEnabledListenerPackages(this).contains(getPackageName());
        String s = Prefs.isPaired(this) ? "متصل" : "وصل نیست";
        status.setText(s + " · پیامک " + (sms ? "✓" : "✗") + " · اعلان‌ها " + (notif ? "✓" : "✗")
                + " · در صف: " + Outbox.size(this));
    }

    // ---------------------------------------------------------------- جفت‌سازی
    private void showPairDialog() {
        LinearLayout box = new LinearLayout(this);
        box.setOrientation(LinearLayout.VERTICAL);
        box.setPadding(dp(20), dp(8), dp(20), 0);
        box.setLayoutDirection(View.LAYOUT_DIRECTION_RTL);

        TextView help = new TextView(this);
        help.setText("در تلگرام به مهرداد بنویس /pair تا یک کد ۸ حرفی بگیری. آدرس سرور را هم وارد کن (باید https باشد).");
        help.setTextSize(13);
        box.addView(help);

        EditText url = new EditText(this);
        url.setHint("https://mehrdad.example.com");
        url.setText(Prefs.serverUrl(this));
        url.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_VARIATION_URI);
        url.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        box.addView(url);

        EditText code = new EditText(this);
        code.setHint("کد جفت‌سازی");
        code.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_CAP_CHARACTERS
                | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS);
        code.setLayoutDirection(View.LAYOUT_DIRECTION_LTR);
        box.addView(code);

        new AlertDialog.Builder(this)
                .setTitle("اتصال به مهرداد")
                .setView(box)
                .setCancelable(Prefs.isPaired(this))
                .setPositiveButton("اتصال", (d, w) ->
                        pair(url.getText().toString().trim(), code.getText().toString().trim()))
                .setNegativeButton("بعداً", null)
                .show();
    }

    private void pair(String rawUrl, String code) {
        String base = rawUrl;
        while (base.endsWith("/")) base = base.substring(0, base.length() - 1);
        if (!base.startsWith("https://")) { toast("آدرس باید با https:// شروع شود"); return; }
        if (code.isEmpty()) { toast("کد را وارد کن"); return; }
        final String baseUrl = base;
        toast("در حال اتصال…");
        io.submit(() -> {
            Api.Result r;
            try {
                JSONObject body = new JSONObject().put("code", code)
                        .put("name", (Build.MANUFACTURER + " " + Build.MODEL).trim());
                r = Api.call(this, baseUrl, "POST", "/api/pair", body, false, 20000);
            } catch (Exception e) {
                r = new Api.Result(0, String.valueOf(e.getMessage()));
            }
            final Api.Result res = r;
            ui.post(() -> {
                if (res.ok() && !res.json().optString("token").isEmpty()) {
                    Prefs.savePairing(this, baseUrl, res.json().optString("token"));
                    toast("وصل شد ✓");
                    loadHistory();
                    requestSmsIfNeeded();
                    Outbox.schedule(this);
                } else if (res.code == 403) {
                    toast("کد اشتباه است یا منقضی شده. دوباره /pair بزن.");
                } else if (res.code == 429) {
                    toast("تلاش ناموفق زیاد بود؛ ۱۰ دقیقه بعد دوباره.");
                } else {
                    toast("به سرور نرسیدم (" + res.code + "). آدرس و اینترنت/فیلترشکن را چک کن.");
                }
                refreshStatus();
            });
        });
    }

    // ---------------------------------------------------------------- چت
    private void loadHistory() {
        if (!Prefs.isPaired(this)) return;
        io.submit(() -> {
            Api.Result r = Api.call(this, "GET", "/api/history?limit=60", null, 20000);
            ui.post(() -> {
                if (r.code == 401) { onUnauthorized(); return; }
                if (!r.ok()) return;
                JSONArray arr = r.json().optJSONArray("messages");
                if (arr == null) return;
                messages.removeAllViews();
                for (int i = 0; i < arr.length(); i++) {
                    JSONObject m = arr.optJSONObject(i);
                    if (m != null) addBubble(m.optString("text"), "user".equals(m.optString("role")));
                }
            });
        });
    }

    private void sendMessage(String text) {
        if (!Prefs.isPaired(this)) { showPairDialog(); return; }
        if (busy) return;
        addBubble(text, true);
        input.setText("");
        final TextView typing = addBubble("…", false);
        setBusy(true);
        io.submit(() -> {
            Api.Result r;
            try {
                r = Api.call(this, "POST", "/api/chat", new JSONObject().put("text", text), 150000);
            } catch (Exception e) {
                r = new Api.Result(0, String.valueOf(e.getMessage()));
            }
            final Api.Result res = r;
            ui.post(() -> {
                setBusy(false);
                if (res.code == 401) { messages.removeView(typing); onUnauthorized(); return; }
                if (res.ok()) {
                    typing.setText(res.json().optString("reply", "…"));
                } else {
                    typing.setText("نتوانستم به سرور برسم (" + res.code + "). دوباره امتحان کن.");
                }
                scroll.post(() -> scroll.fullScroll(View.FOCUS_DOWN));
            });
        });
    }

    private void setBusy(boolean b) {
        busy = b;
        sendBtn.setEnabled(!b);
    }

    private void onUnauthorized() {
        Prefs.clearToken(this);
        toast("این گوشی دیگر وصل نیست. با /pair دوباره وصلش کن.");
        refreshStatus();
        showPairDialog();
    }

    // ---------------------------------------------------------------- صدا و مجوزها
    private void startVoice() {
        Intent i = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        i.putExtra(RecognizerIntent.EXTRA_LANGUAGE, "fa-IR");
        i.putExtra(RecognizerIntent.EXTRA_PROMPT, "بگو…");
        try {
            speech.launch(i);
        } catch (ActivityNotFoundException e) {
            toast("تشخیص گفتار در این گوشی نیست (برنامهٔ Google لازم است؛ شاید فیلترشکن هم).");
        }
    }

    private void requestSmsIfNeeded() {
        if (ContextCompat.checkSelfPermission(this, Manifest.permission.RECEIVE_SMS)
                != PackageManager.PERMISSION_GRANTED) {
            smsPermission.launch(Manifest.permission.RECEIVE_SMS);
        }
    }

    private void toast(String s) {
        Toast.makeText(this, s, Toast.LENGTH_LONG).show();
    }

    private int dp(int v) {
        return (int) (v * getResources().getDisplayMetrics().density);
    }
}
