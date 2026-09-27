const { chromium } = require('playwright');
const URL = 'file://' + require('path').resolve(__dirname, '../index.html');
const OUT = process.argv[2] || require('os').tmpdir();
let fails = 0, passes = 0;
function ok(cond, msg) { if (cond) { passes++; console.log('  ✔', msg); } else { fails++; console.log('  ✘ FAIL:', msg); } }

// شبیه‌سازی window.claude برای تست db و AI
const FAKE_CLAUDE = `
window.__db = {};
window.__aiCalls = [];
window.claude = { use: async (name) => {
  await new Promise(r=>setTimeout(r,50));
  if (name === 'db') return { doc: (p) => ({
    get: async () => ({ exists: !!window.__db[p], data: () => window.__db[p] }),
    set: async (d) => { window.__db[p] = JSON.parse(JSON.stringify(d)); }
  })};
  if (name === 'sample') {
    const f = async (input, opts) => { window.__aiCalls.push(input); const t = 'تحلیل آزمایشی: مشکل اصلی تمرکز است.'; opts && opts.onText && opts.onText({text:t, delta:t}); return {text:t, truncated:false}; };
    f.json = async (input) => { window.__aiCalls.push(input); const m = String(input).match(/idهای پروژه فعال: (p_[a-z0-9]+)/); return { actions: [
      {cat:'income', title:'تماس با ۳ مدیر کارخانه', projectId: m ? m[1] : '', goalId:'', estMin:60, expected:'۱ جلسه'},
      {cat:'future', title:'ماژول گزارش VQ', projectId:'bogus', goalId:'', estMin:90, expected:'نسخه اول'},
      {cat:'growth', title:'مطالعه مذاکره', projectId:'', goalId:'', estMin:30, expected:'یادداشت'}], note:'تست' }; };
    return f;
  }
  return null;
}};`;

