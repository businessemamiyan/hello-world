// تست حالت سرور (Mini App): سرور واقعی FastAPI + اپ + پیامک + ربات
// اجرا: node ghotbnama/tests/e2e_server.js   (نیازمند python3 با fastapi/uvicorn/httpx)
const { chromium } = require('playwright');
const { spawn } = require('child_process');
const crypto = require('crypto');
const path = require('path');

const PORT = 8765, BASE = `http://127.0.0.1:${PORT}`, KEY = 'k'.repeat(20), SMS = 's'.repeat(20);
let fails = 0, passes = 0;
function ok(c, m) { if (c) { passes++; console.log('  ✔', m); } else { fails++; console.log('  ✘ FAIL:', m); } }
const sleep = ms => new Promise(r => setTimeout(r, ms));
const api = (p, opt = {}) => fetch(BASE + p, { ...opt, headers: { 'X-App-Key': KEY, 'Content-Type': 'application/json', ...(opt.headers || {}) } });
const state = async () => (await (await api('/api/state')).json()).state.real;

function initData(uid) {
  const f = { auth_date: String(Math.floor(Date.now() / 1000)), query_id: 'Q1', user: JSON.stringify({ id: uid, first_name: 'M' }) };
  const dcs = Object.keys(f).sort().map(k => `${k}=${f[k]}`).join('\n');
  const secret = crypto.createHmac('sha256', 'WebAppData').update('1:TESTTOKEN').digest();
  f.hash = crypto.createHmac('sha256', secret).update(dcs).digest('hex');
  return new URLSearchParams(f).toString();
}

