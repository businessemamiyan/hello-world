/* مهرداد — اپ وب (فارسی/RTL). داده فقط با توکن دستگاه از /api می‌آید؛ هیچ داده‌ای داخل خود فایل‌ها نیست. */
(() => {
'use strict';
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const FA = '۰۱۲۳۴۵۶۷۸۹';
const fa = s => String(s).replace(/\d/g, d => FA[d]);
const money = n => fa(Math.round(n || 0).toLocaleString('en'));
const store = {
  get: k => { try { return localStorage.getItem(k); } catch { return null; } },
  set: (k, v) => { try { localStorage.setItem(k, v); } catch {} },
  del: k => { try { localStorage.removeItem(k); } catch {} },
};
const ICON = {income:'💰', expense:'💸', meal:'🍽', smoking:'💨', intimacy:'❤️', workout:'🏃', sleep:'😴',
  feeling:'💭', task:'✅', goal:'🎯', idea:'💡', habit:'🔥', note:'📝', other:'•'};
const THEMES = {night:'شب', day:'روز', amber:'کهربایی', ocean:'اقیانوسی'};
const RANGES = {today:'امروز', week:'۷ روز', month:'این ماه'};
const SHORT_KINDS = 'income,expense,meal,smoking,intimacy,workout,sleep,feeling,task,goal,idea,habit,note,other';

// ------------------------------------------------------------- وضعیت
let token = store.get('mehrdad_token') || '';
const hash = new URLSearchParams(location.hash.slice(1));
if (hash.get('t')) { token = hash.get('t'); store.set('mehrdad_token', token); history.replaceState(null, '', location.pathname); }
if (!token && window.MehrdadNative && MehrdadNative.getToken) token = MehrdadNative.getToken() || '';
const S = { tab: store.get('mehrdad_tab') || 'today', mview: 'tx', mrange: 'month', lrange: 'week', priv: store.get('mehrdad_priv') === '1',
            cache: {}, busy: false };
applyTheme(store.get('mehrdad_theme') || 'night');

function applyTheme(t) {
  if (!THEMES[t]) t = 'night';
  if (t === 'night') document.documentElement.removeAttribute('data-theme'); else document.documentElement.dataset.theme = t;
  store.set('mehrdad_theme', t);
  const meta = $('meta[name=theme-color]');
  if (meta) meta.content = getComputedStyle(document.documentElement).getPropertyValue('--bg').trim() || '#0A0F18';
}

// ------------------------------------------------------------- شبکه
async function api(path, { method = 'GET', body } = {}) {
  const r = await fetch(path, { method, headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
                                body: body ? JSON.stringify(body) : undefined });
  if (r.status === 401) { logout(true); throw new Error('unauthorized'); }
  if (!r.ok) { let m = ''; try { const j = await r.json(); m = typeof j.detail === 'string' ? j.detail : ''; } catch {} throw new Error(m || ('خطا ' + r.status)); }
  return r.json();
}
function logout(silent) {
  token = ''; store.del('mehrdad_token');
  if (window.MehrdadNative && MehrdadNative.clearToken) MehrdadNative.clearToken();
  if (!silent) toast('قطع شد');
  boot();
}
let toastTimer;
function toast(msg) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.hidden = true; }, 3200);
}

// ------------------------------------------------------------- اجزای کوچک
function g2j(gy, gm, gd) {
  const gdm = [0,31,59,90,120,151,181,212,243,273,304,334], gy2 = gm > 2 ? gy + 1 : gy;
  let days = 355666 + 365 * gy + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100) + Math.floor((gy2 + 399) / 400) + gd + gdm[gm - 1];
  let jy = -1595 + 33 * Math.floor(days / 12053); days %= 12053;
  jy += 4 * Math.floor(days / 1461); days %= 1461;
  if (days > 365) { jy += Math.floor((days - 1) / 365); days = (days - 1) % 365; }
  const jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
  const jd = days < 186 ? 1 + days % 31 : 1 + (days - 186) % 30;
  return [jy, jm, jd];
}
const jdate = s => { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(s || ''); if (!m) return s || '';
  const [y, mo, d] = g2j(+m[1], +m[2], +m[3]); return fa(`${y}/${String(mo).padStart(2, '0')}/${String(d).padStart(2, '0')}`); };
const en = s => String(s).replace(/[۰-۹]/g, d => '۰۱۲۳۴۵۶۷۸۹'.indexOf(d)).replace(/[٠-٩]/g, d => '٠١٢٣٤٥٦٧٨٩'.indexOf(d)).replace(/[,٬،\s]/g, '');
const ACCKIND = { bank: 'بانک', cash: 'نقد', wallet: 'کیف پول', crypto: 'کریپتو', other: 'سایر' };
const DEBTKIND = { installment: 'قسط', loan: 'وام', credit_card: 'کارت اعتباری', personal: 'شخصی', other: 'سایر' };
const kpi = (l, v, cls = '') => `<div class="kpi ${cls}"><div class="v num">${v}</div><div class="l">${l}</div></div>`;
const seg = (scope, cur) => `<div class="seg" role="group">${Object.entries(RANGES).map(([k, v]) =>
  `<button data-act="seg" data-scope="${scope}" data-val="${k}" aria-pressed="${cur === k}">${v}</button>`).join('')}</div>`;
const empty = t => `<div class="m-empty">${t}</div>`;
const hidden = kind => kind === 'intimacy' && !S.priv;

