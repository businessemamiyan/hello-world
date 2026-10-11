/* مهرداد — اپ وب (فارسی/RTL). داده فقط با توکن دستگاه از /api میاد؛ هیچ داده‌ای داخل خود فایل‌ها نیست. */
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
const S = { tab: store.get('mehrdad_tab') || 'today', mview: 'tx', pmonth: '', pid: '', gview: 'goals', mrange: 'month', lrange: 'week', priv: store.get('mehrdad_priv') === '1',
            cache: {}, busy: false, talk: false, talkSilent: 0, voiceIn: false,
            sview: store.get('mehrdad_sview') || 'today', cq: '', cst: '', cid: null };
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
    <div class="m-tl-b"><div>${esc(i.summary)}${i.uncertain ? ' <span class="pill warn" title="مهرداد مطمئن نیست">؟</span>' : ''}</div>
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

// ------------------------------------------------------------- صدا: خواندن جواب‌ها و گفتگوی صوتی
const bubble = (cls, text) => `<div class="m-b ${cls}"><span class="m-txt">${esc(text)}</span>${cls === 'bot' ? '<button class="m-spk" data-act="speak" aria-label="بخون">🔊</button>' : ''}</div>`;
function fillBot(el, text) {
  if (!el) return;
  el.classList.remove('typing'); el.removeAttribute('id');
  el.innerHTML = `<span class="m-txt">${esc(text)}</span><button class="m-spk" data-act="speak" aria-label="بخون">🔊</button>`;
}
let curAudio = null;
function stopSpeaking() {
  if (curAudio) { const a = curAudio; curAudio = null; try { a.pause(); a.onended && a.onended(); } catch (e) { /* ignore */ } }
}
// جواب را با صدای سرور می‌خواند (فارسی طبیعی، مستقل از صداهای گوشی)؛ وقتی پخش تمام شد resolve می‌شود
async function speakText(text) {
  stopSpeaking();
  const clean = String(text || '').trim(); if (!clean) return;
  try {
    const r = await fetch('/api/tts', { method: 'POST', headers: { 'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json' },
      body: JSON.stringify({ text: clean, voice: store.get('mehrdad_voice') || undefined }) });
    if (r.status === 401) { logout(true); return; }
    if (!r.ok) throw new Error('tts ' + r.status);
    const url = URL.createObjectURL(await r.blob());
    await new Promise((ok, bad) => {
      const a = new Audio(url); curAudio = a;
      a.onended = () => { URL.revokeObjectURL(url); ok(); };
      a.onerror = () => { URL.revokeObjectURL(url); bad(new Error('play')); };
      a.play().catch(bad);
    });
  } catch (e) {
    if (window.MehrdadNative && MehrdadNative.speakAvailable && MehrdadNative.speakAvailable()) MehrdadNative.speak(clean.slice(0, 600));
    else toast('صدا پخش نشد؛ اینترنت یا فیلترشکن رو چک کن');
  } finally { curAudio = null; }
}
const ttsAlways = () => store.get('mehrdad_tts') === '1';
const ttsBtnLabel = () => ttsAlways() ? '🔊 جواب‌ها صوتی' : '🔇 جواب‌ها متنی';
const talkBtnLabel = () => S.talk ? '⏹ قطع گفتگو' : '🗣️ گفتگوی صوتی';
function talkUi() { const b = $('#talkBtn'); if (b) { b.textContent = talkBtnLabel(); b.classList.toggle('danger', !!S.talk); } }
const TALK_STOP = /^(?:(?:ممنون|مرسی|باشه|ok)[\s،]*)?(?:تمام|تمومه|تمام شد|بس|بسه|بس کن|قطع|قطع کن|خداحافظ|خدافظ|خداحافظی|خدانگهدار|فعلا|فعلاً)[\s.!،؟]*$/i;
function talkListen() {
  if (!S.talk) return;
  try { MehrdadNative.startVoiceChat(); } catch (e) { talkStop('گفتگوی صوتی فقط داخل اپ اندروید کار می‌کنه'); }
}
function talkStart() {
  if (!(window.MehrdadNative && MehrdadNative.startVoiceChat)) return toast('گفتگوی صوتی با اپ اندروید کار می‌کنه؛ اینجا 🎤 رو بزن');
  if (S.tab !== 'chat') go('chat');
  S.talk = true; S.talkSilent = 0; talkUi(); talkListen();
}
function talkStop(msg) { S.talk = false; stopSpeaking(); talkUi(); if (msg) toast(msg); }
window.onVoiceChatCancel = () => { if (S.talk) talkStop('گفتگو قطع شد'); };
window.onVoiceChat = async text => {
  if (!S.talk) return;
  text = String(text || '').trim();
  if (!text) { if (++S.talkSilent >= 2) return talkStop('صدایی نشنیدم؛ گفتگو تموم شد. دوباره 🗣️ رو بزن.'); return talkListen(); }
  S.talkSilent = 0;
  if (TALK_STOP.test(text)) { talkStop('خداحافظ 👋'); return; }
  const reply = await chatTurn(text, true);
  if (S.talk) talkListen();
  return reply;
};
// یک نوبت چت با نمایش حباب‌ها (اگه روی صفحهٔ گفتگو باشیم) و اختیاری خواندن جواب
async function chatTurn(text, speak) {
  const list = $('#chatList');
  if (list) {
    const empt = $('.m-empty', list); if (empt) empt.remove();
    list.insertAdjacentHTML('beforeend', `${bubble('me', text)}<div class="m-b bot typing" id="typing"><span class="m-spin"></span></div>`);
    window.scrollTo(0, document.body.scrollHeight);
  }
  try {
    const r = await api('/api/chat', { method: 'POST', body: { text } });
    fillBot($('#typing'), r.reply); window.scrollTo(0, document.body.scrollHeight);
    if (speak) await speakText(r.reply);
    return r.reply;
  } catch (e) {
    if (e.message !== 'unauthorized') { toast('نشد: ' + e.message); const t = $('#typing'); if (t) { t.classList.remove('typing'); t.textContent = 'نتونستم به مغز برسم؛ دوباره امتحان کن.'; t.removeAttribute('id'); } if (S.talk) talkStop(); }
    return null;
  }
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
  const [d, pjs, phs] = await Promise.all([api('/api/dashboard?range=today'), api('/api/projects').catch(() => ({ projects: [] })), api('/api/phone/status').catch(() => null)]); S.cache.today = d;
  if (phs && phs.pending && phs.pending.length) setTimeout(() => { if (S.tab === 'today') render(); }, 12000);
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
      <p class="muted small">هر چی بنویسی خودش در بخش درست ثبت می‌شه.</p></div>
    ${phoneCard(phs)}
    ${projectsStrip(pjs.projects)}
    ${plannedLine(f)}
    ${groupKpis(d, 4)}
    ${timeBars(d)}
    <div class="card"><div class="row spread"><h2>برنامهٔ امروز</h2><span class="pill num">${fa(open.length)} باز</span></div>
      ${open.length ? open.map(taskRow).join('') : empty('کار بازی نیست. یکی اضافه کن یا به مهرداد بگو.')}
      <form class="row" data-form="task" style="flex-wrap:nowrap"><input type="text" name="title" placeholder="کار تازه…" required maxlength="200"><button class="btn primary" type="submit">افزودن</button></form></div>
    ${habitsCard(d.habits)}
    <div class="card"><div class="row spread"><h2>امروز چه گذشت</h2><span class="muted small">${fa((d.items || []).filter(i => !hidden(i.kind)).length)} مورد</span></div>${timeline(d.items || [], 'today')}</div>
  </section>`;
}

const mviewSeg = () => `<div class="seg" role="group" style="justify-self:start">
  <button data-act="mview" data-val="tx" aria-pressed="${S.mview === 'tx'}">تراکنش‌ها</button>
  <button data-act="mview" data-val="wealth" aria-pressed="${S.mview === 'wealth'}">دارایی و بدهی</button>
  <button data-act="mview" data-val="payroll" aria-pressed="${S.mview === 'payroll'}">فیش حقوقی</button></div>`;

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
    const pill = days === null ? '' : days < 0 ? `<span class="pill crit">${fa(-days)} روز گذشته</span>` : days <= 7 ? `<span class="pill warn">${days === 0 ? 'امروز' : fa(days) + ' روز دیگه'}</span>` : `<span class="pill">${fa(days)} روز دیگه</span>`;
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
      <p class="muted small">حساب‌ها، اقساط و درآمد/خرج واقعی‌ات رو کنار هم می‌بینه و راه‌حل می‌ده.</p>
      <div class="row"><button class="btn ai" data-act="ask-fin" data-q="وضعیت مالی‌ام رو کامل بررسی کن: حساب‌ها، اقساط، درآمد و خرج. مشکل‌ها و یک برنامهٔ مشخص برای پرداخت بدهی‌ها و پس‌انداز بده.">بررسی کامل</button>
      <button class="btn" data-act="ask-fin" data-q="این ماه کدوم خرج‌هام رو می‌تونم کم کنم تا اقساط رو راحت‌تر بدم؟">کجا خرج کم کنم؟</button></div><div id="finOut"></div></div>
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
      <label class="f"><span>مانده فعلی (اگه کمتره)</span><input type="number" name="remaining" inputmode="numeric" min="0"></label>
      <label class="f"><span>مبلغ هر قسط</span><input type="number" name="installment_amount" inputmode="numeric" min="0"></label>
      <label class="f"><span>تعداد کل اقساط</span><input type="number" name="installments_total" inputmode="numeric" min="1"></label>
      <label class="f"><span>روز سررسید در ماه (۱ تا ۳۱)</span><input type="number" name="due_day" inputmode="numeric" min="1" max="31"></label>
      <button class="btn primary" type="submit">افزودن</button></form></div>
    ${s.payoff.length ? `<div class="card"><h2>کی بدهی‌ها تمام می‌شه؟</h2>${s.payoff.map(p => `<div class="row spread"><span>${esc(p.title)}</span><span class="pill num">${fa(p.months_left)} ماه · ${esc(p.free_on)}</span></div>`).join('')}</div>` : ''}
    ${paid.length ? `<details class="card"><summary>تسویه‌شده‌ها (${fa(paid.length)})</summary>${paid.map(debtCard).join('')}</details>` : ''}
  </section>`;
}

const PAY_VARS = [['overtime', 'اضافه‌کاری عادی (ساعت)'], ['holiday_overtime', 'اضافه‌کاری تعطیلی (ساعت)'], ['leave', 'مرخصی حقوق‌دار (روز)'],
  ['unpaid_leave', 'غیبت / مرخصی بدون حقوق (روز)'], ['advance', 'مساعده (تومان)'], ['other_earn', 'سایر پرداختی (تومان)'], ['other_ded', 'سایر کسور (تومان)'],
  ['days_worked', 'روز کارکردِ کل ماه']];