(async () => {
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  const errors = [];
  const newPage = async (ctx) => { const p = await ctx.newPage(); p.on('pageerror', e => errors.push(e.message)); p.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); }); return p; };

  // ---------- ۱. اجرای اول: ویزارد ----------
  console.log('\n# اجرای اول و ویزارد');
  let ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  let page = await newPage(ctx);
  await page.goto(URL); await page.waitForTimeout(400);
  ok(await page.isVisible('#wizard'), 'ویزارد در اولین اجرا باز می‌شود');
  const sub = await page.textContent('#topSub');
  const expDay = await page.evaluate(() => new Intl.DateTimeFormat('fa-IR-u-ca-persian', { day: 'numeric', month: 'long' }).format(new Date()));
  ok(sub.includes(expDay.split(' ')[0]) && sub.includes('مهر'), 'تاریخ شمسی درست است: ' + sub + ' (انتظار: ' + expDay + ')');
  ok(sub.includes('یکشنبه'), 'روز هفته درست است (یکشنبه)');
  // مرحله ۱
  await page.fill('#wz-name', 'مهرداد');
  await page.click('[data-act=wz-next]');
  // مرحله ۲
  ok((await page.textContent('#wizard h1')).includes('درآمد واقعی'), 'مرحله ۲: درآمد واقعی');
  await page.fill('#wz-target', '80000000'); await page.fill('#wz-tend', '1406/12');
  await page.click('[data-act=wz-ssug][data-n="حقوق"]');
  ok(await page.inputValue('#wz-target') === '80000000', 'مقدار هدف بعد از افزودن منبع حفظ شد');
  await page.fill('[data-chg=wz-s][data-i="0"][data-f=cur]', '32000000');
  await page.fill('[data-chg=wz-s][data-i="0"][data-f=prev]', '30000000');
  await page.click('[data-act=wz-ssug][data-n="VQ / Vista Quantum"]');
  ok(await page.inputValue('[data-chg=wz-s][data-i="0"][data-f=cur]') === '32000000', 'مبلغ منبع اول بعد از افزودن منبع دوم حفظ شد');
  await page.fill('[data-chg=wz-s][data-i="1"][data-f=target]', '20000000');
  await page.click('[data-act=wz-next]');
  // مرحله ۳
  await page.fill('#wz-vision', 'VQ محصول فروخته‌شده در چند کارخانه');
  await page.click('[data-act=wz-gtpl][data-i="0"]');
  await page.fill('#wz-gn', '1'); await page.fill('#wz-ge', '1405/10/30');
  await page.click('form[data-form=wz-gadd] button');
  await page.fill('#wz-gt', 'هدف بدون عدد'); await page.click('form[data-form=wz-gadd] button');
  const wzGoals = await page.$$eval('#wizard .wz-row .pill', els => els.map(e => e.textContent));
  ok(wzGoals.includes('کامل') && wzGoals.includes('ناقص'), 'هدف کامل و ناقص درست تشخیص داده شد');
  await page.click('[data-act=wz-next]');
  // مرحله ۴
  const projRows = await page.$$('#wizard .wz-row');
  ok(projRows.length === 5, '۵ پروژه اولیه ساخته شد');
  await page.fill('[data-chg=wz-p][data-i="0"][data-f=nextAction]', 'دمو برای مدیر تولید');
  await page.fill('[data-chg=wz-p][data-i="0"][data-f=weeklyHours]', '8');
  await page.click('[data-act=wz-next]');
  // مرحله ۵
  await page.fill('#wz-free', '12');
  await page.click('[data-act=wz-next]');
  // مرحله ۶
  await page.selectOption('#wz-mp', { label: 'VQ / Vista Quantum' });
  await page.fill('#wz-pri', 'اولین مشتری VQ');
  await page.click('[data-act=wz-next]');
  // مرحله ۷
  const sum = await page.textContent('#wizard');
  ok(sum.includes('۲ / ۲'), 'خلاصه: پروژه فعال / ظرفیت = ۲/۲ (۱۲ ساعت ÷ ۶)');
  await page.click('[data-act=wz-next]');
  ok(!(await page.isVisible('#wizard')), 'ویزارد بسته شد و برنامه شروع شد');
  ok(await page.isVisible('section[data-pane=today]'), 'بعد از راه‌اندازی به «امروز» می‌رود');

  // ---------- ۲. امروز ----------
  console.log('\n# برنامه روزانه');
  ok(await page.isVisible('.sugs button[data-act=sug]'), 'پیشنهاد اقدام از «اقدام بعدی» پروژه نمایش داده شد');
  await page.click('.sugs button[data-act=sug]');
  ok(await page.inputValue('#na-title-0') === 'دمو برای مدیر تولید', 'پیشنهاد فرم را پر کرد');
  await page.fill('#na-est-0', '90');
  await page.click('form[data-form=action-add] button.primary');
  await page.fill('#na-title-1', 'کار بی‌ربط'); await page.click('form[data-form=action-add] button.primary');
  ok((await page.textContent('#toast')).includes('وصل نیست'), 'هشدار اقدام وصل‌نشده');
  await page.fill('#na-title-2', 'مطالعه'); await page.click('form[data-form=action-add] button.primary');
  ok(!(await page.$('form[data-form=action-add]')), 'بعد از ۳ اقدام، فرم افزودن حذف می‌شود (سقف ۳)');
  // ثبت نتیجه
  const resBtns = await page.$$('[data-act=res-open]');
  await resBtns[0].click();
  await page.click('[data-act=res-st][data-v=done]');
  await page.fill('input[id^=rr-]', 'تاریخ پایلوت گرفته شد'); await page.fill('input[id^=rm-]', '80');
  await page.click('form[data-form=result] button.primary');
  await (await page.$$('[data-act=res-open]'))[1].click();
  await page.click('[data-act=res-st][data-v=skipped]');
  await page.click('form[data-form=result] button.primary');
  ok((await page.textContent('#toast')).includes('دلیل'), 'انجام‌نشده بدون دلیل پذیرفته نمی‌شود');
  await page.fill('input[id^=rw-]', 'وقت نشد'); await page.click('form[data-form=result] button.primary');
  ok(await page.isDisabled('[data-act=day-close]'), 'با یک اقدام بدون نتیجه، بستن روز غیرفعال است');
  await (await page.$$('[data-act=res-open]'))[2].click();
  await page.click('[data-act=res-st][data-v=partial]'); await page.fill('input[id^=rw-]', 'نصف شد'); await page.fill('input[id^=rm-]', '30');
  await page.click('form[data-form=result] button.primary');
  await page.click('[data-act=day-close]');
  const closeToast = await page.textContent('#toast');
  ok(closeToast.includes('امتیاز'), 'بستن روز امتیاز می‌دهد: ' + closeToast);
  // امتیاز مورد انتظار: اجرا (1+0.5)/3*25=12.5، نتیجه: درآمد0 + نتیجه ثبت‌شده (۱ از ۲ انجام‌شده/نیمه)=7.5، تمرکز ۱/۳*20=6.67، نظم 10+5+5=20 => 46.67 → 47
  ok(closeToast.includes('۴۷'), 'امتیاز روز طبق فرمول = ۴۷');
  // ثبت درآمد
  await page.selectOption('#tqS', { label: 'VQ / Vista Quantum' });
  await page.fill('#tqA', '5000000'); await page.click('form[data-form=income-quick] button');
  ok((await page.textContent('#toast')).includes('ثبت شد'), 'درآمد امروز ثبت شد');
  const scorePill = await page.textContent('section[data-pane=today] .card .pill.num');
  ok(scorePill.includes('۶۷'), 'بعد از ثبت درآمد، امتیاز روز ۲۰ امتیاز بالا رفت: ' + scorePill);

  // ---------- ۳. خانه ----------
  console.log('\n# داشبورد');
  await page.click('nav.bottom [data-tab=home]');
  const home = await page.textContent('section[data-pane=home]');
  ok(home.includes('۳۷ میلیون'), 'درآمد این ماه = ۳۲ + ۵ = ۳۷ میلیون');
  ok(home.includes('۴۶٪'), 'درصد تحقق ۳۷/۸۰ = ۴۶٪');
  ok(home.includes('۴۳ میلیون'), 'فاصله تا هدف = ۴۳ میلیون');
  ok(home.includes('الان کجا هستم؟') && home.includes('مشکل اصلی') && home.includes('امروز چه کنم؟'), 'سه سؤال اصلی نمایش داده می‌شود');
  ok(home.includes('واقعیت امروز من'), 'کارت «واقعیت امروز من» وجود دارد');
  ok(await page.$('#homeChart svg') !== null, 'نمودار ۶ ماهه رسم شد');
  await page.screenshot({ path: OUT + '/v2-home.png', fullPage: true });

  // ---------- ۴. اهداف ----------
  console.log('\n# اهداف');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=goals]');
  ok((await page.$$('section[data-pane=goals] .item')).length === 2, 'دو هدف از ویزارد');
  await page.fill('#gf-title', 'هدف تست بدون تاریخ'); await page.fill('#gf-target', '10');
  await page.selectOption('#gf-status', 'active');
  await page.click('form[data-form=goal] button.primary');
  ok((await page.textContent('#toast')).includes('پیش‌نویس'), 'هدف بدون تاریخ پایان فعال نمی‌شود');
  const draftSel = await page.$$('select[data-chg=goal-status]');
  // هدف ناقص را فعال کن → باید رد شود
  for (const s of draftSel) { if (await s.inputValue() === 'draft') { await s.selectOption('active'); break; } }
  ok((await page.textContent('#toast')).includes('فعال نمی‌شود'), 'فعال کردن هدف ناقص رد شد');
  await page.fill('#gf-start', '1405/99/01'); await page.fill('#gf-title', 'x'); await page.click('form[data-form=goal] button.primary');
  ok((await page.textContent('#toast')).includes('معتبر نیست'), 'تاریخ نامعتبر رد شد');
  // به‌روزرسانی مقدار هدف کامل
  const curInp = await page.$('input[data-chg=goal-cur]');
  await curInp.fill('1'); await curInp.dispatchEvent('change');
  const gtext = await page.textContent('section[data-pane=goals]');
  ok(gtext.includes('به عدد هدف رسید'), 'هدف ۱ از ۱ → «به عدد هدف رسید»');

  // ---------- ۵. پروژه‌ها ----------
  console.log('\n# پروژه‌ها و اولویت‌بندی');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=projects]');
  const selects = await page.$$('select[data-chg=proj-status]');
  for (const s of selects) { if (await s.inputValue() === 'backlog') { await s.selectOption('active'); break; } }
  ok((await page.textContent('#toast')).includes('ظرفیت'), 'فعال کردن پروژه سوم با ظرفیت ۲ هشدار داد');
  const ptext = await page.textContent('section[data-pane=projects]');
  ok(ptext.includes('۳ پروژه فعال دارید'), 'Focus Guard: «شما ۳ پروژه فعال دارید»');
  // امتیازدهی: پروژه «درآمد و فروش» را ارزش بالا کن
  const editBtns = await page.$$('[data-act=proj-edit]');
  let target = null;
  for (const b of editBtns) { const card = await b.evaluateHandle(el => el.closest('.item')); const t = await card.evaluate(el => el.querySelector('.ttl').textContent); if (t.includes('درآمد و فروش')) { target = b; break; } }
  await target.click();
  for (const k of ['inc', 'goal', 'imp', 'prob']) await page.$eval('#pf-sc-' + k, el => { el.value = '5'; });
  await page.$eval('#pf-sc-urg', el => { el.value = '1'; });
  await page.fill('#pf-pot', '30000000'); await page.fill('#pf-next', 'پیام به ۵ مدیر');
  await page.click('form[data-form=project] button.primary');
  const firstRow = await page.textContent('section[data-pane=projects] table tbody tr');
  ok(firstRow.includes('درآمد و فروش') && firstRow.includes('۹۰'), 'رتبه ۱ = «درآمد و فروش» با ارزش ۹۰ (فوریت ۱): ' + firstRow.replace(/\s+/g, ' '));
  // فوریت بالا به‌تنهایی رتبه نمی‌دهد
  await (await page.$$('[data-act=proj-edit]'))[0].click();
  const nm = await page.inputValue('#pf-name');
  for (const k of ['inc', 'goal', 'imp', 'prob']) await page.$eval('#pf-sc-' + k, el => { el.value = '1'; });
  await page.$eval('#pf-sc-urg', el => { el.value = '5'; });
  await page.click('form[data-form=project] button.primary');
  const rows = await page.$$eval('section[data-pane=projects] table tbody tr', trs => trs.map(t => t.textContent));
  const urgentRow = rows.find(r => r.includes(nm));
  ok(urgentRow && urgentRow.includes('۱۰') && rows.indexOf(urgentRow) === rows.length - 1, 'پروژه فقط-فوری ارزش ۱۰ و رتبه آخر گرفت');
  // افزودن اقدام بعدی پروژه به امروز: امروز ۳ اقدام دارد → دکمه نباید باشد
  ok(!(await page.$('[data-act=proj-to-today]')), 'وقتی امروز ۳ اقدام دارد، «افزودن به امروز» نمایش داده نمی‌شود');

  // ---------- ۶. درآمد ----------
  console.log('\n# درآمد');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=income]');
  const itext = await page.textContent('section[data-pane=income]');
  ok(itext.includes('+۲۳٪'), 'رشد نسبت به ماه قبل: ۳۷ در برابر ۳۰ = +۲۳٪');
  ok(itext.includes('۱۴٪') , 'سهم VQ از کل: ۵/۳۷ = ۱۴٪');
  const cell = await page.$('input[data-chg=cell][data-id]:last-of-type');
  ok(!!cell, 'جدول درآمد قابل ویرایش است');

  // ---------- ۷. بازبینی ----------
  console.log('\n# بازبینی هفتگی');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=review]');
  await page.click('[data-act=revweek]:has-text("این هفته")');
  const rtext = await page.textContent('section[data-pane=review]');
  ok(rtext.includes('۵ میلیون'), 'درآمد هفته = ۵ میلیون (از ثبت سریع)');
  ok(rtext.includes('۵۰٪'), 'درصد اجرا = ۱.۵ از ۳ = ۵۰٪');
  await page.click('form[data-form=review] button');
  ok((await page.textContent('#toast')).includes('حداقل'), 'بازبینی خالی پذیرفته نمی‌شود');
  await page.fill('#rv-best', 'تاریخ پایلوت'); await page.fill('#rv-focus', 'بستن قرارداد پایلوت');
  await page.click('form[data-form=review] button');
  ok((await page.$$('section[data-pane=review] .item')).length === 1, 'بازبینی با عددهای خودکار ثبت شد');

  // ---------- ۸. واقعیت و فرمان و مربی ----------
  console.log('\n# واقعیت بدون تعارف، مرکز فرمان، مربی');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=reality]');
  ok((await page.$$('section[data-pane=reality] .cmd')).length === 8, '۸ سؤال واقعیت نمایش داده شد');
  const real = await page.textContent('section[data-pane=reality]');
  ok(real.includes('۳ پروژه فعال') && real.includes('ظرفیت محاسبه‌شده ۲'), 'سؤال ظرفیت با عدد واقعی جواب داده شد');
  await page.click('nav.bottom [data-tab=command]');
  const cmd = await page.textContent('section[data-pane=command]');
  ok(cmd.includes('بزرگ‌ترین ریسک') && cmd.includes('فرصت') && cmd.includes('Focus Guard'), 'مرکز فرمان کامل رندر شد');
  ok(cmd.includes('درآمد و فروش'), 'فرصت = پروژه با بیشترین درآمد مورد انتظار');
  await page.click('nav.bottom [data-tab=coach]');
  ok((await page.textContent('section[data-pane=coach]')).includes('فقط وقتی این اپ داخل Claude'), 'بدون Claude، مربی پیام درست نشان می‌دهد');
  ok(await page.isDisabled('[data-act=coach-preset]'), 'دکمه‌های مربی بدون Claude غیرفعال‌اند');

  // ---------- ۹. داده نمونه جدا از واقعی ----------
  console.log('\n# جداسازی Sample Data');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=settings]');
  await page.click('[data-act=mode][data-v=demo]');
  ok((await page.textContent('#banners')).includes('Sample Data'), 'بنر Sample Data نمایش داده شد');
  await page.click('nav.bottom [data-tab=home]');
  const demoHome = await page.textContent('section[data-pane=home]');
  ok(demoHome.includes('۸۰ میلیون'), 'در حالت نمونه، داده نمونه نمایش داده می‌شود');
  await page.screenshot({ path: OUT + '/v2-demo-home.png', fullPage: true });
  await page.click('nav.bottom [data-tab=today]');
  await page.screenshot({ path: OUT + '/v2-demo-today.png', fullPage: true });
  await page.click('nav.bottom [data-tab=command]');
  await page.screenshot({ path: OUT + '/v2-demo-command.png', fullPage: true });
  const stored = await page.evaluate(() => localStorage.getItem('ghotbnama.v2'));
  ok(!stored.includes('مشاوره سیستم (فریلنس)'), 'داده نمونه در ذخیره‌سازی واقعی نوشته نشد');
  await page.click('[data-act=to-real]');
  const realHome = await page.textContent('section[data-pane=home]');
  ok(realHome.includes('۳۷ میلیون'), 'برگشت به داده واقعی: عددها دست‌نخورده');

  // ---------- ۱۰. ماندگاری بعد از بارگذاری دوباره ----------
  await page.reload(); await page.waitForTimeout(300);
  ok(!(await page.isVisible('#wizard')), 'بعد از reload، ویزارد دوباره باز نمی‌شود');
  ok((await page.textContent('section[data-pane=home]')).includes('۳۷ میلیون'), 'داده بعد از reload ماند');
  // پشتیبان نامعتبر
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=settings]');
  await page.fill('#backup', '{"foo":1}'); await page.click('[data-act=import]');
  ok((await page.textContent('#toast')).includes('معتبر نیست'), 'پشتیبان نامعتبر رد شد و داده پاک نشد');
  await page.click('[data-act=copy]');
  const backup = await page.inputValue('#backup');
  await ctx.close();

  // ---------- ۱۱. مهاجرت از نسخه ۱ ----------
  console.log('\n# مهاجرت از نسخه ۱');
  ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  page = await newPage(ctx);
  await page.goto(URL);
  await page.evaluate(() => { localStorage.clear(); localStorage.setItem('ghotbnama.v1', JSON.stringify({ v: 1, sample: false, profile: { name: 'مهرداد', target: 100000000, deadline: '1406/12', about: 'x' }, vision: 'چشم', streams: [{ id: 's_job', name: 'حقوق', kind: 'job', target: 0, entries: { '1405-07': 31000000 } }, { id: 's_tch', name: 'پخش تیچای', kind: 'active', target: 30000000, entries: { '1405-07': 2000000 } }], goals: [{ id: 'g1', title: 'فروشگاه ثابت و تکراری برای تیچای', horizon: 'quarter', cur: 0, target: 30, unit: 'فروشگاه', deadline: '1405/10', ms: [] }, { id: 'g2', title: 'هدف واقعی من', horizon: 'month', cur: 2, target: 5, unit: 'مشتری', deadline: '1405/08', ms: [] }], today: { date: 'x', tasks: [] }, history: {}, reviews: [{ id: 'r1', date: '1405-07-01', did: 'a', result: 'b', fail: 'c', lesson: 'd', focus: 'e' }] })); });
  await page.reload(); await page.waitForTimeout(300);
  const mig = await page.evaluate(() => JSON.parse(localStorage.getItem('ghotbnama.v2')));
  ok(mig && mig.v === 2, 'نسخه ۱ به نسخه ۲ مهاجرت کرد');
  ok(mig.real.profile.target === 0, 'هدف ۱۰۰ میلیون (عدد نمونه قبلی) پاک شد');
  ok(mig.real.streams.find(s => s.id === 's_tch').target === 0 && mig.real.streams.find(s => s.id === 's_job').entries['1405-07'] === 31000000, 'هدف نمونه منبع پاک شد، درآمد واقعی حفظ شد');
  const g1 = mig.real.goals.find(g => g.title.includes('تیچای')), g2 = mig.real.goals.find(g => g.title === 'هدف واقعی من');
  ok(g1.status === 'draft' && g1.target === 0, 'هدف پیشنهادی نمونه قبلی به پیش‌نویس بدون عدد تبدیل شد');
  ok(g2.status === 'active' && g2.target === 5, 'هدف واقعی کاربر حفظ و فعال شد');
  ok(mig.real.reviews.length === 1 && mig.real.reviews[0].best === 'b', 'بازبینی قبلی منتقل شد');
  ok((await page.textContent('#banners')).includes('منتقل شد'), 'پیام مهاجرت نمایش داده شد');
  ok(await page.isVisible('#wizard'), 'بعد از مهاجرت، ویزارد برای تکمیل باز می‌شود');
  // v1 sample
  await page.evaluate(() => { localStorage.clear(); localStorage.setItem('ghotbnama.v1', JSON.stringify({ v: 1, sample: true, profile: { target: 100000000 }, streams: [{ id: 's_job', name: 'حقوق', entries: { '1405-07': 32000000 } }], goals: [], reviews: [] })); });
  await page.reload(); await page.waitForTimeout(300);
  const mig2 = await page.evaluate(() => JSON.parse(localStorage.getItem('ghotbnama.v2')));
  ok(mig2.real.streams.length === 0 && mig2.real.profile.target === 0, 'داده نمونه نسخه ۱ به داده واقعی منتقل نشد');
  // بازگردانی پشتیبان
  await page.click('[data-act=wz-demo]');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=settings]');
  await page.fill('#backup', backup); await page.click('[data-act=import]');
  ok((await page.textContent('section[data-pane=home]')).includes('۳۷ میلیون'), 'بازگردانی پشتیبان کار کرد');
  await ctx.close();

  // ---------- ۱۲. داخل Claude: db و AI ----------
  console.log('\n# شبیه‌سازی داخل Claude (db + AI)');
  ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
  await ctx.addInitScript(FAKE_CLAUDE + `window.__db['plan/main']={state:${JSON.stringify(JSON.stringify(JSON.parse(backup)))}};`);
  page = await newPage(ctx);
  await page.goto(URL); await page.waitForTimeout(600);
  ok((await page.textContent('#modeChip')).includes('ابری'), 'داده از پایگاه داده Claude بارگذاری شد');
  ok((await page.textContent('section[data-pane=home]')).includes('۳۷ میلیون'), 'عددها از db خوانده شدند');
  await page.click('[data-act=ai-today]'); await page.waitForTimeout(200);
  ok((await page.textContent('#aiToday')).includes('تحلیل آزمایشی'), '«واقعیت امروز من» با AI ساخته شد');
  const prompt = await page.evaluate(() => window.__aiCalls[0]);
  ok(prompt.includes('VQ / Vista Quantum') && prompt.includes('# پروژه‌ها') && prompt.includes('# اقدامات ۱۴ روز اخیر') && prompt.includes('# بازبینی‌های اخیر'), 'مربی اهداف، پروژه‌ها، اقدامات، درآمد و بازبینی‌ها را می‌خواند');
  ok(!prompt.includes('Sample Data'), 'در داده واقعی، هشدار نمونه به AI فرستاده نمی‌شود');
  await page.click('nav.bottom [data-tab=coach]');
  ok((await page.$$('[data-act=coach-preset]')).length === 9, '۹ دکمه آماده مربی');
  await page.click('[data-act=coach-preset][data-k=tomorrow]'); await page.waitForTimeout(200);
  ok(await page.isVisible('[data-act=plan-add]'), 'برنامه فردا به‌صورت ساختاریافته ساخته شد');
  await page.click('[data-act=plan-add]');
  const tmr = await page.textContent('section[data-pane=today]');
  ok(tmr.includes('تماس با ۳ مدیر کارخانه') && tmr.includes('فردا'), 'برنامه AI به «فردا» اضافه شد');
  ok(!tmr.includes('bogus'), 'id پروژه نامعتبر از AI پذیرفته نشد');
  await page.click('nav.bottom [data-tab=coach]');
  await page.click('[data-act=coach-preset][data-k=stop]'); await page.waitForTimeout(150);
  await page.fill('#coachQ', 'چرا؟'); await page.click('form[data-form=coach] button.btn.ai'); await page.waitForTimeout(150);
  const turns = await page.evaluate(() => window.__aiCalls[window.__aiCalls.length - 1]);
  ok(Array.isArray(turns) && turns.length === 3 && turns[1].role === 'assistant', 'سؤال آزاد ادامه گفت‌وگو را با تاریخچه می‌فرستد');
  await page.waitForTimeout(800);
  const dbState = await page.evaluate(() => JSON.parse(window.__db['plan/main'].state));
  ok(dbState.real.coachLog.length >= 2 && Object.keys(dbState.real.days).length >= 2, 'تغییرات در db ذخیره شد');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=review]');
  await page.click('[data-act=ai-review]'); await page.waitForTimeout(150);
  ok((await page.textContent('section[data-pane=review]')).includes('تحلیل آزمایشی'), 'گزارش مدیریتی AI برای بازبینی ساخته شد');
  await page.click('nav.bottom [data-tab=more]'); await page.click('.menu [data-tab=reality]');
  await page.click('[data-act=ai-reality]'); await page.waitForTimeout(150);
  ok((await page.textContent('#aiReality')).includes('تحلیل آزمایشی'), 'جمع‌بندی هفتگی AI ساخته شد');
  await ctx.close();

  // ---------- ۱۳. عرض کم و اسکرول افقی ----------
  ctx = await browser.newContext({ viewport: { width: 360, height: 780 } });
  await ctx.addInitScript(`localStorage.setItem('ghotbnama.v2', ${JSON.stringify(backup)});`);
  page = await newPage(ctx);
  await page.goto(URL); await page.waitForTimeout(300);
  for (const t of ['home', 'command', 'today', 'coach', 'goals', 'projects', 'income', 'review', 'reality', 'settings']) {
    await page.evaluate(t => { document.querySelector('nav.bottom [data-tab=home]').click(); }, t);
    await page.evaluate(t => { const b = document.createElement('button'); b.dataset.act = 'go'; b.dataset.tab = t; document.body.appendChild(b); b.click(); b.remove(); }, t);
    const sw = await page.evaluate(() => document.documentElement.scrollWidth);
    ok(sw <= 360, `بدون اسکرول افقی در ${t} (عرض ${sw})`);
  }
  await ctx.close();

  console.log(`\nنتیجه: ${passes} موفق، ${fails} ناموفق`);
  console.log('خطاهای صفحه:', errors.length ? errors : 'هیچ');
  await browser.close();
  process.exit(fails || errors.length ? 1 : 0);
})().catch(e => { console.error(e); process.exit(2); });