function tlItem(i) {
  const sign = i.kind === 'income' ? '+' : '−';
  const cls = i.kind === 'income' ? 'm-pos' : 'm-neg';
  return `<div class="m-tl"><span class="m-ic">${ICON[i.kind] || '•'}</span>
    <div class="m-tl-b"><div>${esc(i.summary)}</div><div class="muted small">${esc(i.label)}${i.category ? ' · ' + esc(i.category) : ''} · <span class="num">${i.range === 'today' ? '' : esc(i.date) + ' '}${esc(i.time)}</span></div></div>
    ${i.amount ? `<b class="num ${cls}">${sign}${money(i.amount)}</b>` : '<span></span>'}
    <button class="x" data-act="edit" data-id="${i.id}" aria-label="ویرایش">✎</button>
    <button class="x" data-act="del" data-id="${i.id}" aria-label="حذف">✕</button></div>`;
}
function timeline(items, range) {
  const list = items.filter(i => !hidden(i.kind)).map(i => ({ ...i, range }));
  return list.length ? list.slice().reverse().map(tlItem).join('') : empty('هنوز چیزی ثبت نشده.');
}

function chart(daily, keys) {
  const n = daily.length || 1, W = Math.max(320, n * 24), H = 150, top = 8, bot = 22;
  const max = Math.max(1, ...daily.map(d => Math.max(...keys.map(k => d[k.k] || 0))));
  const bw = W / n, inner = H - top - bot;
  let bars = '', lbl = '';
  daily.forEach((d, i) => {
    keys.forEach((k, j) => {
      const h = (d[k.k] || 0) / max * inner, w = bw * (0.76 / keys.length), x = W - (i + 1) * bw + bw * 0.12 + j * w;
      if (h > 0) bars += `<rect x="${x.toFixed(1)}" y="${(top + inner - h).toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${k.c}"/>`;
    });
    if (n <= 10 || i % Math.ceil(n / 10) === 0 || i === n - 1)
      lbl += `<text x="${(W - i * bw - bw / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle" font-size="10" fill="var(--ink3)">${d.day}</text>`;
  });
  const base = `<line x1="0" y1="${top + inner}" x2="${W}" y2="${top + inner}" stroke="var(--line)"/>`;
  return `<div class="m-chart"><svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet" role="img">${base}${bars}${lbl}</svg></div>`;
}

function catBars(map, color) {
  const rows = Object.entries(map).sort((a, b) => b[1] - a[1]).slice(0, 8);
  if (!rows.length) return empty('دسته‌ای نیست.');
  const max = rows[0][1] || 1;
  return rows.map(([c, v]) => `<div class="m-cat"><span>${esc(c)}</span><div class="bar"><i style="width:${(v / max * 100).toFixed(0)}%;background:${color}"></i></div><b class="num small">${money(v)}</b></div>`).join('');
}

function habitsCard(h) {
  if (!h || !h.length) return '';
  return `<div class="card"><div class="row spread"><h2>عادت‌ها</h2><span class="pill gold">${fa(h.length)} فعال</span></div>` +
    h.map(x => `<div class="row spread"><span>${esc(x.good)}${x.bad ? ` <span class="muted small">(به‌جای ${esc(x.bad)})</span>` : ''}</span><span class="pill ${x.streak ? 'good' : ''} num">🔥 ${fa(x.streak)} روز</span></div>`).join('') + '</div>';
}

function taskRow(t) {
  const done = (t.fields || {}).status === 'done';
  const due = (t.fields || {}).due;
  return `<div class="m-task ${done ? 'done' : ''}"><button class="m-check" data-act="toggle" data-id="${t.id}" aria-label="انجام شد">✓</button>
    <div><div class="m-t">${esc(t.summary)}</div>${due ? `<div class="muted small">موعد: ${esc(jdate(due))}</div>` : ''}</div>
    <button class="x" data-act="edit" data-id="${t.id}" aria-label="ویرایش">✎</button><button class="x" data-act="del" data-id="${t.id}" aria-label="حذف">✕</button></div>`;
}

function composer(id, ph) {
  const mic = (window.MehrdadNative && MehrdadNative.startVoice) || window.SpeechRecognition || window.webkitSpeechRecognition;
  return `<div class="m-composer"><textarea id="${id}" rows="2" placeholder="${ph}" aria-label="پیام"></textarea>
    ${mic ? `<button class="m-mic" data-act="mic" data-for="${id}" aria-label="گفتن">🎤</button>` : ''}
    <button class="m-send" data-act="say" data-for="${id}" aria-label="ارسال">↑</button></div>`;
}