const shiftM = (k, n) => { const [y, m] = k.split('-').map(Number); const i = y * 12 + (m - 1) + n; return `${Math.floor(i / 12)}-${String(i % 12 + 1).padStart(2, '0')}`; };
async function viewPayroll() {
  const s = await api('/api/payroll' + (S.pmonth ? '?month=' + S.pmonth : '')); S.cache.pay = s; S.pmonth = s.month;
  const L = s.labels, d = s.actual || s.estimate, st = s.settings, k = st.unit === 'rial' ? 10 : 1;
  const nav = `<div class="row spread"><button class="btn sm" data-act="pshift" data-d="-1" aria-label="ماه قبل">›</button><b>${esc(s.label)}</b>
    <button class="btn sm" data-act="pshift" data-d="1" aria-label="ماه بعد">‹</button></div>`;
  const row = (l, v, cls = '') => `<div class="row spread"><span>${l}</span><b class="num ${cls}">${money(v)}</b></div>`;
  const head = d ? `<div class="north"><span class="eyebrow">${s.actual ? 'فیش واقعی' : 'حقوق تخمینی'} · ${esc(s.label)}</span>
      <div class="fig"><strong class="num">${money(d.net)}</strong><span>تومان خالص پرداختی</span></div>
      <div class="meta"><span>جمع پرداختی <b class="num m-pos">${money(d.total_earn)}</b></span><span>جمع کسورات <b class="num m-neg">${money(d.total_ded)}</b></span></div>
      ${s.actual ? '' : `<div class="muted small" style="color:var(--hero-sub)">از روی فیش واقعی ${esc(s.template_month)} محاسبه شده؛ هر چی اضافه‌کاری/مرخصی بگویی دقیق‌تر می‌شه.</div>`}</div>`
    : `<div class="card gold"><h2>🧾 فیش حقوقی</h2><p class="muted small">یک بار فیش یکی از ماه‌ها رو پایین پر کن (یا عکسش رو در چت بفرست)؛ بعد حقوق ماه‌های بعد رو خودم حساب می‌کنم و اضافه‌کاری و مرخصی رو از حرف‌هات می‌گیرم.</p></div>`;
  const brk = d ? `<div class="card"><div class="row spread"><h2>پرداختی‌ها</h2><span class="pill gold">${s.actual ? 'واقعی' : 'تخمینی'}</span></div>
      ${L.earn.filter(([key]) => d.earn[key] || key === 'base').map(([key, l]) => row(esc(l), d.earn[key])).join('')}
      <div class="row spread" style="border-top:1px solid var(--line);padding-top:6px"><b>جمع پرداختی</b><b class="num m-pos">${money(d.total_earn)}</b></div>
      <h2 style="margin-top:10px">کسورات</h2>${L.ded.filter(([key]) => d.ded[key]).map(([key, l]) => row(esc(l), d.ded[key], 'm-neg')).join('') || empty('کسوری نیست.')}
      <div class="row spread" style="border-top:1px solid var(--line);padding-top:6px"><b>جمع کسورات</b><b class="num m-neg">${money(d.total_ded)}</b></div>
      <div class="row spread"><b>خالص پرداختی</b><b class="num">${money(d.net)}</b></div>
      ${s.actual && (s.actual.mismatch || []).length ? '<div class="issue warn"><span class="tag">چک کن</span><div>جمع‌های واردشده با مجموع اقلام نمی‌خونه؛ شاید قلمی جا افتاده یا عددی اشتباه‌ست.</div></div>' : ''}
      <h2 style="margin-top:10px">کارکرد</h2>
      <div class="kpis m-k3">${kpi('روز کارکرد', fa(d.work.days_worked || 0))}${kpi('اضافه‌کاری عادی', fa(d.work.ot_normal_h || 0) + ' س')}${kpi('اضافه‌کاری تعطیلی', fa(d.work.ot_holiday_h || 0) + ' س')}
        ${kpi('مرخصی', fa(d.work.leave_days || 0) + ' روز')}${kpi('ساعت کارکرد', fa(d.work.work_hours || 0))}</div>
      ${!s.actual && s.estimate ? `<p class="muted small">فرض‌های یادگرفته‌شده از فیش: نرخ بیمه ${fa((s.estimate.assumptions.insurance_rate * 100).toFixed(1))}٪ · نرخ مالیات ${fa((s.estimate.assumptions.tax_rate * 100).toFixed(1))}٪ · ضریب اضافه‌کاری ${fa(s.estimate.assumptions.factor_ot_normal)}. مالیات رو شرکت می‌ده (مزایا ۳) پس روی خالص اثری نداره.</p>` : ''}
      ${s.actual ? `<div class="row"><button class="btn sm danger" data-act="pay-del">حذف فیش این ماه</button></div>` : ''}</div>` : '';
  const quick = `<div class="card ai"><div class="row spread"><h2>اضافه‌کاری، مرخصی، مساعده</h2><span class="pill ai">${esc(s.label)}</span></div>
      <p class="muted small">یا همین رو در چت به مهرداد بگو: «امروز ۲ ساعت اضافه‌کاری کردم». جمع این ماه: عادی ${fa(s.vars.ot_normal_h || 0)} س · تعطیلی ${fa(s.vars.ot_holiday_h || 0)} س · مرخصی ${fa(s.vars.leave_days || 0)} روز · غیبت ${fa(s.vars.unpaid_days || 0)} روز${s.vars.advance ? ' · مساعده ' + money(s.vars.advance) : ''}.</p>
      <form class="form" data-form="payvar"><label class="f"><span>چه چیزی؟</span><select name="op">${PAY_VARS.map(([v, l]) => `<option value="${v}">${l}</option>`).join('')}</select></label>
        <label class="f"><span>مقدار</span><input type="text" name="value" inputmode="decimal" required></label>
        <label class="f"><span>نحوه</span><select name="mode"><option value="add">اضافه کن به جمع</option><option value="set">جمع کل ماه اینه</option></select></label>
        <button class="btn primary" type="submit">ثبت</button></form></div>`;
  const src = s.actual || s.template || { earn: {}, ded: {}, work: {} };
  const fld = (grp, key, label) => `<label class="f"><span>${esc(label)}</span><input type="text" inputmode="decimal" name="${grp}_${key}" value="${(src[grp] || {})[key] ? (grp === 'work' ? src[grp][key] : Math.round(src[grp][key] * k)) : ''}"></label>`;
  const form = `<div class="card"><div class="row spread"><h2>${s.actual ? 'ویرایش فیش واقعی' : 'ثبت فیش واقعی (نمونه)'}</h2><span class="muted small">ماه ${esc(s.label)}</span></div>
      <p class="muted small">${s.actual ? '' : 'یک ماه رو کامل پر کن؛ ماه‌های بعد از روی اون حساب می‌شن. هر ماه که فیش واقعی اومد دوباره پرش کن تا دقیق‌تر بشه. '}اقلام خالی = صفر.</p>
      <form class="form" data-form="payslip"><label class="f"><span>ماه فیش (مثل ۱۴۰۵-۰۷)</span><input type="text" name="month" value="${esc(fa(s.month))}" required dir="ltr"></label>
        <label class="f"><span>واحد مبلغ‌ها</span><select name="unit"><option value="toman" ${st.unit === 'toman' ? 'selected' : ''}>تومان</option><option value="rial" ${st.unit === 'rial' ? 'selected' : ''}>ریال</option></select></label>
        <div class="full eyebrow">پرداختی‌ها</div>${L.earn.map(([key, l]) => fld('earn', key, l)).join('')}
        <div class="full eyebrow">کسورات</div>${L.ded.map(([key, l]) => fld('ded', key, l)).join('')}
        <div class="full eyebrow">کارکردها</div>${L.work.map(([key, l]) => fld('work', key, l)).join('')}
        <div class="full eyebrow">جمع‌های روی فیش (اختیاری؛ برای کنترل اشتباه)</div>
        <label class="f"><span>جمع پرداختی</span><input type="text" inputmode="decimal" name="tot_total_earn"></label>
        <label class="f"><span>جمع کسورات</span><input type="text" inputmode="decimal" name="tot_total_ded"></label>
        <label class="f"><span>خالص پرداختی</span><input type="text" inputmode="decimal" name="tot_net"></label>
        <button class="btn primary" type="submit">ذخیره فیش</button></form></div>`;
  const hist = `<div class="card"><h2>ماه‌ها</h2>${s.months.map(m => `<div class="row spread"><button class="btn sm" data-act="pmonth" data-val="${m.month}">${esc(m.label)}</button>
      <span><span class="pill ${m.actual ? 'good' : ''}">${m.actual ? 'واقعی' : 'تخمینی'}</span> <b class="num">${money(m.net)}</b></span></div>`).join('') || empty('هنوز فیشی نیست.')}</div>`;
  const ins = new Set(st.insurable);
  const sett = `<details class="card"><summary>تنظیمات محاسبه</summary><div class="stack6 small" style="margin-top:8px">
      <label class="f"><span>مبنای روز</span><select data-act="pay-setting" data-key="day_basis"><option value="auto" ${st.day_basis === 'auto' ? 'selected' : ''}>خودکار (از روی فیش نمونه تشخیص می‌ده)</option>
        <option value="month" ${st.day_basis === 'month' ? 'selected' : ''}>ماه کامل = حقوق کامل (۳۰ یا ۳۱ روز فرقی نداره)</option>
        <option value="30cap" ${st.day_basis === '30cap' ? 'selected' : ''}>هر ماه ۳۰ روز (حتی ماه ۳۱ روزه)</option>
        <option value="30" ${st.day_basis === '30' ? 'selected' : ''}>روزمزد = یک‌سی‌ام (ماه ۳۱ روزه ۳۱ روز می‌شه)</option></select></label>
      <div class="muted">اقلام مشمول بیمه:</div>
      <div class="row">${L.earn.filter(([key]) => key !== 'benefit3').map(([key, l]) => `<label class="row" style="gap:4px"><input type="checkbox" data-act="pay-ins" value="${key}" ${ins.has(key) ? 'checked' : ''}> ${esc(l)}</label>`).join('')}</div>
      <div class="muted">محاسبه‌ها همه تخمین‌اند؛ هر ماه که فیش واقعی رو ثبت کنی ضریب‌ها از همون دوباره یاد گرفته می‌شه.</div></div></details>`;
  return `<section class="pane">${mviewSeg()}<div class="pane-title"><h1>فیش حقوقی</h1></div>${nav}${head}${quick}${brk}${form}${hist}${sett}</section>`;
}

