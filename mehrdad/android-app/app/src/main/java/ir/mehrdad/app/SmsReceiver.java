package ir.mehrdad.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;

/** هر پیامک ورودی: اگر مالی بود و رمز یک‌بارمصرف نبود → صف ارسال به سرور شخصی. بقیه همان‌جا دور ریخته می‌شوند. */
public class SmsReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context context, Intent intent) {
        if (!Telephony.Sms.Intents.SMS_RECEIVED_ACTION.equals(intent.getAction())) return;
        if (!Prefs.isPaired(context)) return;

        SmsMessage[] parts = Telephony.Sms.Intents.getMessagesFromIntent(intent);
        if (parts == null || parts.length == 0) return;

        String from = parts[0].getOriginatingAddress();
        StringBuilder body = new StringBuilder();
        for (SmsMessage m : parts) {
            if (m == null) continue;
            String b = m.getMessageBody();
            if (b != null) body.append(b);
        }
        String text = body.toString();
        if (!Filters.shouldForward(text)) return;
        Outbox.add(context, "sms", from, text);
    }
}