// ------------------------------------------------------------- صفحه‌ها
async function viewToday() {
  const d = await api('/api/dashboard?range=today'); S.cache.today = d;
  $('#subtitle').textContent = d.today_jalali;
  const f = d.finance, c = d.counts || {};
  const tasks = d.tasks || [], open = tasks.filter(t => (t.fields || {}).status !== 'done');
  const net = f.net;
  return `<section class="pane">
    <div class="north"><span class="eyebrow">امروز · ${esc(d.today_jalali)}</span>
      <div class="fig"><strong class="num">${net < 0 ? '−' : ''}${money(Math.abs(net))}</strong><span>تومان خالص امروز</span></div>
      <div class="meta"><span>درآمد <b class="num m-pos">${money(f.income)}</b></span><span>خرج <b class="num m-neg">${money(f.expense)}</b></span></div></div>
    <div class="card ai"><div class="row spread"><h2>امروز چی شد؟</h2><span class="pill ai">مهرداد</span></div>
      ${composer('sayToday', 'مثلاً: ۲۰۰ ت فروش داشتم، ناهار برنج خوردم')}
      <p class="muted small">هر چه بنویسی خودش در بخش درست ثبت می‌شود.</p></div>
    <div class="kpis">${kpi('وعدهٔ غذا', fa(c.meal || 0))}${kpi('قلیان/سیگار', fa(c.smoking || 0), c.smoking ? 'warn' : '')}${kpi('ورزش', fa(c.workout || 0), c.workout ? 'good' : '')}${kpi('کار باز', fa(open.length))}</div>
    <div class="card"><div class="row spread"><h2>برنامهٔ امروز</h2><span class="pill num">${fa(open.length)} باز</span></div>
      ${open.length ? open.map(taskRow).join('') : empty('کار بازی نیست. یکی اضافه کن یا به مهرداد بگو.')}
      <form class="row" data-form="task" style="flex-wrap:nowrap"><input type="text" name="title" placeholder="کار تازه…" required maxlength="200"><button class="btn primary" type="submit">افزودن</button></form></div>
    ${habitsCard(d.habits)}
    <div class="card"><div class="row spread"><h2>امروز چه گذشت</h2><span class="muted small">${fa((d.items || []).filter(i => !hidden(i.kind)).length)} مورد</span></div>${timeline(d.items || [], 'today')}</div>
  </section>`;
}

const mviewSeg = () => `<div class="seg" role="group" style="justify-self:start">
  <button data-act="mview" data-val="tx" aria-pressed="${S.mview === 'tx'}">تراکنش‌ها</button>
  <button data-act="mview" data-val="wealth" aria-pressed="${S.mview === 'wealth'}">دارایی و بدهی</button></div>`;

async function viewWealth() {
  const f = await api('/api/finance'); S.cache.fin = f;
  const s = f.summary, today = new Date();
  const lvl = { crit: 'crit', warn: 'warn', good: 'good', info: 'info' };
  const accRow = a => `<div class="m-tl" style="grid-template-columns:1fr auto auto auto"><div class="m-tl-b"><div>${esc(a.name)}</div><div class="muted small">${ACCKIND[a.kind] || a.kind}${a.note ? ' · ' + esc(a.note) : ''}</div></div>
    <b class="num">${money(a.balance)}</b><button class="x" data-act="acc-edit" data-id="${a.id}" aria-label="ویرایش">✎</button><button class="x" data-act="acc-del" data-id="${a.id}" aria-label="حذف">✕</button></div>`;
  const debtCard = d => {
    const paidPct = d.total > 0 ? Math.max(0, Math.min(100, (d.total - d.remaining) / d.total * 100)) : 0;
    const due = d.next_due ? new Date(d.next_due + 'T00:00:00') : null;
    const days = due ? Math.round((due - new Date(today.getFullYear(), today.getMonth(), today.getDate())) / 86400000) : null;
    const pill = days === null ? '' : days < 0 ? `<span class="pill crit">${fa(-days)} روز گذشته</span>` : days <= 7 ? `<span class="pill warn">${days === 0 ? 'امروز' : fa(days) + ' روز دیگر'}</span>` : `<span class="pill">${fa(days)} روز دیگر</span>`;
    return `<div class="card m-goal"><div class="row spread"><b>${esc(d.title)}</b><span class="row" style="gap:4px"><span class="pill gold">${DEBTKIND[d.kind] || ''}</span>
      <button class="x" data-act="debt-edit" data-id="${d.id}" aria-label="ویرایش">✎</button><button class="x" data-act="debt-del" data-id="${d.id}" aria-label="حذف">✕</button></span></div>
      <div class="row spread"><span class="muted small">${d.creditor ? esc(d.creditor) + ' · ' : ''}مانده <b class="num">${money(d.remaining)}</b> از <span class="num">${money(d.total)}</span></span>${pill}</div>
      <div class="bar good"><i style="width:${paidPct.toFixed(0)}%"></i></div>
      <div class="row spread"><span class="small">قسط <b class="num">${money(d.installment_amount)}</b>${d.next_due ? ' · سررسید <span class="num">' + esc(jdate(d.next_due)) + '</span>' : ''}${d.installments_total ? ' · <span class="num">' + fa(d.installments_paid) + '/' + fa(d.installments_total) + '</span> قسط' : ''}</span>
      ${d.status === 'active' ? `<button class="btn primary sm" data-act="debt-pay" data-id="${d.id}">✓ پرداخت قسط</button>` : '<span class="pill good">تسویه شد</span>'}</div></div>`;
  };
  const active = f.debts.filter(d => d.status === 'active'), paid = f.debts.filter(d => d.status !== 'active');
  return `<section class="pane">${mviewSeg()}
    <div class="north"><span class="eyebrow">ارزش خالص (دارایی − بدهی)</span>
      <div class="fig"><strong class="num">${s.net_worth < 0 ? '−' : ''}${money(Math.abs(s.net_worth))}</strong><span>تومان</span></div>
      <div class="meta"><span>دارایی <b class="num m-pos">${money(s.assets)}</b></span><span>بدهی <b class="num m-neg">${money(s.debts_total)}</b></span></div></div>
    <div class="kpis m-k3">${kpi('نقد', money(s.liquid), 'good')}${kpi('اقساط ماهانه', money(s.monthly_obligations), s.monthly_obligations ? 'warn' : '')}${kpi('اقساط ۳۰ روز', money(s.next30_due), s.next30_due > s.liquid ? 'crit' : '')}</div>
    <div class="stack">${s.alerts.map(a => `<div class="issue ${lvl[a.level] || 'info'}"><span class="tag">${esc(a.tag)}</span><div>${esc(a.text)}</div></div>`).join('')}</div>
    <div class="card ai"><div class="row spread"><h2>بررسی با مهرداد</h2><span class="pill ai">مربی</span></div>
      <p class="muted small">حساب‌ها، اقساط و درآمد/خرج واقعی‌ات را کنار هم می‌بیند و راه‌حل می‌دهد.</p>
      <div class="row"><button class="btn ai" data-act="ask-fin" data-q="وضعیت مالی‌ام را کامل بررسی کن: حساب‌ها، اقساط، درآمد و خرج. مشکل‌ها و یک برنامهٔ مشخص برای پرداخت بدهی‌ها و پس‌انداز بده.">بررسی کامل</button>
      <button class="btn" data-act="ask-fin" data-q="این ماه کدام خرج‌هایم را می‌توانم کم کنم تا اقساط را راحت‌تر بدهم؟">کجا خرج کم کنم؟</button></div><div id="finOut"></div></div>
    <div class="card"><div class="row spread"><h2>🏦 حساب‌ها و موجودی</h2><span class="pill num">${fa(f.accounts.length)}</span></div>
      ${f.accounts.length ? f.accounts.map(accRow).join('') : empty('هنوز حسابی ثبت نشده.')}
      <form class="form" data-form="account"><label class="f"><span>نام (مثلاً بانک ملی)</span><input type="text" name="name" required maxlength="60"></label>
        <label class="f"><span>نوع</span><select name="kind">${Object.entries(ACCKIND).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label>
        <label class="f"><span>موجودی (تومان)</span><input type="number" name="balance" inputmode="numeric" required></label>
        <button class="btn primary" type="submit">افزودن حساب</button></form></div>
    <h2>⛓ بدهی و اقساط</h2>
    <div class="stack">${active.length ? active.map(debtCard).join('') : `<div class="card">${empty('بدهی فعالی ثبت نشده 🎉')}</div>`}</div>
    <div class="card"><h2>افزودن بدهی/قسط</h2><form class="form" data-form="debt">
      <label class="f full"><span>عنوان (مثلاً قسط گوشی)</span><input type="text" name="title" required maxlength="100"></label>
      <label class="f"><span>نوع</span><select name="kind">${Object.entries(DEBTKIND).map(([k, v]) => `<option value="${k}">${v}</option>`).join('')}</select></label>
      <label class="f"><span>طلبکار</span><input type="text" name="creditor" maxlength="80"></label>
      <label class="f"><span>مبلغ کل</span><input type="number" name="total" inputmode="numeric" required min="0"></label>
      <label class="f"><span>مانده فعلی (اگر کمتر است)</span><input type="number" name="remaining" inputmode="numeric" min="0"></label>
      <label class="f"><span>مبلغ هر قسط</span><input type="number" name="installment_amount" inputmode="numeric" min="0"></label>
      <label class="f"><span>تعداد کل اقساط</span><input type="number" name="installments_total" inputmode="numeric" min="1"></label>
      <label class="f"><span>روز سررسید در ماه (۱ تا ۳۱)</span><input type="number" name="due_day" inputmode="numeric" min="1" max="31"></label>
      <button class="btn primary" type="submit">افزودن</button></form></div>
    ${s.payoff.length ? `<div class="card"><h2>کی بدهی‌ها تمام می‌شود؟</h2>${s.payoff.map(p => `<div class="row spread"><span>${esc(p.title)}</span><span class="pill num">${fa(p.months_left)} ماه · ${esc(p.free_on)}</span></div>`).join('')}</div>` : ''}
    ${paid.length ? `<details class="card"><summary>تسویه‌شده‌ها (${fa(paid.length)})</summary>${paid.map(debtCard).join('')}</details>` : ''}
  </section>`;
}