async function viewMoney() {
  if (S.mview === 'wealth') return viewWealth();
  if (S.mview === 'payroll') return viewPayroll();
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
    : `<div class="card"><div class="m-lock">🔒 <span>بخش‌های خصوصی پنهونن. با دکمهٔ 🔒 بالا نشونشون بده.</span></div></div>`;
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
  <button data-act="gview" data-val="profile" aria-pressed="${S.gview === 'profile'}">پروفایل من</button>
  <button data-act="gview" data-val="projects" aria-pressed="${S.gview === 'projects'}">پروژه‌ها</button></div>`;

async function viewHabits() {
  const [p, d] = await Promise.all([api('/api/profile'), api('/api/dashboard?range=today')]);
  const bad = p.habits.filter(h => h.kind === 'bad'), good = p.habits.filter(h => h.kind !== 'bad');
  const hrow = h => `<div class="m-tl" style="grid-template-columns:1fr auto auto"><div class="m-tl-b"><div>${esc(h.name)} <span class="pill ${h.kind === 'bad' ? 'warn' : 'good'}">${h.kind === 'bad' ? 'بد' : 'خوب'}</span></div>
      <div class="muted small">۷ روز: ${h.minutes_7d ? dur(h.minutes_7d) : fa(h.count_7d) + ' بار'} در ${fa(h.days_7d)} روز · ۳۰ روز: ${h.minutes_30d ? dur(h.minutes_30d) : '—'}</div></div>
      <span></span>${h.kind === 'bad' ? `<button class="btn sm" data-act="track-habit" data-name="${esc(h.name)}">پیگیری کن</button>` : '<span></span>'}</div>`;
  return `<section class="pane">${gviewSeg()}
    <div class="pane-title"><h1>عادت‌ها و روتین</h1></div>
    <div class="card"><div class="row spread"><h2>🧭 روتین‌های منظم</h2><span class="pill num">${fa(p.routines.length)}</span></div>
      <p class="muted small">مهرداد از روی چیزهایی که می‌گی تشخیص می‌ده (مثلاً «رفتم سر کار ایساتیس») و خودش روتین می‌سازه.</p>
      ${p.routines.length ? p.routines.map(r => `<div class="m-tl" style="grid-template-columns:1fr auto"><div class="m-tl-b"><div>${esc(r.name)}</div>
        <div class="muted small">${fa(r.per_week)} روز در هفته · معمولاً <span class="num">${esc(r.avg_start)}${r.avg_end ? '–' + esc(r.avg_end) : ''}</span>${r.avg_minutes ? ' · ' + dur(r.avg_minutes) : ''}</div></div>
        <span class="pill num">${fa(r.days)} روز</span></div>`).join('') : empty('هنوز روتینی تشخیص داده نشده؛ چند روز روزت رو تعریف کن.')}</div>
    <div class="card"><div class="row spread"><h2>🔍 عادت‌هایی که دیده‌ام</h2><span class="pill num">${fa(p.habits.length)}</span></div>
      <p class="muted small">حتی اگه اسمش رو عادت نذاشته باشی (اسکرول اینستاگرام، قلیان، …)؛ این‌ها در هدف‌گذاری وزن دارن.</p>
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
      <p class="muted small">هر چی بیشتر بدونم، هدف‌ها و برنامه‌ها دقیق‌تر می‌شن. ${c.missing.length ? 'خالی: ' + esc(c.missing.slice(0, 4).join('، ')) : 'همهٔ بخش‌ها پره 👏'}</p>
      <div class="row"><button class="btn ai" data-act="say-onboard">شروع مصاحبه در چت</button><span class="muted small">یا در تلگرام: /onboard</span></div></div>
    <div class="card gold"><div class="row spread"><h2>💌 لینک برای همسرت</h2><span class="pill gold">فقط چند تا سؤال ساده</span></div>
      <p class="muted small">یه لینک امن فقط برای چند تا سؤال؛ همسرت هیچ‌چیز از اطلاعات تو رو نمی‌بینه. جواب‌هاش همین‌جا توی پروفایلت می‌آد و هر کدوم رو خواستی می‌تونی پاک کنی.</p>
      <div class="row"><button class="btn primary" data-act="make-invite">ساخت لینک تازه</button></div><div id="inviteOut"></div>
      ${inv.invites.length ? `<div class="stack6" style="margin-top:6px">${inv.invites.map(invRow).join('')}</div>` : ''}</div>
    ${secs.filter(k => by[k]).map(k => `<div class="card"><div class="row spread"><h2>${esc(k)}</h2><span class="pill num">${fa(by[k].length)}</span></div>${by[k].slice().reverse().map(fact).join('')}</div>`).join('')
      || `<div class="card">${empty('هنوز چیزی دربارهٔ تو ثبت نشده. شروع کن: «من … هستم و …» یا مصاحبه رو بزن.')}</div>`}
  </section>`;
}

const mdLite = s => esc(s).replace(/\[([^\]\n]+)\]\([^)\n]*\)/g, '$1').replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>').replace(/`([^`\n]+)`/g, '<code>$1</code>').replace(/^#{1,4}\s*(.*)$/gm, '<b>$1</b>');
const isoDay = ts => new Date(ts * 1000).toISOString().slice(0, 10);
function projectsStrip(ps) {
  if (!ps || !ps.length) return '';
  return `<div class="card"><div class="row spread"><h2>🗂 پروژه‌هام</h2><button class="btn sm" data-act="goto-projects">همه</button></div>
    ${ps.map(p => `<button class="m-pj" data-act="proj-open" data-id="${esc(p.id)}" style="border-inline-start-color:${esc(p.color)}"><span class="r1"><b>${esc(p.icon)} ${esc(p.name)}</b><span class="row" style="gap:4px;flex-wrap:wrap"><span class="pill">${esc(p.status)}</span>${p.open_count ? `<span class="pill gold num">${fa(p.open_count)} کار باز</span>` : ''}</span></span><span class="r2">${esc(p.summary.slice(0, 90))}${p.summary.length > 90 ? '…' : ''}</span></button>`).join('')}</div>`;
}
async function viewProjects() {
  if (S.pid) return viewProjectDetail();
  const r = await api('/api/projects'); S.cache.projects = r.projects;
  const card = p => `<div class="card m-goal" style="border-inline-start:4px solid ${esc(p.color)}"><div class="row spread"><b>${esc(p.icon)} ${esc(p.name)}</b><span class="pill">${esc(p.status)}</span></div>
      ${p.subtitle ? `<div class="muted small">${esc(p.subtitle)}</div>` : ''}<div class="small">${esc(p.summary)}</div>
      ${(p.kpis || []).length ? `<div class="kpis m-k3">${p.kpis.slice(0, 3).map(([l, v]) => kpi(esc(l), esc(v))).join('')}</div>` : ''}
      ${p.last_note ? `<div class="muted small">آخرین: ${esc(p.last_note.text.slice(0, 120))}</div>` : ''}
      <div class="row spread"><span class="muted small num">${fa(p.open_count)} کار باز · ${fa(p.docs_count)} بخش مستند</span><button class="btn sm primary" data-act="proj-open" data-id="${esc(p.id)}">باز کن</button></div></div>`;
  return `<section class="pane">${gviewSeg()}<div class="pane-title"><h1>پروژه‌ها</h1></div>
    <p class="muted small">مهرداد از این پروژه‌ها خبر داره. هر پیشرفت، مشکل یا کار تازه‌ای رو که تو چت بگی خودش همین‌جا ثبت می‌کنه.</p>
    <div class="stack">${r.projects.length ? r.projects.map(card).join('') : `<div class="card">${empty('هنوز پروژه‌ای نیست.')}</div>`}</div>
    <form class="row" data-form="proj-new" style="flex-wrap:nowrap"><input type="text" name="name" placeholder="پروژهٔ تازه…" required maxlength="80"><button class="btn" type="submit">افزودن</button></form></section>`;
}
async function viewProjectDetail() {
  let d;
  try { d = await api('/api/projects/' + encodeURIComponent(S.pid)); } catch (e) { S.pid = ''; throw e; }
  S.cache.pdetail = d;
  const open = d.tasks.filter(t => !t.done), done = d.tasks.filter(t => t.done);
  const trow = t => `<div class="m-task ${t.done ? 'done' : ''}"><button class="m-check" data-act="proj-toggle" data-id="${t.id}" data-done="${t.done ? 0 : 1}" aria-label="انجام شد">✓</button>
      <div><div class="m-t">${esc(t.text)}</div></div><button class="x" data-act="proj-del" data-id="${t.id}" aria-label="حذف">✕</button><span></span></div>`;
  const STATUSES = ['فعال', 'در انتظار', 'متوقف', 'تمام‌شده'];
  const sel = STATUSES.includes(d.status) ? STATUSES : [d.status, ...STATUSES];
  return `<section class="pane"><div class="row spread"><button class="btn sm" data-act="proj-back">‹ همهٔ پروژه‌ها</button>
      <select data-act="proj-status" data-id="${esc(d.id)}" aria-label="وضعیت">${sel.map(s => `<option ${s === d.status ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></div>
    <div class="north" style="border-inline-start:4px solid ${esc(d.color)}"><span class="eyebrow">${esc(d.subtitle || 'پروژه')}</span>
      <div class="fig"><strong style="font-size:1.4rem">${esc(d.icon)} ${esc(d.name)}</strong></div>
      <div style="color:var(--hero-sub);line-height:1.8">${esc(d.summary)}</div></div>
    ${(d.kpis || []).length ? `<div class="kpis">${d.kpis.map(([l, v]) => kpi(esc(l), esc(v))).join('')}</div>` : ''}
    <div class="card"><div class="row spread"><h2>✅ کارهای باز</h2><span class="pill num">${fa(open.length)}</span></div>
      ${open.length ? open.map(trow).join('') : empty('کار بازی نیست.')}
      <form class="form" data-form="proj-item"><label class="f full"><span>کار تازه یا یادداشت پیشرفت</span><input type="text" name="text" required maxlength="500" placeholder="مثلاً: ایندکس‌های دیتابیس اجرا شد"></label>
        <label class="f"><span>نوع</span><select name="kind"><option value="task">کار باز</option><option value="note">یادداشت پیشرفت</option></select></label>
        <button class="btn primary" type="submit">افزودن</button></form>
      ${done.length ? `<details style="margin-top:8px"><summary>انجام‌شده‌ها (${fa(done.length)})</summary>${done.map(trow).join('')}</details>` : ''}</div>
    <div class="card"><div class="row spread"><h2>📝 یادداشت‌ها و پیشرفت</h2><span class="pill num">${fa(d.notes.length)}</span></div>
      <p class="muted small">یا همین‌ها رو تو چت به مهرداد بگو؛ خودش می‌نویسه.</p>
      ${d.notes.length ? d.notes.slice(0, 40).map(n => `<div class="m-tl" style="grid-template-columns:1fr auto"><div class="m-tl-b"><div>${esc(n.text)}</div><div class="muted small num">${esc(jdate(isoDay(n.ts)))}${n.source === 'import' ? ' · از سند اولیه' : ''}</div></div><button class="x" data-act="proj-del" data-id="${n.id}" aria-label="حذف">✕</button></div>`).join('') : empty('هنوز یادداشتی نیست.')}</div>
    ${d.docs.length ? `<div class="card"><div class="row spread"><h2>📚 مستندات کامل</h2><span class="pill num">${fa(d.docs.length)} بخش</span></div>
      <p class="muted small">مهرداد این مستندات رو هم می‌خونه و وقتی ازش بپرسی (مثلاً «باگ‌های لعاب‌زنی چی بود؟») جواب می‌ده.</p>
      ${d.docs.map(x => `<details data-doc="${x.id}"><summary>${esc(x.section)}</summary><div class="c-body small" id="doc${x.id}" dir="auto"><span class="muted">در حال باز کردن…</span></div></details>`).join('')}</div>` : ''}</section>`;
}

async function viewGoals() {
  if (S.gview === 'habits') return viewHabits();
  if (S.gview === 'profile') return viewProfile();
  if (S.gview === 'projects') return viewProjects();
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
      <p class="muted small">مهرداد بر پایهٔ پروفایل، روتین‌ها، عادت‌ها و مالی‌ات هدف پیشنهاد می‌ده؛ هر کدوم رو خودت تأیید می‌کنی.</p>
      <div class="row"><button class="btn primary" data-act="suggest-goals">پیشنهاد هدف</button></div><div id="goalSuggest"></div></div>
    <div class="card ai"><div class="row spread"><h2>برنامه‌ریزی با مهرداد</h2><span class="pill ai">مربی</span></div>
      <p class="muted small">بر اساس هدف‌ها و کارهای بازت، برنامهٔ هفته رو می‌چینه.</p>
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
  const msgs = r.messages.map(m => bubble(m.role === 'user' ? 'me' : 'bot', m.text)).join('');
  return `<section class="pane"><div class="pane-title"><h1>گفتگو با مهرداد</h1>
      <div class="row"><button class="btn sm" id="ttsBtn" data-act="tts-toggle">${ttsBtnLabel()}</button><button class="btn sm primary${S.talk ? ' danger' : ''}" id="talkBtn" data-act="talk-toggle">${talkBtnLabel()}</button></div></div>
    <div class="m-chatwrap"><div class="m-chat" id="chatList">${msgs || empty('هنوز چیزی نگفتی.')}</div></div>
    <div class="m-composer-fixed">${composer('sayChat', 'بنویس یا با 🎤 بگو…')}</div></section>`;
}

function eveCard(c) {
  const qs = c.evening_questions || [], ans = c.answers || {};
  return `<div class="card"><div class="row spread"><h2>🌙 مرور شبانه</h2><span class="pill ai">روز رو ببند</span></div>
    ${qs.map((q, i) => { const a = ans['e' + i]; return `<div class="c-q" style="padding:8px 0;border-bottom:1px solid var(--line)"><div class="c-id">${esc(q)}</div>${a ? `<div class="m-b me" style="max-width:100%;margin-top:6px">${esc(a.text)}</div><div class="m-b bot" style="max-width:100%;margin-top:6px">${esc(a.reply)}</div>`
      : `<textarea id="ce${i}" rows="2" placeholder="جوابت…"></textarea><div class="row"><button class="btn sm primary" data-act="coach-answer" data-kind="e" data-i="${i}">ثبت</button></div>`}</div>`; }).join('')}</div>`;
}
const BOOK_ST = { suggested: 'پیشنهادی', reading: 'در حال مطالعه', done: 'تمام شد' };
async function viewCoach() {
  const c = await api('/api/coach'); S.cache.coach = c;
  const st = c.stats, p = c.plan, done = c.done || {};
  const head = `<div class="pane-title"><h1>مربی</h1><span class="row" style="gap:6px"><span class="pill gold num">🔥 ${fa(st.streak)} روز</span><span class="pill num">سطح ${fa(st.level)}</span></span></div>`;
  if (c.generating) {
    setTimeout(() => { if (S.tab === 'coach') render(); }, 3000);
    return `<section class="pane">${head}<div class="card ai"><h2><span class="m-spin"></span> مربی داره برنامهٔ امروزت رو می‌چینه…</h2><p class="muted small">معمولاً ۳۰ تا ۶۰ ثانیه؛ از روی چیزهایی که دربارهٔ تو می‌دونه.</p></div></section>`;
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
      <p class="muted small">هر موضوعی که می‌خوای (فروش، تمرکز، مدیریت پول، زبان…) برات درس مستقل و تمرین می‌ده.</p>
      <div class="row" style="flex-wrap:nowrap"><input type="text" id="teachTopic" placeholder="مثلاً: چطور فروش فیلترشکن رو بالا ببرم؟" maxlength="300"><button class="btn primary" data-act="coach-teach">یاد بده</button></div><div id="teachOut"></div></div>
    <div class="stack">${books.length ? books.map(bookCard).join('') : `<div class="card">${empty('هنوز کتابی نیست. پیشنهاد بگیر یا خودت اضافه کن.')}</div>`}</div>
    <div class="row"><button class="btn ai" data-act="coach-rec">پیشنهاد کتاب برای من</button></div><div id="recOut"></div>
    <form class="row" data-form="coach-book" style="flex-wrap:nowrap"><input type="text" name="title" placeholder="اسم کتابی که می‌خوای یاد بگیری…" required maxlength="120"><button class="btn" type="submit">افزودن</button></form>`;
  if (!p) return `<section class="pane">${head}<div class="card ai"><h2>برنامهٔ امروز هنوز ساخته نشده</h2>
      <p class="muted small">مربی با توجه به شناختی که از تو داره: تمرکز روز، روتین ساعت‌بندی‌شده، یک درس، یک چالش، چند سؤال و راه تبدیل عادت‌های بد رو می‌سازه. هر روز ساعت ۷ صبح هم خودش می‌سازه و در تلگرام می‌فرسته.</p>
      ${c.error ? `<p class="small" style="color:var(--warn)">دفعهٔ قبل نشد: ${esc(c.error)}</p>` : ''}
      <div class="row"><button class="btn primary" data-act="coach-gen">ساخت برنامهٔ امروز</button></div></div>${library}</section>`;
  const t = st.today, pct = t.total ? Math.round(t.done / t.total * 100) : 0;
  const qs = (p.questions || []).map((q, i) => { const a = (c.answers || {})[String(i)];
    return `<div class="c-q" style="padding:8px 0;border-bottom:1px solid var(--line)"><div class="c-id">${esc(q)}</div>${a ? `<div class="m-b me" style="max-width:100%;margin-top:6px">${esc(a.text)}</div><div class="m-b bot" style="max-width:100%;margin-top:6px">${esc(a.reply)}</div>`
      : `<textarea id="cq${i}" rows="2" placeholder="جوابت رو بنویس…"></textarea><div class="row"><button class="btn sm primary" data-act="coach-answer" data-i="${i}">ثبت جواب</button></div>`}</div>`; }).join('');
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
    ${qs ? `<div class="card"><div class="row spread"><h2>❓ مربی از تو می‌پرسه</h2><span class="pill ai">جواب‌ها ثبت می‌شن</span></div>${qs}</div>` : ''}
    ${eveCard(c)}
    ${swaps ? `<div class="card"><div class="row spread"><h2>🔁 عادت بد ← عادت خوب</h2></div><p class="muted small">حذف نه؛ جایگزین. هر کدوم رو بزن تا هر شب بپرسم چطور پیش رفتی.</p>${swaps}</div>` : ''}
    ${p.book ? `<div class="card"><div class="row spread"><h2>📚 کتاب پیشنهادی</h2></div><div class="c-id">${esc(p.book.title)}${p.book.author ? ' — ' + esc(p.book.author) : ''}</div>${p.book.why ? `<div class="small muted">${esc(p.book.why)}</div>` : ''}
      <div class="row"><button class="btn sm primary" data-act="coach-addbook" data-title="${esc(p.book.title)}" data-author="${esc(p.book.author || '')}">اضافه به کتاب‌هام و شروع آموزش</button></div></div>` : ''}
    ${p.note ? `<div class="card"><div class="c-id">${esc(p.note)}</div></div>` : ''}
    ${library}
    <div class="row"><button class="btn sm" data-act="coach-gen" data-force="1">ساخت دوبارهٔ برنامهٔ امروز</button></div>
  </section>`;
}

// ------------------------------------------------------------- فروش و پیگیری (CRM)
const CRM_ST = { lead: 'سرنخ', prospect: 'در حال مذاکره', customer: 'مشتری', lost: 'از دست رفته', inactive: 'غیرفعال' };
const CRM_STAGE = { lead: 'سرنخ', contacted: 'تماس گرفته شد', proposal: 'قیمت دادم', negotiation: 'مذاکره', won: 'فروش شد ✅', lost: 'از دست رفت' };
const CRM_OPEN = ['lead', 'contacted', 'proposal', 'negotiation'];
const CRM_CH = { call: '📞 تماس', sms: '✉️ پیامک', visit: '🤝 دیدار', telegram: 'تلگرام', whatsapp: 'واتس‌اپ', email: 'ایمیل', other: 'سایر' };
const CRM_EV = { note: '📝', stage: '📈', deal: '💼', sale: '💰', payment: '💵', call: '📞', sms: '✉️', followup: '✅' };
const crmMoney = n => { n = Number(n) || 0; return n >= 1e9 ? fa((n / 1e9).toFixed(2).replace(/\.?0+$/, '')) + ' میلیارد' : n >= 1e6 ? fa((n / 1e6).toFixed(1).replace(/\.0$/, '')) + ' میلیون' : money(n); };
const opts = (obj, cur) => Object.entries(obj).map(([k, v]) => `<option value="${k}"${k === cur ? ' selected' : ''}>${v}</option>`).join('');
const crmSeg = () => `<div class="seg" role="group" style="justify-self:start">${[['today', 'پیگیری‌ها'], ['customers', 'مشتری‌ها'], ['pipeline', 'معامله‌ها']].map(([k, v]) =>
  `<button data-act="crm-view" data-val="${k}" aria-pressed="${S.sview === k}">${v}</button>`).join('')}</div>`;

async function viewCrm() {
  const d = await api('/api/crm'); S.cache.crm = d;
  $('#subtitle').textContent = d.today_jalali;
  if (S.sview === 'customers') return viewCrmCustomers(d);
  if (S.sview === 'pipeline') return viewCrmPipeline(d);
  return viewCrmToday(d);
}

function crmFuRow(f, late) {
  return `<div class="card m-fu"><div class="row spread"><button class="link" data-act="crm-open" data-id="${f.customer_id}">${esc(f.customer)}</button>
      ${late ? `<span class="pill crit">${fa(f.days_late)} روز عقبه</span>` : `<span class="pill">${esc(jdate(f.due))}</span>`}</div>
    ${f.note ? `<div class="small">${esc(f.note)}</div>` : ''}${f.channel ? `<div class="muted small">${CRM_CH[f.channel]}</div>` : ''}
    <div class="row"><button class="btn sm primary" data-act="crm-fu-done" data-id="${f.id}">✅ انجام شد</button><button class="btn sm" data-act="crm-fu-tom" data-id="${f.id}">⏭ فردا</button>
      ${f.phone ? `<button class="btn sm" data-act="crm-call" data-id="${f.customer_id}">📞 زنگ بزن</button><button class="btn sm" data-act="crm-sms" data-id="${f.customer_id}">✉️ پیامک</button>` : ''}</div></div>`;
}

function viewCrmToday(d) {
  const f = d.followups, now = f.overdue.length + f.today.length;
  return `<section class="pane">${crmSeg()}
    <div class="north"><span class="eyebrow">فروش · ${esc(d.today_jalali)}</span>
      <div class="fig"><strong class="num">${fa(now)}</strong><span>پیگیری برای امروز${f.overdue.length ? ` (${fa(f.overdue.length)} تا عقب‌افتاده)` : ''}</span></div>
      <div class="meta"><span>معامله باز <b class="num">${fa(d.open_deals)}</b> · ${crmMoney(d.open_value)} تومان</span><span>فروش این ماه <b class="num m-pos">${crmMoney(d.won_month.value)}</b></span></div></div>
    <div class="card ai"><h2>🗣️ بگو، خودش ثبت می‌کنه</h2><p class="muted small">مثلاً «با آقای کریمی برای پنل ۱۲۰ میلیون صحبت کردم، سه‌شنبه بهش زنگ بزنم» یا «فروش به رضا ۵ میلیون شد، پولشم گرفتم».</p>
      ${composer('sayCrm', 'بنویس یا با 🎤 بگو…')}</div>
    ${f.overdue.length ? `<h2>⏰ عقب‌افتاده</h2><div class="stack">${f.overdue.map(x => crmFuRow(x, true)).join('')}</div>` : ''}
    <h2>📞 امروز</h2><div class="stack">${f.today.length ? f.today.map(x => crmFuRow(x, false)).join('') : `<div class="card">${empty('برای امروز پیگیری نداری 🎉')}</div>`}</div>
    ${f.upcoming.length ? `<h2>📅 ۷ روز آینده</h2><div class="stack">${f.upcoming.map(x => crmFuRow(x, false)).join('')}</div>` : ''}
    ${d.stale.length ? `<div class="card"><h2>⚠️ معامله‌هایی که پیگیری ندارن</h2><p class="muted small">بیشتر از ${fa(7)} روز دست بهشون نخورده و هیچ پیگیری هم نذاشتی:</p>
      ${d.stale.slice(0, 6).map(x => `<div class="row spread small"><button class="link" data-act="crm-open" data-id="${x.customer_id}">${esc(x.customer)}</button><span>${esc(x.title)} · ${crmMoney(x.value)}</span></div>`).join('')}</div>` : ''}
  </section>`;
}

const crmCustCard = c => `<div class="card m-cust"><div class="row spread"><button class="link" data-act="crm-open" data-id="${c.id}">${esc(c.name)}</button><span class="pill ${c.status === 'customer' ? 'good' : c.status === 'lost' ? 'crit' : c.status === 'prospect' ? 'gold' : ''}">${CRM_ST[c.status]}</span></div>
  ${c.company ? `<div class="muted small">${esc(c.company)}</div>` : ''}
  <div class="row small muted">${c.phone ? `<span class="num" dir="ltr">${esc(c.phone)}</span>` : ''}${c.open_deals ? `<span>💼 ${fa(c.open_deals)} معامله · ${crmMoney(c.open_value)}</span>` : ''}${c.next_due ? `<span>⏰ ${esc(jdate(c.next_due))}</span>` : ''}</div></div>`;

async function viewCrmCustomers(d) {
  const r = await api('/api/crm/customers?q=' + encodeURIComponent(S.cq || '') + (S.cst ? '&status=' + S.cst : ''));
  return `<section class="pane">${crmSeg()}
    <div class="pane-title"><h1>مشتری‌ها و سرنخ‌ها</h1><span class="muted small">${fa(d.customers)} نفر</span></div>
    <div class="row" style="flex-wrap:nowrap"><input type="text" id="crmQ" data-act="crm-q" placeholder="جست‌وجو (اسم، شرکت، شماره)" value="${esc(S.cq || '')}">
      <select data-act="crm-st-filter" style="max-width:130px"><option value="">همه</option>${opts(CRM_ST, S.cst || '')}</select></div>
    <div id="crmList" class="stack">${r.customers.length ? r.customers.map(crmCustCard).join('') : `<div class="card">${empty('هنوز مشتری یا سرنخی نیست؛ پایین اضافه کن یا توی چت بگو.')}</div>`}</div>
    <div class="card"><h2>➕ مشتری یا سرنخ تازه</h2><form class="form" data-form="crm-cust">
      <label class="f full"><span>اسم</span><input type="text" name="name" required maxlength="80" placeholder="مثلاً آقای کریمی"></label>
      <label class="f"><span>شرکت</span><input type="text" name="company" maxlength="80"></label>
      <label class="f"><span>شماره</span><input type="text" name="phone" maxlength="30" dir="ltr" placeholder="خالی بذاری از مخاطبین گوشی برمی‌دارم"></label>
      <label class="f"><span>وضعیت</span><select name="status">${opts(CRM_ST, 'lead')}</select></label>
      <button class="btn primary" type="submit">افزودن</button></form></div></section>`;
}

const crmDealRow = (x, withCust) => `<div class="card m-deal"><div class="row spread"><b>${esc(x.title)}</b><span class="num">${crmMoney(x.value)}</span></div>
  ${withCust ? `<button class="link small" data-act="crm-open" data-id="${x.customer_id}">${esc(x.customer)}</button>` : ''}
  <div class="row"><select data-act="crm-deal-stage" data-id="${x.id}">${opts(CRM_STAGE, x.stage)}</select>
    ${CRM_OPEN.includes(x.stage) ? `<button class="btn sm primary" data-act="crm-deal-won" data-id="${x.id}">🎉 فروش شد</button>` : ''}
    <button class="x" data-act="crm-deal-del" data-id="${x.id}" aria-label="حذف">✕</button></div></div>`;

async function viewCrmPipeline(d) {
  const [dl, cs] = await Promise.all([api('/api/crm/deals'), api('/api/crm/customers')]);
  const deals = dl.deals, by = st => deals.filter(x => x.stage === st);
  const monthStart = new Date(); monthStart.setDate(1); monthStart.setHours(0, 0, 0, 0);
  const won = by('won').sort((a, b) => (b.closed_ts || 0) - (a.closed_ts || 0)).slice(0, 8), lost = by('lost').slice(0, 5);
  return `<section class="pane">${crmSeg()}
    <div class="pane-title"><h1>قیف فروش</h1><span class="muted small">${fa(d.open_deals)} باز · ${crmMoney(d.open_value)} تومان${d.win_rate != null ? ` · موفقیت ${fa(d.win_rate)}٪` : ''}</span></div>
    ${CRM_OPEN.map(st => { const ds = by(st); const sum = ds.reduce((s, x) => s + x.value, 0);
      return `<div class="row spread"><h2>${CRM_STAGE[st]} <span class="muted small">${fa(ds.length)}</span></h2><span class="num small muted">${crmMoney(sum)}</span></div>
        <div class="stack">${ds.length ? ds.map(x => crmDealRow(x, true)).join('') : `<div class="muted small">—</div>`}</div>`; }).join('')}
    ${won.length ? `<h2>✅ فروش‌های اخیر</h2><div class="stack">${won.map(x => crmDealRow(x, true)).join('')}</div>` : ''}
    ${lost.length ? `<details class="card"><summary>از دست رفته‌ها (${fa(by('lost').length)})</summary>${lost.map(x => `<div class="row spread small"><span>${esc(x.customer)} — ${esc(x.title)}</span><span class="muted">${esc(x.lost_reason || '')}</span></div>`).join('')}</details>` : ''}
    <div class="card"><h2>➕ معامله تازه</h2>${cs.customers.length ? `<form class="form" data-form="crm-deal">
      <label class="f full"><span>مشتری</span><select name="customer_id" required>${cs.customers.map(c => `<option value="${c.id}">${esc(c.name)}</option>`).join('')}</select></label>
      <label class="f full"><span>عنوان</span><input type="text" name="title" required maxlength="120" placeholder="مثلاً پنل خورشیدی ۵ کیلووات"></label>
      <label class="f"><span>مبلغ (تومان)</span><input type="text" name="value" inputmode="numeric" placeholder="۱۲۰۰۰۰۰۰۰"></label>
      <label class="f"><span>مرحله</span><select name="stage">${opts(Object.fromEntries(CRM_OPEN.map(k => [k, CRM_STAGE[k]])), 'lead')}</select></label>
      <button class="btn primary" type="submit">ساختن</button></form>` : empty('اول یه مشتری اضافه کن (تب مشتری‌ها).')}</div></section>`;
}

async function openCustomer(id) {
  const r = await api('/api/crm/customers/' + id), c = r.customer;
  const fuRow = f => `<div class="row spread"><span class="small"><span class="pill">${esc(jdate(f.due))}</span> ${esc(f.note || '')} ${f.channel ? `<span class="muted">${CRM_CH[f.channel]}</span>` : ''}</span>
    <span class="row" style="gap:4px"><button class="btn sm primary" data-act="crm-fu-done" data-id="${f.id}" data-cid="${c.id}">✅</button><button class="btn sm" data-act="crm-fu-tom" data-id="${f.id}" data-cid="${c.id}">⏭ فردا</button>
    <button class="x" data-act="crm-fu-del" data-id="${f.id}" data-cid="${c.id}" aria-label="حذف">✕</button></span></div>`;
  sheet(`<div class="row spread"><h2>${esc(c.name)}</h2><button class="x" data-act="close">✕</button></div>
    ${c.company ? `<div class="muted small">${esc(c.company)}</div>` : ''}
    <div class="row"><select data-act="crm-cust-status" data-id="${c.id}">${opts(CRM_ST, c.status)}</select>${c.phone ? `<span class="num" dir="ltr">${esc(c.phone)}</span>` : '<span class="muted small">شماره ندارم</span>'}</div>
    <div class="row"><button class="btn sm primary" data-act="crm-call" data-id="${c.id}">📞 زنگ بزن</button><button class="btn sm" data-act="crm-sms" data-id="${c.id}">✉️ پیامک</button></div>
    <div id="crmPh"></div>
    <span class="eyebrow">⏰ پیگیری‌ها</span>
    <div class="stack6">${r.followups.length ? r.followups.map(fuRow).join('') : '<div class="muted small">پیگیری بازی نداره</div>'}</div>
    <form class="form" data-form="crm-fu" data-id="${c.id}">
      <label class="f"><span>کِی؟</span><select name="when"><option value="+1">فردا</option><option value="+3">۳ روز دیگه</option><option value="+7">هفتهٔ بعد</option><option value="+14">دو هفتهٔ بعد</option><option value="+30">یک ماه دیگه</option><option value="date">تاریخ دلخواه…</option></select></label>
      <label class="f"><span>تاریخ دلخواه</span><input type="date" name="date"></label>
      <label class="f full"><span>برای چی؟</span><input type="text" name="note" maxlength="300" placeholder="مثلاً زنگ بزنم جواب قیمت رو بگیرم"></label>
      <label class="f"><span>از چه راهی؟</span><select name="channel"><option value="">—</option>${opts(CRM_CH, '')}</select></label>
      <button class="btn primary" type="submit">+ پیگیری</button></form>
    <span class="eyebrow">💼 معامله‌ها</span>
    <div class="stack6">${r.deals.length ? r.deals.map(x => crmDealRow({ ...x, customer: c.name }, false)).join('') : '<div class="muted small">معامله‌ای نیست</div>'}</div>
    <form class="form" data-form="crm-deal" data-id="${c.id}"><input type="hidden" name="customer_id" value="${c.id}">
      <label class="f full"><span>معامله تازه</span><input type="text" name="title" required maxlength="120" placeholder="عنوان"></label>
      <label class="f"><span>مبلغ (تومان)</span><input type="text" name="value" inputmode="numeric"></label>
      <label class="f"><span>مرحله</span><select name="stage">${opts(Object.fromEntries(CRM_OPEN.map(k => [k, CRM_STAGE[k]])), 'lead')}</select></label>
      <button class="btn primary" type="submit">+ معامله</button></form>
    <span class="eyebrow">📝 تاریخچه</span>
    <form class="row" data-form="crm-note" data-id="${c.id}" style="flex-wrap:nowrap"><input type="text" name="text" required maxlength="800" placeholder="یادداشت: تلفنی چی گفتن؟"><button class="btn primary" type="submit">ثبت</button></form>
    <div class="stack6 small">${r.events.length ? r.events.map(e => `<div>${CRM_EV[e.kind] || '•'} <span class="muted">${esc(jdate(isoDay(e.ts)))}</span> ${esc(e.text || '')}</div>`).join('') : '<div class="muted">هنوز چیزی ثبت نشده</div>'}</div>
    <details><summary class="muted small">ویرایش مشخصات</summary><form class="form" data-form="crm-cust-edit" data-id="${c.id}">
      <label class="f"><span>اسم</span><input type="text" name="name" value="${esc(c.name)}" maxlength="80" required></label>
      <label class="f"><span>شرکت</span><input type="text" name="company" value="${esc(c.company)}" maxlength="80"></label>
      <label class="f"><span>شماره</span><input type="text" name="phone" value="${esc(c.phone)}" maxlength="30" dir="ltr"></label>
      <label class="f full"><span>یادداشت کلی</span><textarea name="notes" rows="3" maxlength="1500">${esc(c.notes)}</textarea></label>
      <button class="btn primary" type="submit">ذخیره</button></form>
      <div class="row"><button class="btn danger sm" data-act="crm-cust-del" data-id="${c.id}">🗑 حذف مشتری</button></div></details>`);
  S.cid = id;
}
async function crmReload() { if (!$('#modal').hidden && S.cid) { try { await openCustomer(S.cid); } catch (e) { /* مشتری حذف شده */ } } await renderKeep(); }
async function crmFilter() {
  const box = $('#crmList'); if (!box) return;
  try { const r = await api('/api/crm/customers?q=' + encodeURIComponent(S.cq || '') + (S.cst ? '&status=' + S.cst : '')); box.innerHTML = r.customers.length ? r.customers.map(crmCustCard).join('') : `<div class="card">${empty('چیزی پیدا نشد.')}</div>`; } catch (e) { toast(e.message); }
}
let crmTimer;
async function crmContact(id, kind) {
  let text = '';
  if (kind === 'sms') { text = (prompt('متن پیامک؟') || '').trim(); if (!text) return; }
  const r = await api(`/api/crm/customers/${id}/contact`, { method: 'POST', body: { kind, text } });
  toast('کارت تأیید ساخته شد');
  const box = $('#crmPh'); if (box) { try { box.innerHTML = phoneCard(await api('/api/phone/status')); } catch (e) { box.textContent = r.message; } }
  else { try { sheet(`<div class="row spread"><h2>📲 تأیید کن</h2><button class="x" data-act="close">✕</button></div><div id="crmPh2">${phoneCard(await api('/api/phone/status'))}</div>`); } catch (e) { toast(r.message); } }
}
async function crmAct(act, b) {
  const id = b.dataset.id;
  if (act === 'crm-view') { S.sview = b.dataset.val; store.set('mehrdad_sview', S.sview); return render(); }
  if (act === 'crm-open') return openCustomer(id);
  if (act === 'crm-fu-done') { await api('/api/crm/followups/' + id, { method: 'PATCH', body: { done: true } }); toast('✅ انجام شد'); return crmReload(); }
  if (act === 'crm-fu-tom') { const t = new Date(Date.now() + 86400000).toISOString().slice(0, 10); await api('/api/crm/followups/' + id, { method: 'PATCH', body: { due: t } }); toast('⏭ شد فردا'); return crmReload(); }
  if (act === 'crm-fu-del') { await api('/api/crm/followups/' + id, { method: 'DELETE' }); return crmReload(); }
  if (act === 'crm-call') return crmContact(id, 'call');
  if (act === 'crm-sms') return crmContact(id, 'sms');
  if (act === 'crm-deal-won') {
    const paid = confirm('پولش رو هم گرفتی؟ (تأیید = تو درآمدها هم ثبت بشه)');
    await api('/api/crm/deals/' + id, { method: 'PATCH', body: { stage: 'won', paid } }); toast('🎉 فروش ثبت شد'); return crmReload();
  }
  if (act === 'crm-deal-del') { if (confirm('این معامله حذف بشه؟')) { await api('/api/crm/deals/' + id, { method: 'DELETE' }); return crmReload(); } return; }
  if (act === 'crm-cust-del') { if (confirm('مشتری با همهٔ پیگیری‌ها و معامله‌هاش حذف بشه؟')) { await api('/api/crm/customers/' + id, { method: 'DELETE' }); S.cid = null; closeSheet(); toast('حذف شد'); return renderKeep(); } }
}
async function crmSubmit(kind, f, v) {
  const id = f.dataset.id, val = x => { const n = Number(en(x || '')); return n >= 0 ? n : 0; };
  if (kind === 'crm-cust') { await api('/api/crm/customers', { method: 'POST', body: { name: v.name.trim(), company: (v.company || '').trim() || undefined, phone: (v.phone || '').trim() || undefined, status: v.status } }); toast('ثبت شد ✓'); return renderKeep(); }
  if (kind === 'crm-deal') { await api('/api/crm/deals', { method: 'POST', body: { customer_id: Number(v.customer_id), title: v.title.trim(), value: val(v.value), stage: v.stage } }); toast('معامله ساخته شد ✓'); return crmReload(); }
  if (kind === 'crm-fu') {
    const due = v.when === 'date' ? v.date : v.when; if (!due) return toast('تاریخ رو انتخاب کن');
    await api('/api/crm/followups', { method: 'POST', body: { customer_id: Number(id), due, note: (v.note || '').trim() || undefined, channel: v.channel || undefined } }); toast('⏰ پیگیری ثبت شد'); return crmReload();
  }
  if (kind === 'crm-note') { await api(`/api/crm/customers/${id}/notes`, { method: 'POST', body: { text: v.text.trim() } }); toast('ثبت شد ✓'); return crmReload(); }
  if (kind === 'crm-cust-edit') { await api('/api/crm/customers/' + id, { method: 'PATCH', body: { name: v.name.trim(), company: v.company.trim(), phone: v.phone.trim(), notes: v.notes.trim() } }); toast('ذخیره شد ✓'); return crmReload(); }
}

async function crmChange(t) {
  try {
    const a = t.dataset.act;
    if (a === 'crm-cust-status') { await api('/api/crm/customers/' + t.dataset.id, { method: 'PATCH', body: { status: t.value } }); toast('ثبت شد ✓'); crmReload(); }
    else if (a === 'crm-deal-stage') {
      const body = { stage: t.value }; if (t.value === 'won') body.paid = confirm('پولش رو هم گرفتی؟ (تأیید = تو درآمدها هم ثبت بشه)');
      await api('/api/crm/deals/' + t.dataset.id, { method: 'PATCH', body }); toast('رفت به «' + CRM_STAGE[t.value] + '»'); crmReload();
    }
    else if (a === 'crm-st-filter') { S.cst = t.value; crmFilter(); }
  } catch (e) { if (e.message !== 'unauthorized') toast(e.message); }
}
document.addEventListener('input', ev => {
  const t = ev.target; if (!t.dataset || t.dataset.act !== 'crm-q') return;
  S.cq = t.value; clearTimeout(crmTimer); crmTimer = setTimeout(crmFilter, 250);
});

const VIEWS = { crm: viewCrm, today: viewToday, money: viewMoney, life: viewLife, coach: viewCoach, goals: viewGoals, chat: viewChat };
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

// کشیدن صفحه به پایین (وقتی بالای صفحه هستی) = تازه‌سازی؛ نیمه‌کاره‌ها (فرم/پنجره‌ی باز) رو خراب نمی‌کنه
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
  // برگشتن به اپ بعد از چند دقیقه: داده‌ها تازه بشن (مثلاً بعد از ثبت از طریق تلگرام)
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
const PA_KIND = { sms: 'پیامک', call: 'تماس', telegram: 'پیام تلگرام', instagram: 'پیام اینستاگرام', reply: 'پاسخ' };
const agoFa = t => { const m = Math.round((Date.now() / 1000 - t) / 60); return m < 1 ? 'همین الان' : m < 90 ? fa(m) + ' دقیقه پیش' : fa(Math.round(m / 60)) + ' ساعت پیش'; };
const PA_ST = { awaiting: ['⏳', 'منتظر تأیید'], approved: ['📥', 'در صف گوشی'], sending: ['📤', 'در حال انجام'], sent: ['✓', 'انجام شد'], failed: ['⚠️', 'نشد'],
  cancelled: ['✕', 'لغو شد'], expired: ['⌛', 'منقضی شد'], needs_tap: ['👆', 'لمس لازم'] };
const maskN = n => { n = String(n || ''); if (n.startsWith('tg:') || n.includes('|')) return ''; return n.length > 8 ? n.slice(0, 4) + '…' + n.slice(-3) : n; };
const paWho = a => `«${esc(a.to_name || maskN(a.to_number))}»${a.to_name && a.to_number && maskN(a.to_number) ? ` <span class="muted small num">${esc(maskN(a.to_number))}</span>` : ''}`;
function phoneCard(ps) {
  if (!ps || !ps.pending || !ps.pending.length) return '';
  return `<div class="card gold"><div class="row spread"><h2>📲 منتظر تأیید تو</h2><span class="pill gold num">${fa(ps.pending.length)}</span></div>
    ${ps.pending.map(a => `<div class="m-goal" style="padding:8px 0;border-bottom:1px solid var(--line)"><div class="c-id">${PA_KIND[a.kind] || a.kind} به ${paWho(a)}</div>
      ${a.text ? `<div class="small" style="white-space:pre-wrap">${esc(a.text)}</div>` : ''}
      <div class="row"><button class="btn sm primary" data-act="phone-ok" data-id="${a.id}">✅ بفرست</button><button class="btn sm" data-act="phone-no" data-id="${a.id}">❌ لغو</button></div></div>`).join('')}
    <p class="muted small">هیچ پیامک یا تماسی بدون این تأیید انجام نمی‌شه.</p></div>`;
}
async function renderPhoneSection() {
  const box = $('#phoneBox'); if (!box) return;
  let sv;
  try { sv = await api('/api/phone/status'); } catch (e) { box.innerHTML = empty('نشد: ' + esc(e.message)); return; }
  let nat = null; try { nat = (window.MehrdadNative && MehrdadNative.phoneStatus) ? JSON.parse(MehrdadNative.phoneStatus() || '{}') : null; } catch (e) { nat = null; }
  const ok = v => v ? '<b class="m-pos">✓</b>' : '<b class="m-neg">✗</b>';
  const when = ms => ms ? esc(jdate(isoDay(ms / 1000))) : 'هنوز نه';
  const perm = (key, label, need) => nat ? `<div class="row spread"><span>${label} ${ok(nat[key])}</span>${nat[key] ? '' : `<button class="btn sm" data-act="ph-perm" data-p="${need}">فعال کن</button>`}</div>` : '';
  const hist = (sv.recent || []).slice(0, 6).map(a => `<div class="row spread small"><span>${PA_ST[a.status] ? PA_ST[a.status][0] : '•'} ${PA_KIND[a.kind] || a.kind} به ${paWho(a)}</span><span class="muted">${PA_ST[a.status] ? PA_ST[a.status][1] : esc(a.status)}</span></div>`).join('');
  box.innerHTML = `<p class="muted small">مخاطبین و پیامک‌هات فقط روی سرور خودت می‌مونه. هیچ پیامک، تماس یا پیامی بدون تأیید یک‌لمسی خودت انجام نمی‌شه، و متنی که از بیرون می‌رسه (پیامک، ایمیل، اعلان) هرگز دستور حساب نمی‌شه.</p>
    <div class="stack6 small">
      <div class="row spread"><span>مخاطبین روی سرور: <b class="num">${fa(sv.contacts)}</b></span>${nat ? `<span class="muted">آخرین همگام‌سازی: ${when(nat.lastContacts)}</span>` : ''}</div>
      ${nat ? `${perm('contacts', 'دسترسی به مخاطبین', 'contacts')}${perm('smsRead', 'خواندن پیامک‌ها', 'sms_read')}${perm('smsSend', 'فرستادن پیامک', 'sms_send')}${perm('call', 'تماس گرفتن', 'call')}${perm('callLog', 'تاریخچهٔ تماس‌ها', 'calls')}${perm('calendar', 'تقویم', 'calendar')}${perm('notif', 'اعلان‌ها', 'notif')}
      <div class="row spread"><span>خواندن اعلان‌ها (برای پیام‌رسان‌ها) ${ok(nat.notifAccess)}</span>${nat.notifAccess ? '' : '<button class="btn sm" data-act="n-notif">فعال کن</button>'}</div>
      <div class="row"><button class="btn sm" data-act="ph-sync-contacts">همگام‌سازی مخاطبین</button><button class="btn sm" data-act="ph-sync-sms">پیامک‌های ۳۰ روز اخیر</button>
        <button class="btn sm" data-act="ph-sync-calls">تماس‌های ۳۰ روز اخیر</button><button class="btn sm" data-act="ph-sync-cal">تقویم</button></div>
      <label class="row"><input type="checkbox" data-act="ph-msgr" ${nat.msgr ? 'checked' : ''}> پیام‌های تلگرام / واتس‌اپ / اینستاگرام / بله (از اعلان‌ها) برای مهرداد ثبت بشه و بتونه جواب بده</label>
      <div class="muted">آخرین پیام پیام‌رسان که رسید: ${sv.last_notif ? agoFa(sv.last_notif) : 'هنوز چیزی نرسیده (دسترسی اعلان‌ها و تیک بالا باید روشن باشه)'}</div>
      <label class="row"><input type="checkbox" data-act="ph-service" ${nat.service ? 'checked' : ''}> کنترل گوشی (پیامک، تماس و جواب‌دادنی که تأیید می‌کنی از همین گوشی انجام بشه) ${sv.online ? '<span class="pill good">وصله</span>' : '<span class="pill warn">وصل نیست</span>'}</label>
      <label class="row"><input type="checkbox" data-act="ph-smsall" ${nat.smsAll ? 'checked' : ''}> همهٔ پیامک‌های تازه هم برای مهرداد ذخیره بشه (نه فقط بانکی؛ رمز یک‌بارمصرف هرگز)</label>
      <span class="eyebrow">🔌 پایداری اتصال</span>
      <div class="row spread"><span>الان: ${sv.online ? '<b class="m-pos">وصله ✓</b>' : '<b class="m-neg">وصل نیست ✗</b>'} <span class="muted">${sv.last_seen ? '(آخرین ارتباط ' + agoFa(sv.last_seen) + ')' : ''}</span></span><button class="btn sm primary" data-act="ph-reconnect">🔄 وصلش کن</button></div>
      <div class="muted">اگه هی قطع می‌شه، خودِ گوشی (به‌خصوص شیائومی) برنامه رو توی پس‌زمینه می‌کُشه. این موارد رو فقط یک بار انجام بده تا دیگه قطع نشه:</div>
      <div class="row spread"><span>۱) بدون محدودیت باتری ${ok(nat.battery)}</span>${nat.battery ? '' : '<button class="btn sm" data-act="ph-battery-req">فعال کن</button>'}</div>
      <div class="row spread"><span>۲) شروع خودکار (Autostart) برای MEHRDAD</span><button class="btn sm" data-act="ph-autostart">باز کن</button></div>
      ${nat.xiaomi ? '<div class="row spread"><span>۳) شیائومی: «ذخیرهٔ باتری» ← بدون محدودیت</span><button class="btn sm" data-act="ph-miui-batt">باز کن</button></div><div class="muted">۴) صفحهٔ «برنامه‌های اخیر» رو باز کن، کارت MEHRDAD رو نگه دار و 🔒 قفل رو بزن (وگرنه با کشیدن، بسته می‌شه).</div>' : ''}
      <span class="eyebrow">🎤 بیدارکردن مهرداد با صدا</span>
      <div class="muted">«همیشه منتظر اسمش باشه» یعنی میکروفون دائم باز بمونه (باتری، حریم خصوصی و محدودیت اندروید)؛ به‌جاش این راه‌های سریع هست:</div>
      <div class="stack6">
        <div>• دکمهٔ «🎤 بگو به مهرداد» توی اعلان دائمی (وقتی «کنترل گوشی» روشنه)</div>
        <div>• کاشی «مهرداد 🎤» توی تنظیمات سریع (از بالا بکش ← ویرایش ← کاشی رو اضافه کن)</div>
        <div>• نگه‌داشتن دکمهٔ پاور/هوم <span class="muted">(آزمایشی؛ اول مهرداد رو دستیار پیش‌فرض کن)</span> <button class="btn sm" data-act="ph-assistant">انتخاب دستیار</button></div>
        <div>• بگو «هی گوگل، مهرداد رو باز کن»</div>
      </div>
      <div class="row"><button class="btn sm primary" data-act="ph-talk">🎤 همین الان تست کن</button></div>
      <div class="row"><button class="btn sm" data-act="ph-talk-chat">🗣️ گفتگوی صوتی (نوبتی)</button></div>`
        : '<div class="muted">ارسال پیامک و تماس و خواندن پیام‌رسان‌ها فقط داخل اپ اندروید ممکنه.</div>'}
      <label class="row"><input type="checkbox" data-act="ph-auto" ${sv.settings.auto_confirm ? 'checked' : ''}> ارسال بدون تأیید (فقط وقتی خودم اسم یا شمارهٔ گیرنده رو توی دستورم می‌گم)</label>
      ${hist ? `<span class="eyebrow">آخرین اقدام‌ها</span>${hist}` : ''}
    </div>`;
}
window.onPhoneChanged = () => { if ($('#phoneBox')) renderPhoneSection(); };
// صدا زدن مهرداد (دکمهٔ اعلان / کاشی / دستیار): جواب مستقیم نشان داده می‌شود، همان‌جا هم می‌شود پیامک/تماس را تأیید کرد
window.onVoiceCommand = async text => {
  if (!token) return;
  sheet(`<div class="row spread"><h2>🎤 مهرداد</h2><button class="x" data-act="close">✕</button></div>
    <div class="m-b me" style="max-width:100%">${esc(text)}</div><div id="vcOut" class="m-b bot typing" style="max-width:100%"><span class="m-spin"></span></div><div id="vcPh"></div>
    <div class="row"><button class="btn sm primary" data-act="talk-from-sheet">🗣️ ادامهٔ گفتگوی صوتی</button></div>`);
  try {
    const r = await api('/api/chat', { method: 'POST', body: { text } });
    const o = $('#vcOut'); if (o) { o.classList.remove('typing'); o.textContent = r.reply; }
    speakText(r.reply);                                                       // با صدا صدا زدی → جواب هم صوتی
    try { const ps = await api('/api/phone/status'); const box = $('#vcPh'); if (box) box.innerHTML = phoneCard(ps); } catch (e) { /* فقط کارت تأیید نیامد */ }
  } catch (e) { const o = $('#vcOut'); if (o) { o.classList.remove('typing'); o.textContent = 'نشد: ' + e.message; } }
};

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
    <span class="eyebrow">🔊 صدای مهرداد</span>
    <label class="row"><input type="checkbox" data-act="ph-tts" ${ttsAlways() ? 'checked' : ''}> همهٔ جواب‌ها رو با صدا بخون <span class="muted">(وقتی خودت با 🎤 یا صدا زدن حرف بزنی، جواب صوتی همیشه هست)</span></label>
    <div class="row spread"><span>صدا</span><select data-act="ph-voice"><option value="male"${store.get('mehrdad_voice') !== 'female' ? ' selected' : ''}>مرد (فرید)</option><option value="female"${store.get('mehrdad_voice') === 'female' ? ' selected' : ''}>زن (دلارا)</option></select></div>
    <div class="row"><button class="btn sm" data-act="ph-voice-test">▶ امتحان صدا</button></div>
    <span class="eyebrow">📲 دسترسی مهرداد به گوشی</span><div id="phoneBox"><span class="m-spin"></span></div>
    <label class="row"><input type="checkbox" id="privChk" ${S.priv ? 'checked' : ''}> نمایش بخش‌های خصوصی (🔒)</label>
    <p class="muted small">پیامک بانکی و اعلان‌های مالی رو اپ اندروید می‌فرسته. برای قطع این دستگاه در تلگرام /devices و /unpair.</p>
    <button class="btn danger" data-act="logout">خروج از این دستگاه</button></div>`);
  renderPhoneSection();
}

// ------------------------------------------------------------- جفت‌سازی
function pairScreen() {
  $('#nav').hidden = true; $('#subtitle').textContent = 'مغز دوم تو';
  $('#view').innerHTML = `<section class="m-center"><div class="card"><h1>سلام، من مهردادم 👋</h1>
    <p>برای وصل‌شدن: در تلگرام به مهرداد بنویس <b>/pair</b> و کد ۸ حرفی رو اینجا بزن.</p>
    <form class="stack" data-form="pair"><input type="text" name="code" placeholder="کد جفت‌سازی" autocomplete="off" autocapitalize="characters" maxlength="16" dir="ltr" required>
    <button class="btn primary" type="submit">اتصال</button></form></div></section>`;
}

// ------------------------------------------------------------- گفتن (چت / ضبط سریع)
async function say(forId) {
  const ta = $('#' + forId); const text = ta.value.trim(); if (!text || S.busy) return;
  S.busy = true; ta.value = ''; ta.style.height = '';
  const speak = S.voiceIn || ttsAlways(); S.voiceIn = false;            // با صدا گفت یا «جواب صوتی» روشنه → جواب هم خوانده می‌شود
  const send = $(`[data-act=say][data-for=${forId}]`); if (send) send.disabled = true;
  if (forId === 'sayChat') {
    const list = $('#chatList'); const empt = $('.m-empty', list); if (empt) empt.remove();
    list.insertAdjacentHTML('beforeend', `${bubble('me', text)}<div class="m-b bot typing" id="typing"><span class="m-spin"></span></div>`);
    window.scrollTo(0, document.body.scrollHeight);
  } else toast('در حال ثبت…');
  try {
    const r = await api('/api/chat', { method: 'POST', body: { text } });
    if (forId === 'sayChat') { fillBot($('#typing'), r.reply); window.scrollTo(0, document.body.scrollHeight); }
    else { toast(r.reply.length > 110 ? r.reply.slice(0, 110) + '…' : r.reply); await render(); }
    if (speak) speakText(r.reply);
  } catch (e) {
    if (e.message !== 'unauthorized') { toast('نشد: ' + e.message); const t = $('#typing'); if (t) { t.classList.remove('typing'); t.removeAttribute('id'); t.textContent = 'نتونستم به مغز برسم؛ دوباره امتحان کن.'; } ta.value = text; }
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
    list.insertAdjacentHTML('beforeend', `${bubble('me', '📷 ' + (caption || 'عکس'))}<div class="m-b bot typing" id="typing"><span class="m-spin"></span></div>`);
    window.scrollTo(0, document.body.scrollHeight);
  } else toast('مهرداد داره عکس رو می‌خونه…');
  try {
    const image = await downscale(file);
    const r = await api('/api/chat/image', { method: 'POST', body: { image, text: caption } });
    if (inChat) { fillBot($('#typing'), r.reply); window.scrollTo(0, document.body.scrollHeight); }
    else { toast(r.reply.length > 110 ? r.reply.slice(0, 110) + '…' : r.reply); await render(); }
    if (ttsAlways()) speakText(r.reply);
  } catch (e) {
    if (e.message !== 'unauthorized') { toast('نشد: ' + e.message); const t = $('#typing'); if (t) { t.classList.remove('typing'); t.textContent = 'عکس رو نتونستم بخونم؛ دوباره امتحان کن.'; } if (ta) ta.value = caption; }
  } finally { S.busy = false; }
}
document.addEventListener('change', ev => {
  if (ev.target.id !== 'photoIn') return;
  const f = ev.target.files && ev.target.files[0]; ev.target.value = '';
  if (f) sendPhoto(f, S.photoFor || 'sayChat');
});

function mic(forId) {
  const ta = $('#' + forId);
  stopSpeaking();
  if (window.MehrdadNative && MehrdadNative.startVoice) { window.onVoiceText = t => { ta.value = (ta.value.trim() ? ta.value.trim() + ' ' : '') + t; S.voiceIn = true; ta.focus(); }; MehrdadNative.startVoice(); return; }
  const SR = window.SpeechRecognition || window.webkitSpeechRecognition; if (!SR) return toast('گفتار در این مرورگر نیست');
  const rec = new SR(); rec.lang = 'fa-IR'; rec.interimResults = false;
  const btn = $(`[data-act=mic][data-for=${forId}]`); btn.classList.add('on');
  rec.onresult = e => { ta.value = e.results[0][0].transcript; S.voiceIn = true; ta.focus(); };
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
    if (act.startsWith('crm-')) await crmAct(act, b);
    else if (act === 'close') closeSheet();
    else if (act === 'reload') render();
    else if (act === 'seg') { S[b.dataset.scope] = b.dataset.val; render(); }
    else if (act === 'edit') openEdit(id);
    else if (act === 'phone-ok' || act === 'phone-no') {
      const r = await api(`/api/phone/actions/${id}/${act === 'phone-ok' ? 'approve' : 'cancel'}`, { method: 'POST' });
      toast(r.message || 'انجام شد'); render();
      const phBox = $('#vcPh') || $('#crmPh') || $('#crmPh2');
      if (phBox) { try { phBox.innerHTML = phoneCard(await api('/api/phone/status')); } catch (e) { /* ignore */ } }
    }
    else if (act === 'ph-perm') MehrdadNative.requestPhonePermissions(b.dataset.p);
    else if (act === 'ph-sync-contacts') { toast('دارم مخاطبین رو همگام می‌کنم…'); MehrdadNative.syncContacts(); }
    else if (act === 'ph-sync-sms') { toast('دارم پیامک‌ها رو می‌خونم…'); MehrdadNative.syncSms(30); }
    else if (act === 'ph-battery') MehrdadNative.openBatterySettings();
    else if (act === 'ph-battery-req') MehrdadNative.requestBatteryExemption();
    else if (act === 'ph-autostart') MehrdadNative.openAutostart();
    else if (act === 'ph-miui-batt') MehrdadNative.openMiuiBattery();
    else if (act === 'ph-reconnect') { MehrdadNative.restartPhoneService(); toast('دارم وصلش می‌کنم…'); setTimeout(renderPhoneSection, 4000); setTimeout(renderPhoneSection, 12000); }
    else if (act === 'ph-sync-calls') { toast('دارم تماس‌ها رو می‌خونم…'); MehrdadNative.syncCalls(); }
    else if (act === 'ph-sync-cal') { toast('دارم تقویم رو همگام می‌کنم…'); MehrdadNative.syncCalendar(); }
    else if (act === 'ph-assistant') MehrdadNative.openAssistantSettings();
    else if (act === 'ph-talk') { closeSheet(); MehrdadNative.startVoiceCommand(); }
    else if (act === 'ph-talk-chat' || act === 'talk-from-sheet') { closeSheet(); talkStart(); }
    else if (act === 'ph-voice-test') speakText('سلام، من مهرداد هستم. اگه صدامو می‌شنوی، همه‌چی درسته.');
    else if (act === 'speak') { const m = b.closest('.m-b'), tx = m && $('.m-txt', m); if (tx) { stopSpeaking(); speakText(tx.textContent); } }
    else if (act === 'tts-toggle') { if (ttsAlways()) store.del('mehrdad_tts'); else store.set('mehrdad_tts', '1'); b.textContent = ttsBtnLabel(); toast(ttsAlways() ? 'از این به بعد جواب‌ها صوتی هم می‌شه' : 'جواب‌ها فقط متنی (با 🔊 کنار هر پیام می‌تونی بشنوی)'); }
    else if (act === 'talk-toggle') { if (S.talk) talkStop(); else talkStart(); }
    else if (act === 'n-sms') MehrdadNative.requestSmsPermission();
    else if (act === 'n-notif') MehrdadNative.openNotificationAccess();
    else if (act === 'n-update') { closeSheet(); MehrdadNative.checkUpdate(); }
    else if (act === 'mark-done') { await api('/api/events/' + id, { method: 'PATCH', body: { status: 'done' } }); toast('انجام‌شد ✓'); render(); }
    else if (act === 'gview') { S.gview = b.dataset.val; render(); }
    else if (act === 'say-onboard') { go('chat'); setTimeout(() => { const ta = $('#sayChat'); if (ta) { ta.value = 'بیا مصاحبه رو شروع کنیم؛ یکی‌یکی ازم سؤال کن تا منو بشناسی.'; ta.focus(); } }, 300); }
    else if (act === 'track-habit') {
      const good = prompt(`جایگزین خوب برای «${b.dataset.name}» چیه؟`, 'پیاده‌روی ۱۰ دقیقه'); if (!good) return;
      await api('/api/habits', { method: 'POST', body: { good: good.trim(), bad: b.dataset.name } }); toast('عادت ثبت شد؛ هر شب از تو می‌پرسم 🔥'); render();
    }
    else if (act === 'make-invite') {
      const r = await api('/api/invites', { method: 'POST', body: { label: 'همسر', days: 14 } });
      $('#inviteOut').innerHTML = `<div class="note" style="padding:10px;border-radius:10px;background:var(--surface2)"><div class="small muted">این لینک رو فقط برای همسرت بفرست (۱۴ روز اعتبار داره، حداکثر ۳ بار باز می‌شه):</div>
        <input type="text" readonly dir="ltr" value="${esc(r.url)}" id="inviteUrl" style="margin-top:6px">
        <div class="row" style="margin-top:6px"><button class="btn sm primary" data-act="copy-invite">کپی</button>${navigator.share ? '<button class="btn sm" data-act="share-invite">ارسال…</button>' : ''}</div></div>`;
    }
    else if (act === 'copy-invite') { const el = $('#inviteUrl'); el.select(); try { await navigator.clipboard.writeText(el.value); toast('کپی شد'); } catch { document.execCommand('copy'); toast('کپی شد'); } }
    else if (act === 'share-invite') { try { await navigator.share({ title: 'چند تا سؤال درباره‌ی مهرداد', text: 'سلام عزیزم 🙏 این چند تا سؤال رو درباره‌ی من جواب بده؛ هر چی به ذهنت می‌رسه. جواب درست و غلط نداره 💛', url: $('#inviteUrl').value }); } catch {} }
    else if (act === 'revoke-inv') { if (confirm('این لینک باطل بشه؟')) { await api('/api/invites/' + id, { method: 'DELETE' }); render(); } }
    else if (act === 'suggest-goals') {
      const out = $('#goalSuggest'); out.innerHTML = '<span class="m-spin"></span> مهرداد داره فکر می‌کنه…'; b.disabled = true;
      try {
        const r = await api('/api/goals/suggest', { method: 'POST' }); S.cache.suggest = r.goals;
        out.innerHTML = r.goals.length ? r.goals.map((g, i) => `<div class="card" style="margin-top:8px"><div class="row spread"><b>${esc(g.title)}</b><span class="pill gold">${esc(g.horizon || '')}</span></div>
          ${g.why ? `<div class="muted small">چرا: ${esc(g.why)}</div>` : ''}${(g.steps || []).length ? `<ul class="small" style="margin:4px 0;padding-inline-start:18px">${g.steps.map(x => `<li>${esc(x)}</li>`).join('')}</ul>` : ''}
          <button class="btn sm primary" data-act="add-suggest" data-i="${i}">افزودن به هدف‌ها</button></div>`).join('') : empty('هنوز چیز کافی از تو نمی‌دونم؛ در «پروفایل من» مصاحبه رو شروع کن.');
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
      const i = b.dataset.i, kind = b.dataset.kind || 'q', ta = $('#c' + (kind === 'e' ? 'e' : 'q') + i), text = (ta.value || '').trim(); if (!text) return toast('جوابت رو بنویس');
      b.disabled = true; b.textContent = 'در حال ثبت…';
      try { await api('/api/coach/answer', { method: 'POST', body: { idx: Number(i), text, kind } }); renderKeep(); } finally { b.disabled = false; }
    }
    else if (act === 'coach-track') { const r = await api(`/api/coach/swap/${b.dataset.i}/track`, { method: 'POST' }); toast(r.existing ? 'از قبل پیگیری می‌شد 🔥' : 'ثبت شد؛ هر شب از تو می‌پرسم 🔥'); b.disabled = true; }
    else if (act === 'coach-teach') {
      const topic = ($('#teachTopic').value || '').trim(); if (topic.length < 2) return toast('موضوع رو بنویس');
      const out = $('#teachOut'); out.innerHTML = '<span class="m-spin"></span> استاد داره درس رو آماده می‌کنه…'; b.disabled = true;
      try { const r = await api('/api/coach/teach', { method: 'POST', body: { topic } }); out.innerHTML = `<div class="m-b bot c-body" style="max-width:100%;margin-top:8px">${esc(r.text)}</div>`; }
      catch (e) { out.innerHTML = empty('نشد: ' + esc(e.message)); } finally { b.disabled = false; }
    }
    else if (act === 'coach-rec') {
      const out = $('#recOut'); out.innerHTML = '<span class="m-spin"></span> دارم کتاب‌های مناسب تو رو پیدا می‌کنم…'; b.disabled = true;
      try { const r = await api('/api/coach/books/recommend', { method: 'POST' }); toast(r.added.length ? 'کتاب‌ها اضافه شد' : 'کتاب تازه‌ای نبود'); await renderKeep(); }
      catch (e) { out.innerHTML = empty('نشد: ' + esc(e.message)); } finally { b.disabled = false; }
    }
    else if (act === 'coach-addbook') { await api('/api/coach/books', { method: 'POST', body: { title: b.dataset.title, author: b.dataset.author } }); b.disabled = true; toast('اضافه شد؛ پایین‌تر «شروع آموزش کتاب» رو بزن'); renderKeep(); }
    else if (act === 'coach-lesson') {
      const out = $('#bk' + id); out.innerHTML = '<span class="m-spin"></span> استاد درس رو آماده می‌کنه (حدود ۱ دقیقه)…'; b.disabled = true;
      try { const r = await api(`/api/coach/books/${id}/lesson`, { method: 'POST' }); if (r.lesson) S.openLesson = id + ':' + r.lesson.n; else toast('این کتاب ۱۲ درس رو تمام کرد 🎉'); await renderKeep(); }
      catch (e) { out.innerHTML = empty('نشد: ' + esc(e.message)); b.disabled = false; }
    }
    else if (act === 'coach-book') { await api('/api/coach/books/' + id, { method: 'PATCH', body: { status: b.dataset.st } }); renderKeep(); }
    else if (act === 'coach-book-del') { if (confirm('این کتاب از فهرست حذف بشه؟')) { await api('/api/coach/books/' + id, { method: 'DELETE' }); renderKeep(); } }
    else if (act === 'goto-projects') { S.tab = 'goals'; S.gview = 'projects'; S.pid = ''; store.set('mehrdad_tab', 'goals'); render(); window.scrollTo(0, 0); }
    else if (act === 'proj-open') { S.tab = 'goals'; S.gview = 'projects'; S.pid = b.dataset.id; store.set('mehrdad_tab', 'goals'); render(); window.scrollTo(0, 0); }
    else if (act === 'proj-back') { S.pid = ''; render(); window.scrollTo(0, 0); }
    else if (act === 'proj-toggle') { await api('/api/projects/items/' + id, { method: 'PATCH', body: { done: b.dataset.done === '1' } }); renderKeep(); }
    else if (act === 'proj-del') { if (confirm('این مورد حذف بشه؟')) { await api('/api/projects/items/' + id, { method: 'DELETE' }); renderKeep(); } }
    else if (act === 'pshift') { S.pmonth = shiftM(S.pmonth, Number(b.dataset.d)); render(); }
    else if (act === 'pmonth') { S.pmonth = b.dataset.val; render(); window.scrollTo(0, 0); }
    else if (act === 'pay-del') { if (confirm('فیش واقعی این ماه حذف بشه؟ (ماه دوباره تخمینی می‌شه)')) { await api('/api/payroll/slips/' + S.pmonth, { method: 'DELETE' }); toast('حذف شد'); render(); } }
    else if (act === 'acc-edit') openAccEdit(id);
    else if (act === 'debt-edit') openDebtEdit(id);
    else if (act === 'acc-del') { if (confirm('این حساب حذف بشه؟')) { await api('/api/accounts/' + id, { method: 'DELETE' }); render(); } }
    else if (act === 'debt-del') { if (confirm('این بدهی حذف بشه؟')) { await api('/api/debts/' + id, { method: 'DELETE' }); render(); } }
    else if (act === 'debt-pay') {
      const d = (S.cache.fin?.debts || []).find(x => x.id === Number(id)); if (!d) return;
      const v = prompt('مبلغ پرداختی (تومان):', String(d.installment_amount || d.remaining)); if (v === null) return;
      const amount = Number(en(v)); if (!(amount >= 0)) return toast('مبلغ نامعتبر');
      await api(`/api/debts/${id}/pay`, { method: 'POST', body: { amount } }); toast('قسط ثبت شد ✓ (در حساب‌ها هم خرج شد)'); render();
    }
    else if (act === 'ask-fin') {
      const out = $('#finOut'); out.innerHTML = '<span class="m-spin"></span> مهرداد داره حساب‌هات رو بررسی می‌کنه…'; b.disabled = true;
      try { const r = await api('/api/chat', { method: 'POST', body: { text: b.dataset.q } }); out.innerHTML = `<div class="m-b bot" style="max-width:100%">${esc(r.reply)}</div>`; } finally { b.disabled = false; }
    }
    else if (act === 'del') { if (confirm('حذف بشه؟')) { await api('/api/events/' + id, { method: 'DELETE' }); closeSheet(); toast('حذف شد'); render(); } }
    else if (act === 'toggle') { const e = findEvent(id); const done = (e.fields || {}).status === 'done';
      await api('/api/events/' + id, { method: 'PATCH', body: { fields: { status: done ? 'open' : 'done' } } }); render(); }
    else if (act === 'say') say(b.dataset.for);
    else if (act === 'mic') mic(b.dataset.for);
    else if (act === 'photo') { S.photoFor = b.dataset.for; $('#photoIn').click(); }
    else if (act === 'theme') { applyTheme(b.dataset.val); $$('.seg [data-act=theme]').forEach(x => x.setAttribute('aria-pressed', x === b)); }
    else if (act === 'logout') { closeSheet(); logout(false); }
    else if (act === 'plan') {
      const out = $('#planOut'); out.innerHTML = '<span class="m-spin"></span> مهرداد داره برنامه می‌چینه…'; b.disabled = true;
      try { const r = await api('/api/chat', { method: 'POST', body: { text: `برنامهٔ ${b.dataset.what}‌ام رو بر اساس هدف‌ها و کارهای بازم و عادت‌هام بچین. کوتاه و قابل‌اجرا، با ساعت‌بندی پیشنهادی.` } });
        out.innerHTML = `<div class="m-b bot" style="max-width:100%">${esc(r.reply)}</div>`; } finally { b.disabled = false; }
    }
  } catch (e) { if (e.message !== 'unauthorized') toast(e.message); }
});

document.addEventListener('change', async ev => {
  const t = ev.target;
  if (t.id === 'privChk') { S.priv = t.checked; store.set('mehrdad_priv', S.priv ? '1' : '0'); syncPriv(); render(); }
  else if (t.dataset.act === 'ph-service') {
    try { MehrdadNative.setPhoneService(t.checked); toast(t.checked ? 'کنترل گوشی روشن شد' : 'کنترل گوشی خاموش شد'); setTimeout(renderPhoneSection, 1200); } catch (e) { toast(e.message); }
  }
  else if (t.dataset.act === 'ph-msgr') {
    try { MehrdadNative.setMessengerCapture(t.checked); toast(t.checked ? 'از این به بعد پیام‌های پیام‌رسان‌ها رو هم می‌بینم' : 'دیگه پیام‌رسان‌ها رو نمی‌خونم'); setTimeout(renderPhoneSection, 800); } catch (e) { toast(e.message); }
  }
  else if ((t.dataset.act || '').startsWith('crm-')) crmChange(t);
  else if (t.dataset.act === 'ph-tts') { if (t.checked) store.set('mehrdad_tts', '1'); else store.del('mehrdad_tts'); toast(t.checked ? 'از این به بعد همهٔ جواب‌ها صوتی هم هست' : 'فقط وقتی با صدا حرف بزنی جواب صوتی می‌گیری'); }
  else if (t.dataset.act === 'ph-voice') { store.set('mehrdad_voice', t.value); toast(t.value === 'female' ? 'صدا: دلارا' : 'صدا: فرید'); speakText('سلام، من مهرداد هستم. این صدای منه.'); }
  else if (t.dataset.act === 'ph-smsall') {
    try { MehrdadNative.setSmsAll(t.checked); await api('/api/phone/settings', { method: 'PUT', body: { sms_all: t.checked } }); toast('ذخیره شد'); } catch (e) { toast(e.message); }
  }
  else if (t.dataset.act === 'ph-auto') {
    if (t.checked && !confirm('با این گزینه، وقتی خودت اسم یا شمارهٔ گیرنده رو توی دستورت بگی پیامک/تماس بدون تأیید انجام می‌شه. اگه مطمئنی روشنش کن.')) { t.checked = false; return; }
    try { await api('/api/phone/settings', { method: 'PUT', body: { auto_confirm: t.checked } }); toast(t.checked ? 'ارسال بدون تأیید روشن شد' : 'از این به بعد همیشه تأیید می‌گیرم'); } catch (e) { toast(e.message); }
  }
  else if (t.dataset.act === 'proj-status') {
    try { await api('/api/projects/' + encodeURIComponent(t.dataset.id), { method: 'PATCH', body: { status: t.value } }); toast('وضعیت عوض شد'); } catch (e) { toast(e.message); }
  }
  else if (t.dataset.act === 'pay-setting') {
    try { await api('/api/payroll/settings', { method: 'PUT', body: { [t.dataset.key]: t.value } }); toast('ذخیره شد'); renderKeep(); } catch (e) { toast(e.message); }
  }
  else if (t.dataset.act === 'pay-ins') {
    const vals = $$('[data-act=pay-ins]:checked').map(x => x.value);
    try { await api('/api/payroll/settings', { method: 'PUT', body: { insurable: vals } }); toast('ذخیره شد'); renderKeep(); } catch (e) { toast(e.message); }
  }
  else if (t.dataset.act === 'progress') {
    try { await api('/api/events/' + t.dataset.id, { method: 'PATCH', body: { fields: { progress: Number(t.value) } } }); render(); } catch (e) { toast(e.message); }
  }
});

document.addEventListener('toggle', async ev => {
  const d = ev.target;
  if (!d || !d.dataset || !d.dataset.doc || !d.open || d.dataset.loaded) return;
  d.dataset.loaded = '1';
  const box = $('#doc' + d.dataset.doc);
  try { const r = await api('/api/projects/doc/' + d.dataset.doc); box.innerHTML = mdLite(r.body); }
  catch (e) { d.dataset.loaded = ''; if (box) box.textContent = 'باز نشد: ' + e.message; }
}, true);

// روی گوشی/تبلت (صفحه‌کلید لمسی) اینتر = سطر بعد؛ ارسال فقط با دکمه. روی کامپیوتر اینتر = ارسال، Shift+Enter = سطر بعد.
const isTouch = () => (window.matchMedia && matchMedia('(pointer: coarse)').matches) || navigator.maxTouchPoints > 0 || /Android|iPhone|iPad/i.test(navigator.userAgent);
document.addEventListener('keydown', ev => {
  if (ev.target.matches && ev.target.matches('textarea[id^=say]') && ev.key === 'Enter' && !ev.shiftKey && !ev.isComposing && !isTouch()) { ev.preventDefault(); say(ev.target.id); }
});
// باکس نوشتن با متن بلندتر می‌شود (تا سقف مشخص)
document.addEventListener('input', ev => {
  const ta = ev.target; if (!ta.matches || !ta.matches('textarea[id^=say]')) return;
  ta.style.height = 'auto'; ta.style.height = Math.min(ta.scrollHeight + 2, 180) + 'px';
});

document.addEventListener('submit', async ev => {
  const f = ev.target.closest('form[data-form]'); if (!f) return; ev.preventDefault();
  const kind = f.dataset.form, v = Object.fromEntries(new FormData(f).entries());
  try {
    if (kind === 'pair') {
      const r = await fetch('/api/pair', { method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ code: v.code.trim(), name: navigator.userAgent.includes('Android') ? 'مرورگر گوشی' : 'مرورگر' }) });
      if (!r.ok) return toast(r.status === 429 ? 'تلاش زیاد؛ ۱۰ دقیقه بعد' : 'کد اشتباه یا منقضیه. دوباره /pair بزن.');
      token = (await r.json()).token; store.set('mehrdad_token', token);
      if (window.MehrdadNative && MehrdadNative.savePairing) MehrdadNative.savePairing(location.origin, token);
      toast('وصل شد ✓'); return boot();
    }
    if (kind.startsWith('crm-')) { await crmSubmit(kind, f, v); return; }
    if (kind === 'proj-item') { await api('/api/projects/' + encodeURIComponent(S.pid) + '/items', { method: 'POST', body: { kind: v.kind, text: v.text.trim() } }); toast('ثبت شد ✓'); return renderKeep(); }
    if (kind === 'proj-new') { const r = await api('/api/projects', { method: 'POST', body: { name: v.name.trim() } }); S.pid = r.id; toast('پروژه ساخته شد'); return render(); }
    if (kind === 'payvar') {
      const val = Number(en(v.value)); if (!(val >= 0)) return toast('مقدار نامعتبر');
      const r = await api('/api/payroll/vars', { method: 'POST', body: { month: S.pmonth, op: v.op, value: val, mode: v.mode } });
      toast((r.notes || [])[0] || 'ثبت شد ✓'); return renderKeep();
    }
    if (kind === 'payslip') {
      const num = x => { const n = Number(en(x || '')); return n >= 0 ? n : 0; };
      const g = (grp, keys) => Object.fromEntries(keys.map(key => [key, num(v[grp + '_' + key])]));
      const L = S.cache.pay.labels, month = en(v.month).replace('/', '-');
      const body = { earn: g('earn', L.earn.map(x => x[0])), ded: g('ded', L.ded.map(x => x[0])), work: g('work', L.work.map(x => x[0])), unit: v.unit };
      const tot = {}; for (const key of ['total_earn', 'total_ded', 'net']) if (v['tot_' + key]) tot[key] = num(v['tot_' + key]); if (Object.keys(tot).length) body.totals = tot;
      const r = await api('/api/payroll/slips/' + month, { method: 'PUT', body });
      S.pmonth = r.month; toast((r.mismatch || []).length ? 'ذخیره شد، اما جمع‌ها با اقلام نمی‌خونه ⚠️' : 'فیش ذخیره شد ✓'); return render();
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
