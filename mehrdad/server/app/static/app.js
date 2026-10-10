/* مهراد — اپ وب (فارسی/RTL). داده فقط با توکن دستگاه از /api می‌آید؛ هیچ داده‌ای داخل خود فایل‌ها نیست. */
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
const ICON = {profile:'🧬', activity:'🧭', income:'💰', expense:'💸', meal:'🍽', smoking:'💨', intimacy:'❤️', workout:'🏃', sleep:'😴',
  feeling:'💭', task:'✅', goal:'🎯', idea:'💡', habit:'🔥', note:'📝', other:'•'};
const THEMES = {night:'شب', day:'روز', amber:'کهربایی', ocean:'اقیانوسی'};
const RANGES = {today:'امروز', week:'۷ روز', month:'این ماه'};
const SHORT_KINDS = 'income,expense,meal,smoking,intimacy,workout,sleep,feeling,task,goal,idea,habit,note,other';

// ------------------------------------------------------------- وضعیت
let token = store.get('mehrdad_token') || '';
const hash = new URLSearchParams(location.hash.slice(1));
if (hash.get('t')) { token = hash.get('t'); store.set('mehrdad_token', token); history.replaceState(null, '', location.pathname); }
if (!token && window.MehrdadNative && MehrdadNative.getToken) token = MehrdadNative.getToken() || '';
const S = { tab: store.get('mehrdad_tab') || 'today', mview: 'tx', gview: 'goals', mrange: 'month', lrange: 'week', priv: store.get('mehrdad_priv') === '1',
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
const dur = m => { m = Math.round(m || 0); const h = Math.floor(m / 60), r = m % 60;
  return h && r ? `${fa(h)} ساعت و ${fa(r)} دقیقه` : h ? `${fa(h)} ساعت` : `${fa(r)} دقیقه`; };
const STATUS = { ongoing: ['در جریان', 'info'], planned: ['برنامه', 'gold'], maybe: ['احتمالی', ''] };
const kpi = (l, v, cls = '') => `<div class="kpi ${cls}"><div class="v num">${v}</div><div class="l">${l}</div></div>`;
const seg = (scope, cur) => `<div class="seg" role="group">${Object.entries(RANGES).map(([k, v]) =>
  `<button data-act="seg" data-scope="${scope}" data-val="${k}" aria-pressed="${cur === k}">${v}</button>`).join('')}</div>`;
const empty = t => `<div class="m-empty">${t}</div>`;
const hidden = kind => kind === 'intimacy' && !S.priv;

function tlItem(i) {
  const sign = i.kind === 'income' ? '+' : '−';
  const cls = i.kind === 'income' ? 'm-pos' : 'm-neg';
  const st = STATUS[i.status];
  const pending = i.status === 'planned' || i.status === 'maybe' || i.status === 'ongoing';
  const span = i.end_time ? `${i.time}–${i.end_time}` : i.time;
  return `<div class="m-tl${st && i.status !== 'ongoing' ? ' m-plan' : ''}"><span class="m-ic">${ICON[i.kind] || '•'}</span>
    <div class="m-tl-b"><div>${esc(i.summary)}${i.uncertain ? ' <span class="pill warn" title="مهراد مطمئن نیست">؟</span>' : ''}</div>
      <div class="muted small">${esc(i.label)}${i.category ? ' · ' + esc(i.category) : ''} · <span class="num">${i.range === 'today' ? '' : esc(i.date) + ' '}${esc(span)}</span>${i.minutes ? ' · <span class="num">' + dur(i.minutes) + '</span>' : ''}${st ? ` <span class="pill ${st[1]}">${st[0]}</span>` : ''}</div></div>
    ${i.amount ? `<b class="num ${cls}">${sign}${money(i.amount)}</b>` : '<span></span>'}
    ${pending ? `<button class="x" data-act="mark-done" data-id="${i.id}" aria-label="انجام شد" title="انجام شد">✓</button>` : '<span></span>'}
    <button class="x" data-act="edit" data-id="${i.id}" aria-label="ویرایش">✎</button>
    <button class="x" data-act="del" data-id="${i.id}" aria-label="حذف">✕</button></div>`;
}
function timeline(items, range) {
  const list = items.filter(i => !hidden(i.kind)).map(i => ({ ...i, range }));
  const ordered = range === 'today' ? list : list.slice().reverse();
  return ordered.length ? ordered.map(tlItem).join('') : empty('هنوز چیزی ثبت نشده.');
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

function groupKpis(d, max = 4) {
  const g = (d.groups || []).filter(x => !(x.kind === 'intimacy' && !S.priv)).slice(0, max);
  if (!g.length) return `<div class="kpis"><div class="kpi"><div class="v">—</div><div class="l">هنوز فعالیتی ثبت نشده</div></div></div>`;
  return `<div class="kpis">${g.map(x => kpi(esc(x.name), x.minutes ? dur(x.minutes) : fa(x.count), x.kind === 'smoking' ? 'warn' : '')).join('')}</div>`;
}
function timeBars(d) {
  const t = d.time_by_category || [];
  if (!t.length) return '';
  const max = t[0].minutes || 1, total = t.reduce((a, x) => a + x.minutes, 0);
  return `<div class="card"><div class="row spread"><h2>⏱ زمان به تفکیک</h2><span class="pill num">${dur(total)}</span></div>` +
    t.slice(0, 8).map(x => `<div class="m-cat"><span>${esc(x.name)}</span><div class="bar"><i style="width:${(x.minutes / max * 100).toFixed(0)}%"></i></div><b class="num small">${dur(x.minutes)}</b></div>`).join('') + '</div>';
}
function plannedLine(f) {
  const pe = f.planned_expense || 0, pi = f.planned_income || 0;
  if (!pe && !pi) return '';
  return `<div class="issue info"><span class="tag">برنامه‌ریزی‌شده</span><div>هنوز حساب نشده: ${pe ? 'خرج ' + money(pe) : ''}${pe && pi ? ' | ' : ''}${pi ? 'درآمد ' + money(pi) : ''} تومان</div></div>`;
}
function activityForm() {
  return `<div class="card"><h2>ثبت فعالیت</h2><form class="form" data-form="activity">
    <label class="f full"><span>چه کاری؟</span><input type="text" name="title" required maxlength="200" placeholder="مثلاً آموزش برنامه‌نویسی"></label>
    <label class="f"><span>دسته</span><input type="text" name="category" list="actcats" maxlength="60" placeholder="کار / یادگیری / رفت‌وآمد…">
      <datalist id="actcats"><option value="کار"><option value="یادگیری"><option value="رفت‌وآمد"><option value="ورزش"><option value="استراحت"><option value="خانواده"></datalist></label>
    <label class="f"><span>از ساعت</span><input type="time" name="start"></label>
    <label class="f"><span>تا ساعت</span><input type="time" name="end"></label>
    <label class="f"><span>یا مدت (دقیقه)</span><input type="number" name="minutes" min="1" max="1440" inputmode="numeric"></label>
    <label class="f"><span>وضعیت</span><select name="status"><option value="done">انجام شد</option><option value="ongoing">در جریان</option><option value="planned">برنامه</option></select></label>
    <button class="btn primary" type="submit">ثبت</button></form></div>`;
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
    <button class="m-mic" data-act="photo" data-for="${id}" aria-label="عکس" title="عکس فیش/رسید">📷</button>
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
    <div class="card ai"><div class="row spread"><h2>امروز چی شد؟</h2><span class="pill ai">مهراد</span></div>
      ${composer('sayToday', 'مثلاً: ۲۰۰ ت فروش داشتم، ناهار برنج خوردم')}
      <p class="muted small">هر چه بنویسی خودش در بخش درست ثبت می‌شود.</p></div>
    ${plannedLine(f)}
    ${groupKpis(d, 4)}
    ${timeBars(d)}
    <div class="card"><div class="row spread"><h2>برنامهٔ امروز</h2><span class="pill num">${fa(open.length)} باز</span></div>
      ${open.length ? open.map(taskRow).join('') : empty('کار بازی نیست. یکی اضافه کن یا به مهراد بگو.')}
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
    <div class="card ai"><div class="row spread"><h2>بررسی با مهراد</h2><span class="pill ai">مربی</span></div>
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
    ${plannedLine(f)}
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
    ${groupKpis(d, 8)}
    ${timeBars(d)}
    ${activityForm()}
    ${S.lrange === 'today' || S.lrange === 'week' ? `<div class="card"><div class="row spread"><h2>🧭 زمان‌بندی</h2><span class="muted small">${fa(items.filter(i => !hidden(i.kind)).length)} مورد</span></div>${timeline(items.filter(i => !['meal','smoking','intimacy','feeling'].includes(i.kind) || true), S.lrange)}</div>` : ''}
    ${habitsCard(d.habits)}
    ${(d.daily || []).length > 1 && c.smoking ? `<div class="card"><h2>💨 قلیان/سیگار در روزها</h2>${chart(d.daily, [{k:'smoking', c:'var(--warn)'}])}</div>` : ''}
    ${sec('meal', 'غذا')}${sec('workout', 'ورزش')}${sec('sleep', 'خواب')}${sec('feeling', 'حال‌وحال')}${sec('smoking', 'قلیان/سیگار')}
    ${intimacy}
    ${!items.filter(i => !hidden(i.kind)).length ? `<div class="card">${empty('در این بازه چیزی ثبت نشده.')}</div>` : ''}
  </section>`;
}

const gviewSeg = () => `<div class="seg" role="group" style="justify-self:start">
  <button data-act="gview" data-val="goals" aria-pressed="${S.gview === 'goals'}">هدف‌ها</button>
  <button data-act="gview" data-val="habits" aria-pressed="${S.gview === 'habits'}">عادت‌ها و روتین</button>
  <button data-act="gview" data-val="profile" aria-pressed="${S.gview === 'profile'}">پروفایل من</button></div>`;

async function viewHabits() {
  const [p, d] = await Promise.all([api('/api/profile'), api('/api/dashboard?range=today')]);
  const bad = p.habits.filter(h => h.kind === 'bad'), good = p.habits.filter(h => h.kind !== 'bad');
  const hrow = h => `<div class="m-tl" style="grid-template-columns:1fr auto auto"><div class="m-tl-b"><div>${esc(h.name)} <span class="pill ${h.kind === 'bad' ? 'warn' : 'good'}">${h.kind === 'bad' ? 'بد' : 'خوب'}</span></div>
      <div class="muted small">۷ روز: ${h.minutes_7d ? dur(h.minutes_7d) : fa(h.count_7d) + ' بار'} در ${fa(h.days_7d)} روز · ۳۰ روز: ${h.minutes_30d ? dur(h.minutes_30d) : '—'}</div></div>
      <span></span>${h.kind === 'bad' ? `<button class="btn sm" data-act="track-habit" data-name="${esc(h.name)}">پیگیری کن</button>` : '<span></span>'}</div>`;
  return `<section class="pane">${gviewSeg()}
    <div class="pane-title"><h1>عادت‌ها و روتین</h1></div>
    <div class="card"><div class="row spread"><h2>🧭 روتین‌های منظم</h2><span class="pill num">${fa(p.routines.length)}</span></div>
      <p class="muted small">مهراد از روی چیزهایی که می‌گویی تشخیص می‌دهد (مثلاً «رفتم سر کار ایساتیس») و خودش روتین می‌سازد.</p>
      ${p.routines.length ? p.routines.map(r => `<div class="m-tl" style="grid-template-columns:1fr auto"><div class="m-tl-b"><div>${esc(r.name)}</div>
        <div class="muted small">${fa(r.per_week)} روز در هفته · معمولاً <span class="num">${esc(r.avg_start)}${r.avg_end ? '–' + esc(r.avg_end) : ''}</span>${r.avg_minutes ? ' · ' + dur(r.avg_minutes) : ''}</div></div>
        <span class="pill num">${fa(r.days)} روز</span></div>`).join('') : empty('هنوز روتینی تشخیص داده نشده؛ چند روز روزت را تعریف کن.')}</div>
    <div class="card"><div class="row spread"><h2>🔍 عادت‌هایی که دیده‌ام</h2><span class="pill num">${fa(p.habits.length)}</span></div>
      <p class="muted small">حتی اگر اسمش را عادت نگذاشته باشی (اسکرول اینستاگرام، قلیان، …)؛ این‌ها در هدف‌گذاری وزن دارند.</p>
      ${bad.map(hrow).join('')}${good.map(hrow).join('')}${p.habits.length ? '' : empty('هنوز عادتی دیده نشده.')}</div>
    ${habitsCard(d.habits)}
    <div class="card"><h2>افزودن عادت برای پیگیری</h2><form class="form" data-form="habit">
      <label class="f"><span>عادت خوب</span><input type="text" name="good" required maxlength="120" placeholder="مثلاً مطالعهٔ ۲۰ دقیقه"></label>
      <label class="f"><span>به‌جای (اختیاری)</span><input type="text" name="bad" maxlength="120" placeholder="مثلاً اسکرول شبانه"></label>
      <button class="btn primary" type="submit">افزودن</button></form></div>
  </section>`;
}

async function viewProfile() {
  const [p, inv] = await Promise.all([api('/api/profile'), api('/api/invites')]);
  S.cache.profile = p;
  const by = {};
  p.profile.forEach(e => (by[e.category || 'سایر'] ||= []).push(e));
  const c = p.completeness, pct = Math.round(c.filled / c.total * 100);
  const fact = e => { const wife = (e.fields || {}).source === 'همسر';
    return `<div class="m-tl" style="grid-template-columns:1fr auto auto"><div class="m-tl-b"><div>${esc(e.summary)}</div>${wife ? '<div class="muted small">از زبان همسرت</div>' : ''}</div>
      <span class="pill ${wife ? 'gold' : ''}">${wife ? 'همسر' : 'خودت'}</span><button class="x" data-act="del" data-id="${e.id}" aria-label="حذف">✕</button></div>`; };
  const secs = p.sections.concat(Object.keys(by).filter(k => !p.sections.includes(k)));
  const invRow = i => `<div class="row spread"><span>${esc(i.label || 'لینک')} · <span class="num">${fa(i.uses)}/${fa(i.max_uses)}</span> ${i.revoked ? '<span class="pill crit">باطل</span>' : i.expires_ts < Date.now() / 1000 ? '<span class="pill warn">منقضی</span>' : ''}</span>
      ${!i.revoked ? `<button class="btn sm danger" data-act="revoke-inv" data-id="${i.id}">ابطال</button>` : ''}</div>`;
  return `<section class="pane">${gviewSeg()}
    <div class="pane-title"><h1>پروفایل من</h1><span class="pill num">${fa(c.filled)} از ${fa(c.total)} بخش</span></div>
    <div class="card"><div class="bar"><i style="width:${pct}%"></i></div>
      <p class="muted small">هر چه بیشتر بدانم، هدف‌ها و برنامه‌ها دقیق‌تر می‌شوند. ${c.missing.length ? 'خالی: ' + esc(c.missing.slice(0, 4).join('، ')) : 'همهٔ بخش‌ها پر است 👏'}</p>
      <div class="row"><button class="btn ai" data-act="say-onboard">شروع مصاحبه در چت</button><span class="muted small">یا در تلگرام: /onboard</span></div></div>
    <div class="card gold"><div class="row spread"><h2>💌 لینک برای همسرت</h2><span class="pill gold">او دربارهٔ تو جواب می‌دهد</span></div>
      <p class="muted small">یک لینک امن و فقط برای پرسش‌نامه؛ او هیچ‌چیز از اطلاعات تو را نمی‌بیند. پاسخ‌هایش اینجا برای خودت دیدنی و قابل‌حذف است و او این را در صفحه می‌خواند.</p>
      <div class="row"><button class="btn primary" data-act="make-invite">ساخت لینک تازه</button></div><div id="inviteOut"></div>
      ${inv.invites.length ? `<div class="stack6" style="margin-top:6px">${inv.invites.map(invRow).join('')}</div>` : ''}</div>
    ${secs.filter(k => by[k]).map(k => `<div class="card"><div class="row spread"><h2>${esc(k)}</h2><span class="pill num">${fa(by[k].length)}</span></div>${by[k].slice().reverse().map(fact).join('')}</div>`).join('')
      || `<div class="card">${empty('هنوز چیزی دربارهٔ تو ثبت نشده. شروع کن: «من … هستم و …» یا مصاحبه را بزن.')}</div>`}
  </section>`;
}

async function viewGoals() {
  if (S.gview === 'habits') return viewHabits();
  if (S.gview === 'profile') return viewProfile();
  const r = await api('/api/events?kind=goal,task&limit=150'); const ev = r.events;
  S.cache.goals = ev;
  const goals = ev.filter(e => e.type === 'goal'), tasks = ev.filter(e => e.type === 'task');
  const open = tasks.filter(t => (t.fields || {}).status !== 'done'), done = tasks.filter(t => (t.fields || {}).status === 'done');
  const goalCard = g => { const p = Number((g.fields || {}).progress || 0), h = (g.fields || {}).horizon;
    return `<div class="card m-goal"><div class="row spread"><b>${esc(g.summary)}</b><span class="row" style="gap:4px">${h ? `<span class="pill gold">${esc(h)}</span>` : ''}
      <button class="x" data-act="edit" data-id="${g.id}" aria-label="ویرایش">✎</button><button class="x" data-act="del" data-id="${g.id}" aria-label="حذف">✕</button></span></div>
      ${(g.fields || {}).why ? `<div class="muted small">چرا: ${esc(g.fields.why)}</div>` : ''}
      ${((g.fields || {}).steps || []).length ? `<ul class="small" style="margin:0;padding-inline-start:18px">${g.fields.steps.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
      <div class="bar ${p >= 100 ? 'good' : ''}"><i style="width:${Math.min(100, p)}%"></i></div>
      <div class="row spread"><input type="range" min="0" max="100" step="5" value="${p}" data-act="progress" data-id="${g.id}" aria-label="پیشرفت"><span class="num small muted">${fa(p)}٪</span></div></div>`; };
  return `<section class="pane">${gviewSeg()}
    <div class="pane-title"><h1>هدف‌ها و برنامه</h1></div>
    <div class="card gold"><div class="row spread"><h2>🎯 هدف‌گذاری هوشمند</h2><span class="pill gold">بر اساس شناخت از تو</span></div>
      <p class="muted small">مهراد بر پایهٔ پروفایل، روتین‌ها، عادت‌ها و مالی‌ات هدف پیشنهاد می‌دهد؛ هر کدام را خودت تأیید می‌کنی.</p>
      <div class="row"><button class="btn primary" data-act="suggest-goals">پیشنهاد هدف</button></div><div id="goalSuggest"></div></div>
    <div class="card ai"><div class="row spread"><h2>برنامه‌ریزی با مهراد</h2><span class="pill ai">مربی</span></div>
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
  return `<section class="pane"><div class="pane-title"><h1>گفتگو با مهراد</h1></div>
    <div class="m-chatwrap"><div class="m-chat" id="chatList">${msgs || empty('هنوز چیزی نگفته‌ای.')}</div></div>
    <div class="m-composer-fixed">${composer('sayChat', 'بنویس یا با 🎤 بگو…')}</div></section>`;
}

const BOOK_ST = { suggested: 'پیشنهادی', reading: 'در حال مطالعه', done: 'تمام شد' };
async function viewCoach() {
  const c = await api('/api/coach'); S.cache.coach = c;
  const st = c.stats, p = c.plan, done = c.done || {};
  const head = `<div class="pane-title"><h1>مربی</h1><span class="row" style="gap:6px"><span class="pill gold num">🔥 ${fa(st.streak)} روز</span><span class="pill num">سطح ${fa(st.level)}</span></span></div>`;
  if (c.generating) {
    setTimeout(() => { if (S.tab === 'coach') render(); }, 3000);
    return `<section class="pane">${head}<div class="card ai"><h2><span class="m-spin"></span> مربی دارد برنامهٔ امروزت را می‌چیند…</h2><p class="muted small">معمولاً ۳۰ تا ۶۰ ثانیه؛ از روی چیزهایی که دربارهٔ تو می‌داند.</p></div></section>`;
  }
  const books = c.books || [];
  const tasks = (key, title, sub, extra = '') => `<div class="m-task ${done[key] ? 'done' : ''}"><button class="m-check" data-act="coach-done" data-key="${key}" aria-label="انجام شد">✓</button>
    <div><div class="m-t">${esc(title)}</div>${sub ? `<div class="muted small">${sub}</div>` : ''}</div>${extra || '<span></span>'}<span></span></div>`;
  const bookCard = b => `<div class="card m-goal"><div class="row spread"><b>${esc(b.title)}</b><span class="pill ${b.status === 'done' ? 'good' : b.status === 'reading' ? 'gold' : ''}">${BOOK_ST[b.status] || ''}</span></div>
      <div class="muted small">${b.author ? esc(b.author) : ''}${b.level ? ' · ' + esc(b.level) : ''}</div>${b.why ? `<div class="small">${esc(b.why)}</div>` : ''}
      ${(b.lessons || []).map(l => `<details ${S.openLesson === b.id + ':' + l.n ? 'open' : ''}><summary>درس ${fa(l.n)}: ${esc(l.title)}</summary><div class="c-body small" style="margin-top:6px">${esc(l.body)}</div></details>`).join('')}
      <div class="row"><button class="btn sm primary" data-act="coach-lesson" data-id="${b.id}">${(b.lessons || []).length ? 'درس بعدی' : 'شروع آموزش کتاب'}</button>
        ${b.status !== 'done' ? `<button class="btn sm" data-act="coach-book" data-id="${b.id}" data-st="done">تمام شد</button>` : ''}<button class="x" data-act="coach-book-del" data-id="${b.id}" aria-label="حذف">✕</button></div><div id="bk${b.id}"></div></div>`;
  const library = `<h2>📚 کتاب و آموزش</h2>
    <div class="card ai"><div class="row spread"><h2>از مربی بپرس / یاد بگیر</h2><span class="pill ai">استاد</span></div>
      <p class="muted small">هر موضوعی که می‌خواهی (فروش، تمرکز، مدیریت پول، زبان…) برایت درس مستقل و تمرین می‌دهد.</p>
      <div class="row" style="flex-wrap:nowrap"><input type="text" id="teachTopic" placeholder="مثلاً: چطور فروش فیلترشکن را بالا ببرم؟" maxlength="300"><button class="btn primary" data-act="coach-teach">یاد بده</button></div><div id="teachOut"></div></div>
    <div class="stack">${books.length ? books.map(bookCard).join('') : `<div class="card">${empty('هنوز کتابی نیست. پیشنهاد بگیر یا خودت اضافه کن.')}</div>`}</div>
    <div class="row"><button class="btn ai" data-act="coach-rec">پیشنهاد کتاب برای من</button></div><div id="recOut"></div>
    <form class="row" data-form="coach-book" style="flex-wrap:nowrap"><input type="text" name="title" placeholder="اسم کتابی که می‌خواهی یاد بگیری…" required maxlength="120"><button class="btn" type="submit">افزودن</button></form>`;
  if (!p) return `<section class="pane">${head}<div class="card ai"><h2>برنامهٔ امروز هنوز ساخته نشده</h2>
      <p class="muted small">مربی با توجه به شناختی که از تو دارد: تمرکز روز، روتین ساعت‌بندی‌شده، یک درس، یک چالش، چند سؤال و راه تبدیل عادت‌های بد را می‌سازد. هر روز ساعت ۷ صبح هم خودش می‌سازد و در تلگرام می‌فرستد.</p>
      ${c.error ? `<p class="small" style="color:var(--warn)">دفعهٔ قبل نشد: ${esc(c.error)}</p>` : ''}
      <div class="row"><button class="btn primary" data-act="coach-gen">ساخت برنامهٔ امروز</button></div></div>${library}</section>`;
  const t = st.today, pct = t.total ? Math.round(t.done / t.total * 100) : 0;
  const qs = (p.questions || []).map((q, i) => { const a = (c.answers || {})[String(i)];
    return `<div class="c-q" style="padding:8px 0;border-bottom:1px solid var(--line)"><div class="c-id">${esc(q)}</div>${a ? `<div class="m-b me" style="max-width:100%;margin-top:6px">${esc(a.text)}</div><div class="m-b bot" style="max-width:100%;margin-top:6px">${esc(a.reply)}</div>`
      : `<textarea id="cq${i}" rows="2" placeholder="جوابت را بنویس…"></textarea><div class="row"><button class="btn sm primary" data-act="coach-answer" data-i="${i}">ثبت جواب</button></div>`}</div>`; }).join('');
  const swaps = (p.swaps || []).map((s, i) => `<div class="c-swap"><div><b>${esc(s.bad)}</b> ← <b class="m-pos">${esc(s.replacement)}</b></div>
      ${s.cue ? `<div class="muted small">نشانهٔ احتمالی: ${esc(s.cue)}</div>` : ''}${s.if_then ? `<div class="small">${esc(s.if_then)}</div>` : ''}
      ${s.tiny_step ? `<div class="small">قدم کوچک: ${esc(s.tiny_step)}</div>` : ''}${s.target ? `<div class="small">هدف این هفته: ${esc(s.target)}</div>` : ''}
      <div class="row"><button class="btn sm primary" data-act="coach-track" data-i="${i}">پیگیری‌اش کن (هر شب می‌پرسم)</button></div></div>`).join('');
  return `<section class="pane">${head}
    <div class="north"><span class="eyebrow">تمرکز امروز</span>
      <div class="fig"><strong style="font-size:1.35rem;line-height:1.5">${esc(p.focus.title)}</strong></div>
      ${p.focus.identity ? `<div class="c-id" style="color:var(--hero-sub)">${esc(p.focus.identity)}</div>` : ''}
      <div class="track"><i style="width:${pct}%"></i></div>
      <div class="meta"><span>امروز <b class="num">${fa(t.done)}</b> از <b class="num">${fa(t.total)}</b></span><span>تجربه <b class="num">${fa(st.xp)}</b></span></div>
      <div class="c-week" aria-label="۷ روز اخیر">${st.week.map(w => `<div title="${jdate(w.date)}"><i style="height:${w.total ? Math.max(6, Math.round(w.done / w.total * 100)) : 0}%"></i></div>`).join('')}</div></div>
    ${(p.routine || []).length ? `<div class="card"><div class="row spread"><h2>🧭 روتین امروز</h2><span class="muted small">پیشنهاد مربی</span></div>${p.routine.map((r, i) => tasks('r' + i, (r.time ? r.time + ' — ' : '') + r.title, esc(r.why || ''), r.minutes ? `<span class="pill num">${dur(r.minutes)}</span>` : '')).join('')}</div>` : ''}
    ${p.lesson.body ? `<div class="card"><div class="row spread"><h2>📖 ${esc(p.lesson.title || 'درس امروز')}</h2></div><div class="c-body">${esc(p.lesson.body)}</div>
      ${p.lesson.takeaway ? `<div class="c-id" style="margin-top:6px">💡 ${esc(p.lesson.takeaway)}</div>` : ''}${tasks('lesson', 'خواندم و فهمیدم', '')}</div>` : ''}
    ${p.challenge.title ? `<div class="card gold"><div class="row spread"><h2>⚡ چالش امروز</h2>${p.challenge.minutes ? `<span class="pill num">${dur(p.challenge.minutes)}</span>` : ''}</div><div class="c-id">${esc(p.challenge.title)}</div>
      ${(p.challenge.steps || []).length ? `<ol class="small" style="margin:4px 0;padding-inline-start:20px">${p.challenge.steps.map(x => `<li>${esc(x)}</li>`).join('')}</ol>` : ''}${tasks('challenge', 'انجامش دادم', '')}</div>` : ''}
    ${qs ? `<div class="card"><div class="row spread"><h2>❓ مربی از تو می‌پرسد</h2><span class="pill ai">جواب‌ها ثبت می‌شوند</span></div>${qs}</div>` : ''}
    ${swaps ? `<div class="card"><div class="row spread"><h2>🔁 عادت بد ← عادت خوب</h2></div><p class="muted small">حذف نه؛ جایگزین. هر کدام را بزن تا هر شب بپرسم چطور پیش رفتی.</p>${swaps}</div>` : ''}
    ${p.book ? `<div class="card"><div class="row spread"><h2>📚 کتاب پیشنهادی</h2></div><div class="c-id">${esc(p.book.title)}${p.book.author ? ' — ' + esc(p.book.author) : ''}</div>${p.book.why ? `<div class="small muted">${esc(p.book.why)}</div>` : ''}
      <div class="row"><button class="btn sm primary" data-act="coach-addbook" data-title="${esc(p.book.title)}" data-author="${esc(p.book.author || '')}">اضافه به کتاب‌هایم و شروع آموزش</button></div></div>` : ''}
    ${p.note ? `<div class="card"><div class="c-id">${esc(p.note)}</div></div>` : ''}
    ${library}
    <div class="row"><button class="btn sm" data-act="coach-gen" data-force="1">ساخت دوبارهٔ برنامهٔ امروز</button></div>
  </section>`;
}

const VIEWS = { today: viewToday, money: viewMoney, life: viewLife, coach: viewCoach, goals: viewGoals, chat: viewChat };
async function renderKeep() { const y = window.scrollY; await render(); window.scrollTo(0, y); }

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

let refreshing = false;
async function refreshNow() {
  if (!token || refreshing) return;
  refreshing = true;
  const b = $('#refBtn'); if (b) b.classList.add('spin');
  try { S.cache = {}; await render(); } finally { refreshing = false; if (b) b.classList.remove('spin'); }
}

// کشیدن صفحه به پایین (وقتی بالای صفحه هستی) = تازه‌سازی؛ نیمه‌کاره‌ها (فرم/پنجره‌ی باز) را خراب نمی‌کند
(function pullToRefresh() {
  const el = $('#ptr'); let y0 = null, dy = 0;
  const TH = 72;
  addEventListener('touchstart', e => {
    const open = !$('#modal').hidden || /^(INPUT|TEXTAREA|SELECT)$/.test((e.target.tagName || ''));
    y0 = (window.scrollY <= 0 && !open && e.touches.length === 1) ? e.touches[0].clientY : null; dy = 0;
  }, { passive: true });
  addEventListener('touchmove', e => {
    if (y0 === null) return;
    dy = e.touches[0].clientY - y0;
    if (dy <= 0 || window.scrollY > 0) { el.hidden = true; return; }
    el.hidden = false;
    const p = Math.min(dy, TH * 1.6);
    el.style.transform = `translate(-50%, ${p * 0.6}px) rotate(${p * 4}deg)`;
    el.classList.toggle('ready', dy >= TH);
  }, { passive: true });
  addEventListener('touchend', () => {
    const go = y0 !== null && dy >= TH;
    y0 = null; el.hidden = true; el.classList.remove('ready'); el.style.transform = '';
    if (go) refreshNow();
  }, { passive: true });
  // برگشتن به اپ بعد از چند دقیقه: داده‌ها تازه شوند (مثلاً بعد از ثبت از طریق تلگرام)
  let hiddenAt = 0;
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) { hiddenAt = Date.now(); return; }
    if (hiddenAt && Date.now() - hiddenAt > 120000 && $('#modal').hidden && S.tab !== 'chat') refreshNow();
  });
})();

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
function nativeStatus() {
  try { return window.MehrdadNative && MehrdadNative.status ? JSON.parse(MehrdadNative.status() || '{}') : null; } catch { return null; }
}
function openSettings() {
  const nat = nativeStatus();
  const natHtml = nat ? `<span class="eyebrow">این گوشی</span><div class="stack6 small">
      <div>نسخهٔ اپ: <b class="num">${esc(fa(nat.version || '?'))}</b></div>
      <div>پیامک ${nat.sms ? '✓' : '✗'} · اعلان‌ها ${nat.notif ? '✓' : '✗'} · در صف ارسال: <b class="num">${fa(nat.queue || 0)}</b></div>
      <div class="row"><button class="btn sm" data-act="n-sms">مجوز پیامک</button><button class="btn sm" data-act="n-notif">دسترسی اعلان‌ها</button>
      <button class="btn sm primary" data-act="n-update">بررسی به‌روزرسانی</button></div></div>` : '';
  sheet(`<div class="row spread"><h2>تنظیمات</h2><button class="x" data-act="close">✕</button></div>
    <div class="stack"><span class="eyebrow">تم</span><div class="seg">${Object.entries(THEMES).map(([k, v]) =>
      `<button data-act="theme" data-val="${k}" aria-pressed="${(document.documentElement.dataset.theme || 'night') === k}">${v}</button>`).join('')}</div>
    ${natHtml}
    <label class="row"><input type="checkbox" id="privChk" ${S.priv ? 'checked' : ''}> نمایش بخش‌های خصوصی (🔒)</label>
    <p class="muted small">پیامک بانکی و اعلان‌های مالی را اپ اندروید می‌فرستد. برای قطع این دستگاه در تلگرام /devices و /unpair.</p>
    <button class="btn danger" data-act="logout">خروج از این دستگاه</button></div>`);
}

// ------------------------------------------------------------- جفت‌سازی
function pairScreen() {
  $('#nav').hidden = true; $('#subtitle').textContent = 'مغز دوم تو';
  $('#view').innerHTML = `<section class="m-center"><div class="card"><h1>سلام، من مهرادم 👋</h1>
    <p>برای وصل‌شدن: در تلگرام به مهراد بنویس <b>/pair</b> و کد ۸ حرفی را اینجا بزن.</p>
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
async function downscale(file, max = 1600) {
  const url = URL.createObjectURL(file);
  try {
    const img = await new Promise((ok, bad) => { const i = new Image(); i.onload = () => ok(i); i.onerror = () => bad(new Error('عکس خوانده نشد')); i.src = url; });
    const k = Math.min(1, max / Math.max(img.naturalWidth, img.naturalHeight));
    const c = document.createElement('canvas'); c.width = Math.round(img.naturalWidth * k); c.height = Math.round(img.naturalHeight * k);
    c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
    return c.toDataURL('image/jpeg', 0.82);
  } finally { URL.revokeObjectURL(url); }
}
async function sendPhoto(file, forId) {
  if (!file || S.busy) return;
  S.busy = true;
  const ta = $('#' + forId); const caption = ta ? ta.value.trim() : ''; if (ta) ta.value = '';
  const inChat = forId === 'sayChat' && $('#chatList');
  if (inChat) {
    const list = $('#chatList'); const empt = $('.m-empty', list); if (empt) empt.remove();
    list.insertAdjacentHTML('beforeend', `<div class="m-b me">📷 ${esc(caption || 'عکس')}</div><div class="m-b bot typing" id="typing"><span class="m-spin"></span></div>`);
    window.scrollTo(0, document.body.scrollHeight);
  } else toast('مهراد دارد عکس را می‌خواند…');
  try {
    const image = await downscale(file);
    const r = await api('/api/chat/image', { method: 'POST', body: { image, text: caption } });
    if (inChat) { const t = $('#typing'); if (t) { t.classList.remove('typing'); t.removeAttribute('id'); t.textContent = r.reply; } window.scrollTo(0, document.body.scrollHeight); }
    else { toast(r.reply.length > 110 ? r.reply.slice(0, 110) + '…' : r.reply); await render(); }
  } catch (e) {
    if (e.message !== 'unauthorized') { toast('نشد: ' + e.message); const t = $('#typing'); if (t) t.textContent = 'عکس را نتوانستم بخوانم؛ دوباره امتحان کن.'; if (ta) ta.value = caption; }
  } finally { S.busy = false; }
}
document.addEventListener('change', ev => {
  if (ev.target.id !== 'photoIn') return;
  const f = ev.target.files && ev.target.files[0]; ev.target.value = '';
  if (f) sendPhoto(f, S.photoFor || 'sayChat');
});

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
  if (ev.target.id === 'refBtn') return refreshNow();
  if (ev.target.id === 'privBtn') { S.priv = !S.priv; store.set('mehrdad_priv', S.priv ? '1' : '0'); syncPriv(); return render(); }
  if (ev.target.id === 'modal') return closeSheet();
  const b = ev.target.closest('[data-act]'); if (!b) return;
  const act = b.dataset.act, id = b.dataset.id;
  try {
    if (act === 'close') closeSheet();
    else if (act === 'reload') render();
    else if (act === 'seg') { S[b.dataset.scope] = b.dataset.val; render(); }
    else if (act === 'edit') openEdit(id);
    else if (act === 'n-sms') MehrdadNative.requestSmsPermission();
    else if (act === 'n-notif') MehrdadNative.openNotificationAccess();
    else if (act === 'n-update') { closeSheet(); MehrdadNative.checkUpdate(); }
    else if (act === 'mark-done') { await api('/api/events/' + id, { method: 'PATCH', body: { status: 'done' } }); toast('انجام‌شد ✓'); render(); }
    else if (act === 'gview') { S.gview = b.dataset.val; render(); }
    else if (act === 'say-onboard') { go('chat'); setTimeout(() => { const ta = $('#sayChat'); if (ta) { ta.value = 'می‌خواهم مصاحبه شروع شود؛ یک‌یک از من سؤال کن تا مرا بشناسی.'; ta.focus(); } }, 300); }
    else if (act === 'track-habit') {
      const good = prompt(`جایگزین خوب برای «${b.dataset.name}» چیست؟`, 'پیاده‌روی ۱۰ دقیقه'); if (!good) return;
      await api('/api/habits', { method: 'POST', body: { good: good.trim(), bad: b.dataset.name } }); toast('عادت ثبت شد؛ هر شب از تو می‌پرسم 🔥'); render();
    }
    else if (act === 'make-invite') {
      const r = await api('/api/invites', { method: 'POST', body: { label: 'همسر', days: 14 } });
      $('#inviteOut').innerHTML = `<div class="note" style="padding:10px;border-radius:10px;background:var(--surface2)"><div class="small muted">این لینک را فقط برای همسرت بفرست (۱۴ روز، حداکثر ۳ بار ارسال):</div>
        <input type="text" readonly dir="ltr" value="${esc(r.url)}" id="inviteUrl" style="margin-top:6px">
        <div class="row" style="margin-top:6px"><button class="btn sm primary" data-act="copy-invite">کپی</button>${navigator.share ? '<button class="btn sm" data-act="share-invite">ارسال…</button>' : ''}</div></div>`;
    }
    else if (act === 'copy-invite') { const el = $('#inviteUrl'); el.select(); try { await navigator.clipboard.writeText(el.value); toast('کپی شد'); } catch { document.execCommand('copy'); toast('کپی شد'); } }
    else if (act === 'share-invite') { try { await navigator.share({ title: 'چند سؤال دربارهٔ من', text: 'این چند سؤال را دربارهٔ من جواب بده 🙏', url: $('#inviteUrl').value }); } catch {} }
    else if (act === 'revoke-inv') { if (confirm('این لینک باطل شود؟')) { await api('/api/invites/' + id, { method: 'DELETE' }); render(); } }
    else if (act === 'suggest-goals') {
      const out = $('#goalSuggest'); out.innerHTML = '<span class="m-spin"></span> مهراد دارد فکر می‌کند…'; b.disabled = true;
      try {
        const r = await api('/api/goals/suggest', { method: 'POST' }); S.cache.suggest = r.goals;
        out.innerHTML = r.goals.length ? r.goals.map((g, i) => `<div class="card" style="margin-top:8px"><div class="row spread"><b>${esc(g.title)}</b><span class="pill gold">${esc(g.horizon || '')}</span></div>
          ${g.why ? `<div class="muted small">چرا: ${esc(g.why)}</div>` : ''}${(g.steps || []).length ? `<ul class="small" style="margin:4px 0;padding-inline-start:18px">${g.steps.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
          <button class="btn sm primary" data-act="add-suggest" data-i="${i}">افزودن به هدف‌ها</button></div>`).join('') : empty('هنوز چیز کافی از تو نمی‌دانم؛ در «پروفایل من» مصاحبه را شروع کن.');
      } catch (e) { out.innerHTML = empty('نشد: ' + esc(e.message)); } finally { b.disabled = false; }
    }
    else if (act === 'add-suggest') {
      const g = (S.cache.suggest || [])[Number(b.dataset.i)]; if (!g) return;
      await api('/api/events', { method: 'POST', body: { type: 'goal', summary: g.title, fields: { progress: 0, horizon: g.horizon || undefined, why: g.why || undefined, steps: g.steps || undefined } } });
      b.disabled = true; b.textContent = 'اضافه شد ✓'; toast('به هدف‌ها اضافه شد');
    }
    else if (act === 'mview') { S.mview = b.dataset.val; render(); }
    else if (act === 'coach-gen') { await api('/api/coach/generate' + (b.dataset.force ? '?force=true' : ''), { method: 'POST' }); render(); }
    else if (act === 'coach-done') { const key = b.dataset.key, on = !b.closest('.m-task').classList.contains('done');
      await api('/api/coach/done', { method: 'POST', body: { key, on } }); renderKeep(); }
    else if (act === 'coach-answer') {
      const i = b.dataset.i, ta = $('#cq' + i), text = (ta.value || '').trim(); if (!text) return toast('جوابت را بنویس');
      b.disabled = true; b.textContent = 'در حال ثبت…';
      try { await api('/api/coach/answer', { method: 'POST', body: { idx: Number(i), text } }); renderKeep(); } finally { b.disabled = false; }
    }
    else if (act === 'coach-track') { const r = await api(`/api/coach/swap/${b.dataset.i}/track`, { method: 'POST' }); toast(r.existing ? 'از قبل پیگیری می‌شد 🔥' : 'ثبت شد؛ هر شب از تو می‌پرسم 🔥'); b.disabled = true; }
    else if (act === 'coach-teach') {
      const topic = ($('#teachTopic').value || '').trim(); if (topic.length < 2) return toast('موضوع را بنویس');
      const out = $('#teachOut'); out.innerHTML = '<span class="m-spin"></span> استاد دارد درس را آماده می‌کند…'; b.disabled = true;
      try { const r = await api('/api/coach/teach', { method: 'POST', body: { topic } }); out.innerHTML = `<div class="m-b bot c-body" style="max-width:100%;margin-top:8px">${esc(r.text)}</div>`; }
      catch (e) { out.innerHTML = empty('نشد: ' + esc(e.message)); } finally { b.disabled = false; }
    }
    else if (act === 'coach-rec') {
      const out = $('#recOut'); out.innerHTML = '<span class="m-spin"></span> دارم کتاب‌های مناسب تو را پیدا می‌کنم…'; b.disabled = true;
      try { const r = await api('/api/coach/books/recommend', { method: 'POST' }); toast(r.added.length ? 'کتاب‌ها اضافه شد' : 'کتاب تازه‌ای نبود'); await renderKeep(); }
      catch (e) { out.innerHTML = empty('نشد: ' + esc(e.message)); } finally { b.disabled = false; }
    }
    else if (act === 'coach-addbook') { await api('/api/coach/books', { method: 'POST', body: { title: b.dataset.title, author: b.dataset.author } }); b.disabled = true; toast('اضافه شد؛ پایین‌تر «شروع آموزش کتاب» را بزن'); renderKeep(); }
    else if (act === 'coach-lesson') {
      const out = $('#bk' + id); out.innerHTML = '<span class="m-spin"></span> استاد درس را آماده می‌کند (حدود ۱ دقیقه)…'; b.disabled = true;
      try { const r = await api(`/api/coach/books/${id}/lesson`, { method: 'POST' }); if (r.lesson) S.openLesson = id + ':' + r.lesson.n; else toast('این کتاب ۱۲ درس را تمام کرد 🎉'); await renderKeep(); }
      catch (e) { out.innerHTML = empty('نشد: ' + esc(e.message)); b.disabled = false; }
    }
    else if (act === 'coach-book') { await api('/api/coach/books/' + id, { method: 'PATCH', body: { status: b.dataset.st } }); renderKeep(); }
    else if (act === 'coach-book-del') { if (confirm('این کتاب از فهرست حذف شود؟')) { await api('/api/coach/books/' + id, { method: 'DELETE' }); renderKeep(); } }
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
      const out = $('#finOut'); out.innerHTML = '<span class="m-spin"></span> مهراد دارد حساب‌هایت را بررسی می‌کند…'; b.disabled = true;
      try { const r = await api('/api/chat', { method: 'POST', body: { text: b.dataset.q } }); out.innerHTML = `<div class="m-b bot" style="max-width:100%">${esc(r.reply)}</div>`; } finally { b.disabled = false; }
    }
    else if (act === 'del') { if (confirm('حذف شود؟')) { await api('/api/events/' + id, { method: 'DELETE' }); closeSheet(); toast('حذف شد'); render(); } }
    else if (act === 'toggle') { const e = findEvent(id); const done = (e.fields || {}).status === 'done';
      await api('/api/events/' + id, { method: 'PATCH', body: { fields: { status: done ? 'open' : 'done' } } }); render(); }
    else if (act === 'say') say(b.dataset.for);
    else if (act === 'mic') mic(b.dataset.for);
    else if (act === 'photo') { S.photoFor = b.dataset.for; $('#photoIn').click(); }
    else if (act === 'theme') { applyTheme(b.dataset.val); $$('.seg [data-act=theme]').forEach(x => x.setAttribute('aria-pressed', x === b)); }
    else if (act === 'logout') { closeSheet(); logout(false); }
    else if (act === 'plan') {
      const out = $('#planOut'); out.innerHTML = '<span class="m-spin"></span> مهراد دارد برنامه می‌چیند…'; b.disabled = true;
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
    if (kind === 'coach-book') { await api('/api/coach/books', { method: 'POST', body: { title: v.title.trim() } }); toast('اضافه شد ✓'); return renderKeep(); }
    if (kind === 'task') await api('/api/events', { method: 'POST', body: { type: 'task', summary: v.title.trim(), fields: { status: 'open' } } });
    else if (kind === 'goal') await api('/api/events', { method: 'POST', body: { type: 'goal', summary: v.title.trim(), fields: { progress: 0, horizon: (v.horizon || '').trim() || undefined } } });
    else if (kind === 'money') await api('/api/events', { method: 'POST', body: { type: v.type, summary: (v.summary || '').trim() || (v.type === 'income' ? 'درآمد' : 'خرج'),
      amount: Number(v.amount), category: (v.category || '').trim() || undefined } });
    else if (kind === 'edit') {
      const body = { summary: v.summary.trim() }; if ('amount' in v) body.amount = v.amount === '' ? null : Number(v.amount); if ('category' in v) body.category = v.category.trim() || null;
      await api('/api/events/' + f.dataset.id, { method: 'PATCH', body }); closeSheet();
    }
    else if (kind === 'activity') {
      const body = { type: 'activity', summary: v.title.trim(), category: (v.category || '').trim() || undefined, status: v.status || 'done' };
      if (v.start) body.when = v.start;
      if (v.end) body.end = v.end; else if (v.minutes) body.minutes = Number(v.minutes);
      await api('/api/events', { method: 'POST', body });
    }
    else if (kind === 'habit') await api('/api/habits', { method: 'POST', body: { good: v.good.trim(), bad: (v.bad || '').trim() || undefined } });
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