async function viewMoney() {
  if (S.mview === 'wealth') return viewWealth();
  const d = await api('/api/dashboard?range=' + S.mrange); S.cache.money = d;
  const f = d.finance;
  const money_items = (d.items || []).filter(i => i.kind === 'income' || i.kind === 'expense');
  return `<section class="pane">
    ${mviewSeg()}<div class="pane-title"><h1>حساب‌ها</h1>${seg('mrange', S.mrange)}</div>
    <div class="kpis m-k3">${kpi('درآمد', money(f.income), 'good')}${kpi('خرج', money(f.expense), f.expense > f.income ? 'crit' : '')}${kpi('خالص', (f.net < 0 ? '−' : '') + money(Math.abs(f.net)), f.net >= 0 ? 'good' : 'crit')}</div>
    <div class="card"><div class="row spread"><h2>روند روزانه</h2><div class="m-legend"><span><i style="background:var(--good)"></i>درآمد</span><span><i style="background:var(--crit)"></i>خرج</span></div></div>
      ${chart(d.daily || [], [{k:'income', c:'var(--good)'}, {k:'expense', c:'var(--crit)'}])}</div>
    <div class="card"><h2>درآمد به تفکیک منبع</h2>${catBars(f.by_category.income, 'var(--good)')}</div>
    <div class="card"><h2>خرج به تفکیک دسته</h2>${catBars(f.by_category.expense, 'var(--crit)')}</div>
    <div class="card"><h2>ثبت سریع</h2>
      <form class="form" data-form="money">
        <label class="f"><span>نوع</span><select name="type"><option value="income">درآمد</option><option value="expense" selected>خرج</option></select></label>
        <label class="f"><span>مبلغ (تومان)</span><input type="number" name="amount" inputmode="numeric" min="0" required></label>
        <label class="f"><span>دسته / منبع</span><input type="text" name="category" maxlength="60" placeholder="مثلاً فروش فیلترشکن"></label>
        <label class="f full"><span>توضیح</span><input type="text" name="summary" maxlength="200"></label>
        <button class="btn primary" type="submit">ثبت</button></form></div>
    <div class="card"><div class="row spread"><h2>ردیف‌ها</h2><span class="muted small">${fa(money_items.length)} مورد</span></div>${timeline(money_items, S.mrange)}</div>
  </section>`;
}

