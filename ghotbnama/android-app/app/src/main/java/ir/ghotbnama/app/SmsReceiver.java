package ir.ghotbnama.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;

/**
 * هر پیامک ورودی را می‌گیرد و مستقیم به سرور شخصی کاربر (/sms/&lt;token&gt;) می‌فرستد.
 * فقط وقتی کار می‌کند که در تنظیمات اپ، آدرس سرور و توکن پیامک وارد شده باشد
 * و کاربر مجوز «پیامک» را در تنظیمات اندروید داده باشد.
 */
public class SmsReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction())) return;
        if (!Prefs.isConfigured(context)) return;

        SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent);
        if (parts == null || parts.length == 0) return;

        String from = parts[0].getOriginatingAddress();
        StringBuilder body = new StringBuilder();
        for (SmsMessage m : parts) {
            if (m == null) continue;
            String b = m.getMessageBody();
            if (b != null) body.append(b);
        }
        if (body.length() == 0) return;
        SmsForwarder.send(context, from, body.toString());
    }
}
