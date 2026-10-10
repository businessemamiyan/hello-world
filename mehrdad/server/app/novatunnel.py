"""اتصال فقط‌خواندنی به دیتابیس NovaTunnel (Supabase) برای خلاصهٔ فروش و هزینه.

فقط view‌های schema `mehrad` را می‌خواند (novatunnel-readonly.sql)، داخل تراکنش read-only و با timeout کوتاه.
هیچ داده‌ای از NovaTunnel دست‌کاری نمی‌شود و اطلاعات شخصی مشتری اصلاً در دسترس این کاربر نیست.
"""
import asyncio
import datetime
import logging
import time

from . import life

log = logging.getLogger("novatunnel")
_CACHE = {"ts": 0.0, "dsn": None, "data": None}
CACHE_SECONDS = 60


async def _connect(dsn):
    import asyncpg   # فقط وقتی تنظیم شده باشد لازم است
    return await asyncio.wait_for(asyncpg.connect(dsn, timeout=8, statement_cache_size=0), 12)


async def _collect(conn, now):
    """conn: هر شیئی با fetchrow/fetch (asyncpg) — برای تست قابل‌جایگزینی."""
    ts, te = life.range_bounds("today", now)
    ms, me = life.range_bounds("month", now)
    dt = lambda x: datetime.datetime.fromtimestamp(x, datetime.timezone.utc)
    rev = lambda a, b: conn.fetchrow(
        "select coalesce(sum(price_toman),0)::float8 as total, count(*)::int as n from mehrad.sales "
        "where payment_status = 'confirmed' and confirmed_at >= $1 and confirmed_at < $2", dt(a), dt(b))
    exp = lambda a, b: conn.fetchrow(
        "select coalesce(sum(amount_toman),0)::float8 as total, count(*)::int as n from mehrad.expenses "
        "where created_at >= $1 and created_at < $2", dt(a), dt(b))
    today, month = await rev(ts, te), await rev(ms, me)
    e_today, e_month = await exp(ts, te), await exp(ms, me)
    pending = await conn.fetchrow(
        "select count(*)::int as n, coalesce(sum(price_toman),0)::float8 as total from mehrad.sales where payment_status = 'pending'")
    topups = await conn.fetchrow(
        "select count(*)::int as n, coalesce(sum(amount_toman),0)::float8 as total from mehrad.topups where status = 'pending'")
    users = await conn.fetchrow("select total_users, new_24h, new_30d from mehrad.user_counts")
    series = await conn.fetch(
        "select (confirmed_at at time zone 'Asia/Tehran')::date as d, sum(price_toman)::float8 as total, count(*)::int as n "
        "from mehrad.sales where payment_status = 'confirmed' and confirmed_at >= $1 group by 1 order by 1", dt(ts - 6 * 86400))
    return {
        "configured": True,
        "revenue": {"today": today["total"], "today_count": today["n"], "month": month["total"], "month_count": month["n"]},
        "expenses": {"today": e_today["total"], "month": e_month["total"]},
        "net_month": month["total"] - e_month["total"],
        "pending_sales": {"count": pending["n"], "total": pending["total"]},
        "pending_topups": {"count": topups["n"], "total": topups["total"]},
        "users": {"total": users["total_users"], "new_24h": users["new_24h"], "new_30d": users["new_30d"]},
        "last7": [{"date": str(r["d"]), "total": r["total"], "count": r["n"]} for r in series],
    }


async def snapshot(dsn, now=None, connect=_connect, use_cache=True):
    """خلاصهٔ NovaTunnel یا {"configured": False} / {"configured": True, "error": ...}."""
    if not dsn:
        return {"configured": False}
    if use_cache and _CACHE["dsn"] == dsn and time.time() - _CACHE["ts"] < CACHE_SECONDS and _CACHE["data"]:
        return _CACHE["data"]
    now = now or life.now_tehran()
    try:
        conn = await connect(dsn)
        try:
            async with conn.transaction(readonly=True):
                data = await _collect(conn, now)
        finally:
            await conn.close()
    except Exception as e:                      # اتصال/دسترسی ناموفق نباید چیز دیگری را خراب کند
        log.warning("novatunnel snapshot failed: %s", type(e).__name__)
        return {"configured": True, "error": f"{type(e).__name__}: {str(e)[:120]}"}
    _CACHE.update(ts=time.time(), dsn=dsn, data=data)
    return data


def format_text(d):
    if not d.get("configured"):
        return "اتصال NovaTunnel هنوز تنظیم نشده‌ست."
    if d.get("error"):
        return "NovaTunnel در دسترس نیست: " + d["error"]
    m = lambda n: life.fa(f"{int(round(n)):,}")
    r, e = d["revenue"], d["expenses"]
    lines = ["🛰 NovaTunnel",
             f"فروش امروز {m(r['today'])} ({life.fa(r['today_count'])} خرید) | این ماه {m(r['month'])} ({life.fa(r['month_count'])} خرید)",
             f"هزینهٔ ثبت‌شده: امروز {m(e['today'])} | ماه {m(e['month'])} → خالص ماه {m(d['net_month'])} تومان",
             f"منتظر تأیید: {life.fa(d['pending_sales']['count'])} خرید ({m(d['pending_sales']['total'])}) | {life.fa(d['pending_topups']['count'])} شارژ کیف پول ({m(d['pending_topups']['total'])})",
             f"کاربران: {life.fa(d['users']['total'])} (۲۴ ساعت: +{life.fa(d['users']['new_24h'])}، ۳۰ روز: +{life.fa(d['users']['new_30d'])})"]
    return "\n".join(lines)
