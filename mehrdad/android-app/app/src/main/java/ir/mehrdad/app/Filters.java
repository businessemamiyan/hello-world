package ir.mehrdad.app;

import java.util.regex.Pattern;

/**
 * فیلتر روی خود گوشی — قبل از اینکه چیزی از گوشی خارج شود:
 *  - فقط پیام‌هایی که «مالی» به نظر می‌رسند ارسال می‌شوند (پیام‌های شخصی دیگران هرگز).
 *  - رمز یک‌بارمصرف/کد امنیتی هرگز ارسال نمی‌شود (سرور هم دوباره چک می‌کند).
 */
public class Filters {
    private static final Pattern OTP = Pattern.compile(
            "رمز\\s*(یک\\s*بار|دوم|پویا|عبور|ورود)|کد\\s*(تایید|تأیید|فعال\\s*ساز|ورود|امنیتی|یکبار)|otp|cvv2?|"
                    + "verification code|one[- ]time|password|پسورد",
            Pattern.CASE_INSENSITIVE);

    private static final Pattern MONEY_WORD = Pattern.compile(
            "ریال|تومان|مبلغ|برداشت|واریز|خرید|پرداخت|مانده|موجودی|انتقال|حواله|کسر|بستانکار|بدهکار|"
                    + "deposit|withdraw|purchase|balance",
            Pattern.CASE_INSENSITIVE);

    private static final Pattern HAS_DIGIT = Pattern.compile("[0-9۰-۹٠-٩]{3,}");

    public static boolean isSensitive(String text) {
        return text != null && OTP.matcher(text).find();
    }

    /** آیا این متن شبیه پیام مالی است و امن برای ارسال؟ */
    public static boolean shouldForward(String text) {
        if (text == null || text.length() < 8) return false;
        if (isSensitive(text)) return false;
        return MONEY_WORD.matcher(text).find() && HAS_DIGIT.matcher(text).find();
    }
}
