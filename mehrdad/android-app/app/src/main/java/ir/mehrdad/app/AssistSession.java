package ir.mehrdad.app;

import android.content.Context;
import android.content.Intent;
import android.os.Bundle;
import android.service.voice.VoiceInteractionSession;

/** وقتی کاربر دستیار را صدا می‌زند: اپ را با حالت «گوش بده» باز کن و جلسه را ببند. */
public class AssistSession extends VoiceInteractionSession {
    public AssistSession(Context context) {
        super(context);
    }

    @Override
    public void onShow(Bundle args, int showFlags) {
        super.onShow(args, showFlags);
        Intent i = new Intent(getContext(), MainActivity.class).putExtra("voice", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        startAssistantActivity(i);
        finish();
    }
}
