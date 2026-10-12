package ir.mehrdad.app;

import android.content.Context;
import android.graphics.Bitmap;
import android.graphics.BitmapFactory;
import android.net.Uri;
import android.util.Base64;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;

/** عکس Share‌شده → data URL کوچک‌شدهٔ JPEG (سریع آپلود شود و حافظه را پر نکند). */
final class ShareImage {
    private static final int MAX_SIDE = 1600;
    private static final int MAX_INPUT = 25 * 1024 * 1024;

    private ShareImage() { }

    static String toDataUrl(Context ctx, Uri uri) {
        try {
            BitmapFactory.Options o = new BitmapFactory.Options();
            o.inJustDecodeBounds = true;
            try (InputStream in = ctx.getContentResolver().openInputStream(uri)) {
                if (in == null) return null;
                BitmapFactory.decodeStream(in, null, o);
            }
            if (o.outWidth <= 0 || o.outHeight <= 0 || (long) o.outWidth * o.outHeight > 120_000_000L) return null;
            int sample = 1;
            while (Math.max(o.outWidth, o.outHeight) / sample > MAX_SIDE * 2) sample *= 2;
            BitmapFactory.Options d = new BitmapFactory.Options();
            d.inSampleSize = sample;
            Bitmap bmp;
            try (InputStream in = ctx.getContentResolver().openInputStream(uri)) {
                if (in == null) return null;
                bmp = BitmapFactory.decodeStream(in, null, d);
            }
            if (bmp == null) return null;
            float k = Math.min(1f, (float) MAX_SIDE / Math.max(bmp.getWidth(), bmp.getHeight()));
            if (k < 1f) {
                Bitmap small = Bitmap.createScaledBitmap(bmp, Math.max(1, Math.round(bmp.getWidth() * k)), Math.max(1, Math.round(bmp.getHeight() * k)), true);
                if (small != bmp) bmp.recycle();
                bmp = small;
            }
            ByteArrayOutputStream out = new ByteArrayOutputStream();
            bmp.compress(Bitmap.CompressFormat.JPEG, 82, out);
            bmp.recycle();
            if (out.size() > MAX_INPUT) return null;
            return "data:image/jpeg;base64," + Base64.encodeToString(out.toByteArray(), Base64.NO_WRAP);
        } catch (Exception | OutOfMemoryError e) {
            return null;
        }
    }
}
