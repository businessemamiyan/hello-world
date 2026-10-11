package ir.mehrdad.app;

import android.app.PendingIntent;
import android.content.Intent;
import android.os.Build;
import android.service.quicksettings.Tile;
import android.service.quicksettings.TileService;

/** کاشی تنظیمات سریع (از بالای صفحه بکش پایین): یک لمس = مهرداد گوش می‌دهد. */
public class MehrdadTile extends TileService {
    @Override
    public void onStartListening() {
        Tile t = getQsTile();
        if (t != null) {
            t.setState(Tile.STATE_INACTIVE);
            t.setLabel("مهرداد 🎤");
            t.updateTile();
        }
    }

    @Override
    public void onClick() {
        Intent i = new Intent(this, MainActivity.class).putExtra("voice", true).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        if (Build.VERSION.SDK_INT >= 34) {
            startActivityAndCollapse(PendingIntent.getActivity(this, 7, i, PendingIntent.FLAG_IMMUTABLE | PendingIntent.FLAG_UPDATE_CURRENT));
        } else {
            startActivityAndCollapse(i);
        }
    }
}