(async () => {
  const srv = spawn('python3', [path.join(__dirname, '../server/tests/serve_for_e2e.py'), String(PORT)], { stdio: ['ignore', 'inherit', 'inherit'] });
  for (let i = 0; i < 50; i++) { try { if ((await fetch(BASE + '/health')).ok) break; } catch (e) {} await sleep(200); }
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const errors = [], external = [];
  try {
    let ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    let page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    page.on('request', r => { if (!r.url().startsWith(BASE)) external.push(r.url()); });

    console.log('\n# ورود با کلید و راه‌اندازی روی سرور');
    await page.goto(BASE + '/app?key=' + KEY); await sleep(800);
    ok(!page.url().includes('key='), 'کلید از آدرس پاک شد');
    ok(await page.isVisible('#wizard'), 'سرور خالی → ویزارد باز شد');
    await page.click('[data-act=wz-next]');
    await page.fill('#wz-target', '80000000');
    await page.click('[data-act=wz-ssug][data-n="حقوق"]');
    await page.fill('[data-chg=wz-s][data-i="0"][data-f=cur]', '30000000');
    for (let i = 0; i < 6; i++) await page.click('[data-act=wz-next]');
    await sleep(900);
    let R = await state();
    ok(R.streams.length === 1 && R.profile.target === 80000000, 'داده ویزارد روی سرور ذخیره شد');
    ok((await page.textContent('#modeChip')).includes('سرور'), 'نشانگر اتصال: «داده واقعی · سرور»');
    ok(external.length === 0, 'هیچ درخواستی به بیرون از سرور نرفت (فونت محلی): ' + external.join(','));

    console.log('\n# پیامک بانک → اپ');
    const sid = R.streams[0].id;
    let r = await fetch(BASE + '/sms/' + SMS, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ from: 'BankMelli', text: 'بانک ملی ایران\nواريز:+320,000,000\nحساب:0123456789001\nمانده:330,000,000\n07/07-08:01' }) });
    ok((await r.json()).status === 'ok', 'پیامک واریز پذیرفته شد');
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange'))); await sleep(600);
    await page.click('nav.bottom [data-tab=money]');
    let money = await page.textContent('section[data-pane=money]');
    ok(money.includes('۳۲٬۰۰۰٬۰۰۰') || money.includes('۳۲,۰۰۰,۰۰۰'), 'واریز ۳۲ میلیون تومانی (۳۲۰ میلیون ریال) در اپ دیده شد');
    ok(money.includes('ملی') && money.includes('پیامک'), 'بانک و منبع «پیامک» نمایش داده شد');
    ok(money.includes('۳۳٬۰۰۰٬۰۰۰'), 'آخرین مانده حساب از پیامک نمایش داده شد');
    await page.selectOption('select[data-chg=txn-class]', 's:' + sid); await sleep(700);
    R = await state();
    const mk = Object.keys(R.streams[0].entries).sort().pop();
    ok(R.streams[0].entries[mk] === 62000000, 'دسته «درآمد: حقوق» → درآمد حقوق این ماه ۳۰ + ۳۲ = ۶۲ میلیون (روی سرور)');
    ok(R.incomeLog.some(l => l.txnId === R.txns[0].id), 'ورودی درآمد به تراکنش گره خورد');

    console.log('\n# پیام تلگرام → اپ');
    await api('/__test/msg?text=' + encodeURIComponent('۲۵۰ ناهار'), { method: 'POST' });
    await page.click('nav.bottom [data-tab=home]');
    await page.evaluate(() => document.dispatchEvent(new Event('visibilitychange'))); await sleep(600);
    const home = await page.textContent('section[data-pane=home]');
    ok(home.includes('خالص نقدی ماه'), 'هزینه تلگرام روی خالص نقدی داشبورد اثر گذاشت');
    ok(home.includes('۶۲ میلیون'), 'درآمد ماه در داشبورد: ۶۲ میلیون');
    await page.click('nav.bottom [data-tab=money]');
    ok((await page.textContent('section[data-pane=money]')).includes('۲۵۰٬۰۰۰'), 'هزینه تلگرام در پنل پول: ۲۵۰ هزار');

    console.log('\n# تعارض: ربات و اپ همزمان');
    await page.click('nav.bottom [data-tab=money]');
    await api('/__test/msg?text=' + encodeURIComponent('۸۰ اسنپ'), { method: 'POST' });
    await page.fill('#tx-amt', '10000'); await page.click('form[data-form=txn-add] button'); await sleep(800);
    ok((await page.textContent('#toast')).includes('ربات در همین فاصله'), 'تعارض تشخیص داده شد و کاربر مطلع شد (بی‌صدا رونویسی نشد)');
    R = await state();
    ok(R.txns.some(t => t.note === 'اسنپ'), 'تغییر ربات حفظ شد');
    await page.click('[data-act=mfilter][data-v=all]');
    ok((await page.textContent('section[data-pane=money]')).includes('اسنپ'), 'اپ نسخه تازه را نشان می‌دهد');

    console.log('\n# ثبت اقدام از اپ و بستن روز از ربات');
    await page.click('nav.bottom [data-tab=today]');
    await page.fill('#na-title-0', 'تماس با مدیر تولید'); await page.click('form[data-form=action-add] button.primary'); await sleep(600);
    R = await state();
    const aid = Object.values(R.days)[0].actions[0].id;
    ok(!!aid, 'اقدام اپ روی سرور است');
    const sent = await (await fetch(BASE + '/__test/sent')).json();
    ok(sent.some(t => t.includes('۲۵۰٬۰۰۰')), 'ربات پیام تأیید هزینه را فرستاد');
    ok(sent.some(t => t.includes('💳 پیامک بانک')), 'ربات اعلان پیامک بانک را فرستاد');
    await ctx.close();

    console.log('\n# دسترسی');
    ctx = await browser.newContext(); page = await ctx.newPage();
    await page.goto(BASE + '/app'); await sleep(700);
    ok((await page.textContent('#banners')).includes('دسترسی به سرور رد شد'), 'بدون کلید: پیام دسترسی نمایش داده شد');
    await ctx.close();
    ctx = await browser.newContext(); page = await ctx.newPage();
    page.on('pageerror', e => errors.push(e.message));
    await page.goto(BASE + '/app#tgWebAppData=' + encodeURIComponent(initData(1001)) + '&tgWebAppVersion=7.0'); await sleep(800);
    ok((await page.textContent('#modeChip')).includes('سرور'), 'ورود از داخل تلگرام (initData) کار کرد');
    ok(!(await page.isVisible('#wizard')), 'راه‌اندازی قبلاً انجام شده؛ ویزارد باز نمی‌شود');
    await ctx.close();
    ctx = await browser.newContext(); page = await ctx.newPage();
    await page.goto(BASE + '/app#tgWebAppData=' + encodeURIComponent(initData(999)) + '&tgWebAppVersion=7.0'); await sleep(700);
    ok((await page.textContent('#banners')).includes('دسترسی به سرور رد شد'), 'کاربر دیگر تلگرام رد شد');
    await ctx.close();
  } finally {
    await browser.close(); srv.kill();
  }
  console.log(`\nنتیجه: ${passes} موفق، ${fails} ناموفق`);
  console.log('خطاهای صفحه:', errors.length ? errors : 'هیچ');
  process.exit(fails || errors.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
