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
const S = { tab: store.get('mehrdad_tab') || 'today', mrange: 'month', lrange: 'week', priv: store.get('mehrdad_priv') === '1',
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
      const h = (d[k.k] || 0) / max * inner, w = bw * (0.76 / keys.length), x = i * bw + bw * 0.12 + j * w;
      if (h > 0) bars += `<rect x="${x.toFixed(1)}" y="${(top + inner - h).toFixed(1)}" width="${w.toFixed(1)}" height="${h.toFixed(1)}" rx="3" fill="${k.c}"/>`;
    });
    if (n <= 10 || i % Math.ceil(n / 10) === 0 || i === n - 1)
      lbl += `<text x="${(i * bw + bw / 2).toFixed(1)}" y="${H - 6}" text-anchor="middle" font-size="10" fill="var(--ink3)">${d.day}</text>`;
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
    <div><div class="m-t">${esc(t.summary)}</div>${due ? `<div class="muted small">موعد: ${esc(fa(due))}</div>` : ''}</div>
    <button class="x" data-act="edit" data-id="${t.id}" aria-label="ویرایش">✎</button><button class="x" data-act="del" data-id="${t.id}" aria-label="حذف">✕</button></div>`;
}

function composer(id, ph) {
  const mic = (window.MehrdadNative && MehrdadNative.startVoice) || window.SpeechRecognition || window.webkitSpeechRecognition;
  return `<div class="m-composer"><textarea id="${id}" rows="1" placeholder="${ph}" aria-label="پیام"></textarea>
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
      ${composer('sayToday', 'مثلاً: ۲۰۰ ت فروش فیلترشکن داشتم، ناهار برنج خوردم…')}
      <p class="muted small">هر چه بنویسی خودش در بخش درست ثبت می‌شود.</p></div>
    <div class="kpis">${kpi('وعدهٔ غذا', fa(c.meal || 0))}${kpi('قلیان/سیگار', fa(c.smoking || 0), c.smoking ? 'warn' : '')}${kpi('ورزش', fa(c.workout || 0), c.workout ? 'good' : '')}${kpi('کار باز', fa(open.length))}</div>
    <div class="card"><div class="row spread"><h2>برنامهٔ امروز</h2><span class="pill num">${fa(open.length)} باز</span></div>
      ${open.length ? open.map(taskRow).join('') : empty('کار بازی نیست. یکی اضافه کن یا به مهرداد بگو.')}
      <form class="row" data-form="task" style="flex-wrap:nowrap"><input type="text" name="title" placeholder="کار تازه…" required maxlength="200"><button class="btn primary" type="submit">افزودن</button></form></div>
    ${habitsCard(d.habits)}
    <div class="card"><div class="row spread"><h2>امروز چه گذشت</h2><span class="muted small">${fa((d.items || []).filter(i => !hidden(i.kind)).length)} مورد</span></div>${timeline(d.items || [], 'today')}</div>
  </section>`;
}

async function viewMoney() {
  const d = await api('/api/dashboard?range=' + S.mrange); S.cache.money = d;
  const f = d.finance;
  const money_items = (d.items || []).filter(i => i.kind === 'income' || i.kind === 'expense');
  return `<section class="pane">
    <div class="pane-title"><h1>حساب‌ها</h1>${seg('mrange', S.mrange)}</div>
    <div class="kpis">${kpi('درآمد', money(f.income), 'good')}${kpi('خرج', money(f.expense), f.expense > f.income ? 'crit' : '')}${kpi('خالص', (f.net < 0 ? '−' : '') + money(Math.abs(f.net)), f.net >= 0 ? 'good' : 'crit')}</div>
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
