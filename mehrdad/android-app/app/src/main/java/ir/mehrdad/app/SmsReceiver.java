package ir.mehrdad.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;
import android.provider.Telephony;
import android.telephony.SmsMessage;

/** هر پیامک ورودی: اگر مالی بود (یا کاربر «همهٔ پیامک‌ها» را روشن کرده) و رمز یک‌بارمصرف نبود → صف ارسال به سرور شخصی. بقیه همان‌جا دور ریخته می‌شوند. */
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
        boolean ok = Prefs.smsAll(context) ? (text.trim().length() >= 2 && !Filters.isSensitive(text)) : Filters.shouldForward(text);
        if (!ok) return;
        Outbox.add(context, "sms", from, text);
    }
}