async function viewLife() {
  const d = await api('/api/dashboard?range=' + S.lrange); S.cache.life = d;
  const c = d.counts || {}, items = d.items || [];
  const by = k => items.filter(i => i.kind === k);
  const sec = (k, title, extra = '') => by(k).length ? `<div class="card"><div class="row spread"><h2>${ICON[k]} ${title}</h2><span class="pill num">${fa(by(k).length)}</span></div>${extra}${timeline(by(k), S.lrange)}</div>` : '';
  const intimacy = S.priv
    ? sec('intimacy', 'زندگی زناشویی')
    : `<div class="card"><div class="m-lock">🔒 <span>بخش‌های خصوصی پنهان‌اند. با دکمهٔ 🔒 بالا نشانشان بده.</span></div></div>`;
  return `<section class="pane">
    <div class="pane-title"><h1>زندگی</h1>${seg('lrange', S.lrange)}</div>
    <div class="kpis">${kpi('غذا', fa(c.meal || 0))}${kpi('قلیان/سیگار', fa(c.smoking || 0), c.smoking ? 'warn' : '')}${kpi('ورزش', fa(c.workout || 0), c.workout ? 'good' : '')}${kpi('خواب ثبت‌شده', fa(c.sleep || 0))}</div>
    ${habitsCard(d.habits)}
    ${(d.daily || []).length > 1 && c.smoking ? `<div class="card"><h2>💨 قلیان/سیگار در روزها</h2>${chart(d.daily, [{k:'smoking', c:'var(--warn)'}])}</div>` : ''}
    ${sec('meal', 'غذا')}${sec('workout', 'ورزش')}${sec('sleep', 'خواب')}${sec('feeling', 'حال‌وحال')}${sec('smoking', 'قلیان/سیگار')}
    ${intimacy}
    ${!items.filter(i => !hidden(i.kind)).length ? `<div class="card">${empty('در این بازه چیزی ثبت نشده.')}</div>` : ''}
  </section>`;
}

async function viewGoals() {
  const r = await api('/api/events?kind=goal,task&limit=150'); const ev = r.events;
  S.cache.goals = ev;
  const goals = ev.filter(e => e.type === 'goal'), tasks = ev.filter(e => e.type === 'task');
  const open = tasks.filter(t => (t.fields || {}).status !== 'done'), done = tasks.filter(t => (t.fields || {}).status === 'done');
  const goalCard = g => { const p = Number((g.fields || {}).progress || 0), h = (g.fields || {}).horizon;
    return `<div class="card m-goal"><div class="row spread"><b>${esc(g.summary)}</b><span class="row" style="gap:4px">${h ? `<span class="pill gold">${esc(h)}</span>` : ''}
      <button class="x" data-act="edit" data-id="${g.id}" aria-label="ویرایش">✎</button><button class="x" data-act="del" data-id="${g.id}" aria-label="حذف">✕</button></span></div>
      <div class="bar ${p >= 100 ? 'good' : ''}"><i style="width:${Math.min(100, p)}%"></i></div>
      <div class="row spread"><input type="range" min="0" max="100" step="5" value="${p}" data-act="progress" data-id="${g.id}" aria-label="پیشرفت"><span class="num small muted">${fa(p)}٪</span></div></div>`; };
  return `<section class="pane">
    <div class="pane-title"><h1>هدف‌ها و برنامه</h1></div>
    <div class="card ai"><div class="row spread"><h2>برنامه‌ریزی با مهرداد</h2><span class="pill ai">مربی</span></div>
      <p class="muted small">بر اساس هدف‌ها و کارهای بازت، برنامهٔ هفته را می‌چیند.</p>
      <div class="row"><button class="btn ai" data-act="plan" data-what="هفته">برنامهٔ این هفته</button><button class="btn" data-act="plan" data-what="امروز">برنامهٔ امروز</button></div>
      <div id="planOut"></div></div>
    <h2>🎯 هدف‌ها</h2>
    <div class="stack">${goals.length ? goals.map(goalCard).join('') : `<div class="card">${empty('هدفی ثبت نشده؛ بنویس یا اضافه کن.')}</div>`}</div>
    <div class="card"><h2>افزودن هدف</h2><form class="form" data-form="goal">
      <label class="f full"><span>هدف</span><input type="text" name="title" required maxlength="200" placeholder="مثلاً درآمد ماهانه ۵۰ میلیون"></label>
      <label class="f"><span>افق</span><input type="text" name="horizon" maxlength="30" placeholder="ماه / سال / ۳ سال"></label>
      <button class="btn primary" type="submit">افزودن</button></form></div>
    <h2>✅ کارها</h2>
    <div class="card">${open.length ? open.map(taskRow).join('') : empty('کار بازی نیست.')}
      <form class="row" data-form="task" style="flex-wrap:nowrap"><input type="text" name="title" placeholder="کار تازه…" required maxlength="200"><button class="btn primary" type="submit">افزودن</button></form></div>
    ${done.length ? `<details class="card"><summary>انجام‌شده‌ها (${fa(done.length)})</summary>${done.map(taskRow).join('')}</details>` : ''}
  </section>`;
}

