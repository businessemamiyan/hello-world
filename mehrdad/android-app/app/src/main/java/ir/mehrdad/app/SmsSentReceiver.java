package ir.mehrdad.app;

import android.content.BroadcastReceiver;
import android.content.Context;
import android.content.Intent;

/** نتیجهٔ ارسال هر تکهٔ پیامک (از SmsManager). در مانیفست ثبت شده تا حتی بعد از مرگ پروسه هم برسد. */
public class SmsSentReceiver extends BroadcastReceiver {
    @Override
    public void onReceive(Context ctx, Intent i) {
        long id = i.getLongExtra("aid", -1);
        if (id < 0) return;
        PhoneActions.onSmsSent(ctx, id, i.getIntExtra("parts", 1), getResultCode());
    }
}
