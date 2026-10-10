-- کاربر «فقط‌خواندنی» برای مهراد روی دیتابیس NovaTunnel (Supabase).
-- اجرا: Supabase ← SQL Editor ← این را paste و Run کن. یک‌بار. قبل از اجرا PASSWORD_HERE را با یک رمز قوی و تصادفی عوض کن.
--
-- اصول:
--  * فقط SELECT روی چند «view» خلاصه؛ هیچ INSERT/UPDATE/DELETE و هیچ دسترسی به جدول‌های اصلی.
--  * view‌ها در schema جدای `mehrad` هستند، نه `public`: schema public از طریق API عمومی Supabase (کلید anon)
--    قابل خواندن است، پس هر چیزی آنجا بسازیم لو می‌رود. schema `mehrad` به API داده نمی‌شود.
--  * اطلاعات شخصی مشتری (موبایل، آیدی تلگرام، نام) در هیچ view نیست.
--  * هر وقت خواستی قطعش می‌کنی:  drop schema mehrad cascade;  drop role mehrad_ro;

create schema if not exists mehrad;
revoke all on schema mehrad from public, anon, authenticated;

create or replace view mehrad.sales as
  select id, price_toman, volume_gb, payment_method::text as payment_method, payment_status::text as payment_status,
         seller_type::text as seller_type, purchased_at, confirmed_at
  from public.purchases;

create or replace view mehrad.topups as
  select id, amount_toman, status, created_at, confirmed_at from public.wallet_topup_requests;

create or replace view mehrad.expenses as
  select id, amount_toman, description, category, created_at from public.expenses;

create or replace view mehrad.user_counts as
  select count(*)::int as total_users,
         count(*) filter (where created_at >= now() - interval '1 day')::int as new_24h,
         count(*) filter (where created_at >= now() - interval '30 days')::int as new_30d
  from public.users;

revoke all on all tables in schema mehrad from public, anon, authenticated;

create role mehrad_ro login password 'PASSWORD_HERE' nosuperuser nocreatedb nocreaterole noinherit;
grant usage on schema mehrad to mehrad_ro;
grant select on all tables in schema mehrad to mehrad_ro;       -- «tables» شامل view‌ها هم می‌شود

-- بررسی (باید permission denied بدهد):
--   set role mehrad_ro; select * from public.users limit 1;
-- و این باید کار کند:
--   set role mehrad_ro; select * from mehrad.user_counts;