async function viewChat() {
  const r = await api('/api/history?limit=80');
  const msgs = r.messages.map(m => `<div class="m-b ${m.role === 'user' ? 'me' : 'bot'}">${esc(m.text)}</div>`).join('');
  return `<section class="pane"><div class="pane-title"><h1>گفتگو با مهرداد</h1></div>
    <div class="m-chatwrap"><div class="m-chat" id="chatList">${msgs || empty('هنوز چیزی نگفته‌ای.')}</div></div>
    <div class="m-composer-fixed">${composer('sayChat', 'بنویس یا با 🎤 بگو…')}</div></section>`;
}

const VIEWS = { today: viewToday, money: viewMoney, life: viewLife, goals: viewGoals, chat: viewChat };

async function render() {
  const view = $('#view');
  try {
    view.innerHTML = await VIEWS[S.tab]();
  } catch (e) {
    if (e.message !== 'unauthorized') view.innerHTML = `<section class="pane"><div class="card"><h2>خطا</h2><p class="muted">${esc(e.message)}</p><button class="btn" data-act="reload">دوباره</button></div></section>`;
    return;
  }
  $$('#nav button').forEach(b => b.setAttribute('aria-current', b.dataset.tab === S.tab ? 'page' : 'false'));
  if (S.tab === 'chat') window.scrollTo(0, document.body.scrollHeight);
}

function go(tab) { S.tab = tab; store.set('mehrdad_tab', tab); render(); window.scrollTo(0, 0); }

// ------------------------------------------------------------- ویرایش / تنظیمات
function sheet(html) { const m = $('#modal'); m.innerHTML = `<div class="m-sheet" role="dialog">${html}</div>`; m.hidden = false; }
function closeSheet() { const m = $('#modal'); m.hidden = true; m.innerHTML = ''; }

function findEvent(id) {
  id = Number(id);
  for (const k of ['today', 'money', 'life']) { const f = (S.cache[k]?.items || []).find(i => i.id === id); if (f) return { id, type: f.kind, summary: f.summary, amount: f.amount, category: f.category, fields: f.fields || {} }; }
  for (const e of (S.cache.today?.tasks || []).concat(S.cache.goals || [])) if (e.id === id) return e;
  return null;
}
function openEdit(id) {
  const e = findEvent(id); if (!e) return;
  const fin = e.type === 'income' || e.type === 'expense';
  sheet(`<div class="row spread"><h2>ویرایش ${ICON[e.type] || ''}</h2><button class="x" data-act="close">✕</button></div>
    <form class="form" data-form="edit" data-id="${e.id}">
      <label class="f full"><span>متن</span><input type="text" name="summary" value="${esc(e.summary)}" maxlength="300" required></label>
      ${fin ? `<label class="f"><span>مبلغ (تومان)</span><input type="number" name="amount" value="${e.amount ?? ''}" min="0"></label>
        <label class="f"><span>دسته</span><input type="text" name="category" value="${esc(e.category || '')}" maxlength="60"></label>` : ''}
      <button class="btn primary" type="submit">ذخیره</button><button class="btn danger" type="button" data-act="del" data-id="${e.id}">حذف</button></form>`);
}
function openAccEdit(id) {
  const a = (S.cache.fin?.accounts || []).find(x => x.id === Number(id)); if (!a) return;
  sheet(`<div class="row spread"><h2>ویرایش حساب</h2><button class="x" data-act="close">✕</button></div>
    <form class="form" data-form="acc-edit" data-id="${a.id}"><label class="f full"><span>نام</span><input type="text" name="name" value="${esc(a.name)}" required maxlength="60"></label>
      <label class="f"><span>موجودی (تومان)</span><input type="number" name="balance" value="${a.balance}" inputmode="numeric" required></label>
      <button class="btn primary" type="submit">ذخیره</button></form>`);
}
function openDebtEdit(id) {
  const d = (S.cache.fin?.debts || []).find(x => x.id === Number(id)); if (!d) return;
  sheet(`<div class="row spread"><h2>ویرایش بدهی</h2><button class="x" data-act="close">✕</button></div>
    <form class="form" data-form="debt-edit" data-id="${d.id}"><label class="f full"><span>عنوان</span><input type="text" name="title" value="${esc(d.title)}" required maxlength="100"></label>
      <label class="f"><span>مانده</span><input type="number" name="remaining" value="${d.remaining}" min="0" inputmode="numeric"></label>
      <label class="f"><span>مبلغ قسط</span><input type="number" name="installment_amount" value="${d.installment_amount}" min="0" inputmode="numeric"></label>
      <label class="f"><span>روز سررسید</span><input type="number" name="due_day" value="${d.due_day ?? ''}" min="1" max="31" inputmode="numeric"></label>
      <button class="btn primary" type="submit">ذخیره</button></form>`);
}
function openSettings() {
  sheet(`<div class="row spread"><h2>تنظیمات</h2><button class="x" data-act="close">✕</button></div>
    <div class="stack"><span class="eyebrow">تم</span><div class="seg">${Object.entries(THEMES).map(([k, v]) =>
      `<button data-act="theme" data-val="${k}" aria-pressed="${(document.documentElement.dataset.theme || 'night') === k}">${v}</button>`).join('')}</div>
    <label class="row"><input type="checkbox" id="privChk" ${S.priv ? 'checked' : ''}> نمایش بخش‌های خصوصی (🔒)</label>
    <p class="muted small">پیامک بانکی و اعلان‌های مالی را اپ اندروید می‌فرستد. برای قطع این دستگاه در تلگرام /devices و /unpair.</p>
    <button class="btn danger" data-act="logout">خروج از این دستگاه</button></div>`);
}

// ------------------------------------------------------------- جفت‌سازی
function pairScreen() {
  $('#nav').hidden = true; $('#subtitle').textContent = 'مغز دوم تو';
  $('#view').innerHTML = `<section class="m-center"><div class="card"><h1>سلام، من مهردادم 👋</h1>
    <p>برای وصل‌شدن: در تلگرام به مهرداد بنویس <b>/pair</b> و کد ۸ حرفی را اینجا بزن.</p>
    <form class="stack" data-form="pair"><input type="text" name="code" placeholder="کد جفت‌سازی" autocomplete="off" autocapitalize="characters" maxlength="16" dir="ltr" required>
    <button class="btn primary" type="submit">اتصال</button></form></div></section>`;
}

// ------------------------------------------------------------- گفتن (چت / ضبط سریع)
async function say(forId) {
  const ta = $('#' + forId); const text = ta.value.trim(); if (!text || S.busy) return;
  S.busy = true; ta.value = '';
  const send = $(`[data-act=say][data-for=${forId}]`); if (send) send.disabled = true;
  if (forId === 'sayChat') {
    const list = $('#chatList'); const empt = $('.m-empty', list); if (empt) empt.remove();
    list.insertAdjacentHTML('beforeend', `<div class="m-b me">${esc(text)}</div><div class="m-b bot typing" id="typing"><span class="m-spin"></span></div>`);
    window.scrollTo(0, document.body.scrollHeight);
  } else toast('در حال ثبت…');
  try {
    const r = await api('/api/chat', { method: 'POST', body: { text } });
    if (forId === 'sayChat') { const t = $('#typing'); if (t) { t.classList.remove('typing'); t.removeAttribute('id'); t.textContent = r.reply; } window.scrollTo(0, document.body.scrollHeight); }
    else { toast(r.reply.length > 110 ? r.reply.slice(0, 110) + '…' : r.reply); await render(); }
  } catch (e) {
    if (e.message !== 'unauthorized') { toast('نشد: ' + e.message); const t = $('#typing'); if (t) t.textContent = 'نتوانستم به مغز برسم؛ دوباره امتحان کن.'; ta.value = text; }
  } finally { S.busy = false; const s2 = $(`[data-act=say][data-for=${forId}]`); if (s2) s2.disabled = false; }
}
function mic(forId) {
  const ta = $('#' + forId);
  if (window.MehrdadNative && MehrdadNative.startVoice) { window.onVoiceText = t => { ta.value = t; ta.focus(); }; MehrdadNative.startVoice(); return; }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (!SR) return toast('گفتار در این مرورگر نیست');
  const rec = new SR(); rec.lang = 'fa-IR'; rec.interimResults = false;
  const btn = $(`[data-act=mic][data-for=${forId}]`); btn.classList.add('on');
  rec.onresult = e => { ta.value = e.results[0][0].transcript; ta.focus(); };
  rec.onend = () => btn.classList.remove('on'); rec.onerror = () => { btn.classList.remove('on'); toast('گفتار نشد'); };
  rec.start();
}

// ------------------------------------------------------------- رویدادهای کلیک/فرم
document.addEventListener('click', async ev => {
  const nav = ev.target.closest('#nav button'); if (nav) return go(nav.dataset.tab);
  if (ev.target.id === 'setBtn') return openSettings();
  if (ev.target.id === 'privBtn') { S.priv = !S.priv; store.set('mehrdad_priv', S.priv ? '1' : '0'); syncPriv(); return render(); }
  if (ev.target.id === 'modal') return closeSheet();
  const b = ev.target.closest('[data-act]'); if (!b) return;
  const act = b.dataset.act, id = b.dataset.id;
  try {
    if (act === 'close') closeSheet();
    else if (act === 'reload') render();
    else if (act === 'seg') { S[b.dataset.scope] = b.dataset.val; render(); }
    else if (act === 'edit') openEdit(id);
    else if (act === 'mview') { S.mview = b.dataset.val; render(); }
    else if (act === 'acc-edit') openAccEdit(id);
    else if (act === 'debt-edit') openDebtEdit(id);
    else if (act === 'acc-del') { if (confirm('این حساب حذف شود؟')) { await api('/api/accounts/' + id, { method: 'DELETE' }); render(); } }
    else if (act === 'debt-del') { if (confirm('این بدهی حذف شود؟')) { await api('/api/debts/' + id, { method: 'DELETE' }); render(); } }
    else if (act === 'debt-pay') {
      const d = (S.cache.fin?.debts || []).find(x => x.id === Number(id)); if (!d) return;
      const v = prompt('مبلغ پرداختی (تومان):', String(d.installment_amount || d.remaining)); if (v === null) return;
      const amount = Number(en(v)); if (!(amount >= 0)) return toast('مبلغ نامعتبر');
      await api(`/api/debts/${id}/pay`, { method: 'POST', body: { amount } }); toast('قسط ثبت شد ✓ (در حساب‌ها هم خرج شد)'); render();
    }
    else if (act === 'ask-fin') {
      const out = $('#finOut'); out.innerHTML = '<span class="m-spin"></span> مهرداد دارد حساب‌هایت را بررسی می‌کند…'; b.disabled = true;
      try { const r = await api('/api/chat', { method: 'POST', body: { text: b.dataset.q } }); out.innerHTML = `<div class="m-b bot" style="max-width:100%">${esc(r.reply)}</div>`; } finally { b.disabled = false; }
    }
    else if (act === 'del') { if (confirm('حذف شود؟')) { await api('/api/events/' + id, { method: 'DELETE' }); closeSheet(); toast('حذف شد'); render(); } }
    else if (act === 'toggle') { const e = findEvent(id); const done = (e.fields || {}).status === 'done';
      await api('/api/events/' + id, { method: 'PATCH', body: { fields: { status: done ? 'open' : 'done' } } }); render(); }
    else if (act === 'say') say(b.dataset.for);
    else if (act === 'mic') mic(b.dataset.for);
    else if (act === 'theme') { applyTheme(b.dataset.val); $$('.seg [data-act=theme]').forEach(x => x.setAttribute('aria-pressed', x === b)); }
    else if (act === 'logout') { closeSheet(); logout(false); }
    else if (act === 'plan') {
      const out = $('#planOut'); out.innerHTML = '<span class="m-spin"></span> مهرداد دارد برنامه می‌چیند…'; b.disabled = true;
      try { const r = await api('/api/chat', { method: 'POST', body: { text: `برنامهٔ ${b.dataset.what}‌ام را بر اساس هدف‌ها و کارهای بازم و عادت‌هایم بچین. کوتاه و قابل‌اجرا، با ساعت‌بندی پیشنهادی.` } });
        out.innerHTML = `<div class="m-b bot" style="max-width:100%">${esc(r.reply)}</div>`; } finally { b.disabled = false; }
    }
  } catch (e) { if (e.message !== 'unauthorized') toast(e.message); }
});

document.addEventListener('change', async ev => {
  const t = ev.target;
  if (t.id === 'privChk') { S.priv = t.checked; store.set('mehrdad_priv', S.priv ? '1' : '0'); syncPriv(); render(); }
  else if (t.dataset.act === 'progress') {
    try { await api('/api/events/' + t.dataset.id, { method: 'PATCH', body: { fields: { progress: Number(t.value) } } }); render(); } catch (e) { toast(e.message); }
  }
});

document.addEventListener('keydown', ev => {
  if (ev.target.matches && ev.target.matches('textarea[id^=say]') && ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing) { ev.preventDefault(); say(ev.target.id); }
});

document.addEventListener('submit', async ev => {
  const f = ev.target.closest('form[data-form]'); if (!f) return; ev.preventDefault();
  const kind = f.dataset.form, v = Object.fromEntries(new FormData(f).entries());
  try {
    if (kind === 'pair') {
      const r = await fetch('/api/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: v.code.trim(), name: navigator.userAgent.includes('Android') ? 'مرورگر گوشی' : 'مرورگر' }) });
      if (!r.ok) return toast(r.status === 429 ? 'تلاش زیاد؛ ۱۰ دقیقه بعد' : 'کد اشتباه یا منقضی است. دوباره /pair بزن.');
      token = (await r.json()).token; store.set('mehrdad_token', token);
      if (window.MehrdadNative && MehrdadNative.savePairing) MehrdadNative.savePairing(location.origin, token);
      toast('وصل شد ✓'); return boot();
    }
    if (kind === 'task') await api('/api/events', { method: 'POST', body: { type: 'task', summary: v.title.trim(), fields: { status: 'open' } } });
    else if (kind === 'goal') await api('/api/events', { method: 'POST', body: { type: 'goal', summary: v.title.trim(), fields: { progress: 0, horizon: (v.horizon || '').trim() || undefined } } });
    else if (kind === 'money') await api('/api/events', { method: 'POST', body: { type: v.type, summary: (v.summary || '').trim() || (v.type === 'income' ? 'درآمد' : 'خرج'),
      amount: Number(v.amount), category: (v.category || '').trim() || undefined } });
    else if (kind === 'edit') {
      const body = { summary: v.summary.trim() }; if ('amount' in v) body.amount = v.amount === '' ? null : Number(v.amount); if ('category' in v) body.category = v.category.trim() || null;
      await api('/api/events/' + f.dataset.id, { method: 'PATCH', body }); closeSheet();
    }
    else if (kind === 'account') await api('/api/accounts', { method: 'POST', body: { name: v.name.trim(), kind: v.kind, balance: Number(v.balance) } });
    else if (kind === 'acc-edit') { await api('/api/accounts/' + f.dataset.id, { method: 'PATCH', body: { name: v.name.trim(), balance: Number(v.balance) } }); closeSheet(); }
    else if (kind === 'debt') {
      const num = k => (v[k] === '' || v[k] === undefined) ? undefined : Number(v[k]);
      await api('/api/debts', { method: 'POST', body: { title: v.title.trim(), kind: v.kind, creditor: (v.creditor || '').trim() || undefined, total: num('total') || 0,
        remaining: num('remaining'), installment_amount: num('installment_amount') || 0, installments_total: num('installments_total'), due_day: num('due_day') } });
    }
    else if (kind === 'debt-edit') {
      const body = { title: v.title.trim() }; for (const k of ['remaining', 'installment_amount', 'due_day']) if (v[k] !== '') body[k] = Number(v[k]);
      await api('/api/debts/' + f.dataset.id, { method: 'PATCH', body }); closeSheet();
    }
    toast('ثبت شد ✓'); render();
  } catch (e) { if (e.message !== 'unauthorized') toast(e.message); }
});

function syncPriv() { const b = $('#privBtn'); b.classList.toggle('on', S.priv); b.textContent = S.priv ? '🔓' : '🔒'; }

// ------------------------------------------------------------- شروع
function boot() {
  syncPriv();
  if (!token) return pairScreen();
  $('#nav').hidden = false;
  render();
}
boot();
})();
