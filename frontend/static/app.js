/* Ghost Data Audit — the page.
   One small state object, a few render functions, and a spring for anything that moves.
   A spring always starts from where the value is right now and keeps its speed, so any animation can be
   interrupted and redirected at any moment. */
(() => {
'use strict';

/* ================================================================== helpers */
const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];
/* "No motion" is either the system setting or ?still=1 (handy for screenshots and for checking the layout). */
const stillMode = new URLSearchParams(location.search).get('still') === '1';
if (stillMode) document.documentElement.classList.add('still');
const motionQuery = matchMedia('(prefers-reduced-motion: reduce)');
const reduce = { get matches() { return motionQuery.matches || stillMode; } };
const fmt = (n) => Number(n).toLocaleString();
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const clamp = (x, a, b) => Math.min(b, Math.max(a, x));
const icon = (name, size = 20) => `<svg width="${size}" height="${size}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const bytes = (n) => n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(n < 10240 ? 1 : 0)} KB` : `${(n / 1048576).toFixed(1)} MB`;

async function api(path, { method = 'GET', body, headers = {} } = {}) {
  let res;
  try {
    res = await fetch(path, { method, body, headers: { 'X-Requested-With': 'ghost-audit-ui', ...headers } });
  } catch {                                       // the browser could not reach the server at all
    const err = new Error('Can’t reach the website’s server. It may have been stopped. Start it again with “Start Website.bat”, then reload this page.');
    err.offline = true; throw err;
  }
  let data = null;
  try { data = await res.json(); } catch { /* not JSON */ }
  if (!res.ok) { const err = new Error(data?.error || `Something went wrong (${res.status}).`); err.data = data; err.status = res.status; throw err; }
  return data;
}

/* A damped spring. response = how quickly it settles (seconds), damping 1 = no overshoot.
   .to(target) while it is moving just changes the target: position and speed carry on, nothing jumps. */
class Spring {
  constructor(value = 0, { response = 0.5, damping = 1 } = {}) {
    this.x = value; this.v = 0; this.t = value; this.raf = 0; this.cb = null;
    const w = (2 * Math.PI) / response; this.k = w * w; this.c = 2 * damping * w;
  }
  to(target, cb) {
    this.t = target; if (cb) this.cb = cb;
    if (reduce.matches) { this.x = target; this.v = 0; this.cb && this.cb(this.x); return this; }
    if (this.raf) return this;
    let last = performance.now();
    const step = (now) => {
      let dt = Math.min(0.05, (now - last) / 1000); last = now;
      while (dt > 0) { const h = Math.min(dt, 1 / 240); this.v += (this.k * (this.t - this.x) - this.c * this.v) * h; this.x += this.v * h; dt -= h; }
      this.cb && this.cb(this.x);
      if (Math.abs(this.t - this.x) < 1e-3 && Math.abs(this.v) < 1e-3) { this.x = this.t; this.v = 0; this.cb && this.cb(this.x); this.raf = 0; return; }
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
    return this;
  }
}

function toast(message) {
  const el = $('#toast'); el.textContent = message; el.classList.add('show');
  clearTimeout(toast.timer); toast.timer = setTimeout(() => el.classList.remove('show'), 2600);
}

/* ================================================================== plain-language words */
const SYSTEMS = {
  account_service: 'Customer accounts', search_service: 'Search index', support_platform: 'Support desk',
  analytics_platform: 'Analytics', integration_service: 'Data connectors', backup_service: 'Backups',
  export_service: 'Data exports', security_service: 'Security logs', marketing_service: 'Marketing',
  object_storage: 'File storage', cache_service: 'Cache', email_service: 'Email delivery', legal_service: 'Legal holds',
};
const sysName = (id) => SYSTEMS[id] || String(id).replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase());
const OPS = {
  REPORT_REMAINING_RECORD: ['found', 'A record that should be gone is still there'],
  REPORT_EXPOSED_PII: ['found', 'A kept record still shows personal details'],
  REPORT_ACTIVE_DATA_FLOW: ['found', 'A process is still copying this person’s data'],
  REPORT_RESTORE_RISK: ['found', 'A backup could bring this data back'],
  DISABLE_DATA_FLOW: ['fix', 'Switch off the process that copies the data'],
  BLOCK_RESTORE: ['fix', 'Stop the backup from restoring this data'],
  DELETE_RECORD: ['fix', 'Delete the record'],
  REDACT_RECORD: ['fix', 'Blank out the personal details but keep the record'],
  ANONYMIZE_RECORD: ['fix', 'Scrub the record so it can’t be linked to the person'],
  VERIFY_RECORD_ABSENT: ['check', 'Check that the record is gone'],
  VERIFY_RECORD_PRESENT: ['check', 'Check that the record we must keep is still there'],
  VERIFY_RECORD_REDACTED: ['check', 'Check the personal details are blanked out'],
  VERIFY_RECORD_ANONYMIZED: ['check', 'Check the record can no longer be linked to the person'],
  VERIFY_DATA_FLOW_DISABLED: ['check', 'Check the copying process is switched off'],
  VERIFY_RESTORE_BLOCKED: ['check', 'Check the data can’t be restored'],
};
const FINDING_BARS = { REPORT_REMAINING_RECORD: 'Records still there', REPORT_EXPOSED_PII: 'Personal details still visible',
  REPORT_ACTIVE_DATA_FLOW: 'Processes still copying data', REPORT_RESTORE_RISK: 'Backups that could bring data back' };
const FIX_BARS = { DELETE_RECORD: 'Delete a record', REDACT_RECORD: 'Blank out personal details', ANONYMIZE_RECORD: 'Scrub so it can’t be linked',
  DISABLE_DATA_FLOW: 'Switch off a copying process', BLOCK_RESTORE: 'Block a backup from restoring' };
const STATUS_LABEL = { COMPLETE: 'Really done', INCOMPLETE: 'Something is left', NOT_APPLICABLE: 'Not a deletion request' };
const REPORTED = { COMPLETE: 'Said complete', PARTIALLY_COMPLETE: 'Said partly done', NOT_STARTED: 'Said not started' };
const sClass = (s) => s === 'COMPLETE' ? 's-complete' : s === 'INCOMPLETE' ? 's-incomplete' : 's-na';

/* ================================================================== state */
const state = {
  status: null, mode: 'builtin', batch: null, useReadings: true,
  job: null, running: false, history: [],
  filter: 'all', query: '', shown: 40,
};

/* ================================================================== theme */
function setTheme(theme, remember = true) {
  const root = document.documentElement;
  root.classList.add('theme-anim'); clearTimeout(setTheme.timer); setTheme.timer = setTimeout(() => root.classList.remove('theme-anim'), 500);
  root.dataset.theme = theme;
  $('meta[name="theme-color"]').setAttribute('content', theme === 'dark' ? '#000000' : '#f5f5f7');
  if (remember) { try { localStorage.setItem('ghost-theme', theme); } catch { /* private mode */ } }
}
$('#themeBtn').addEventListener('click', () => setTheme(document.documentElement.dataset.theme === 'dark' ? 'light' : 'dark'));
matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
  let saved = null; try { saved = localStorage.getItem('ghost-theme'); } catch { /* ignore */ }
  if (!saved) setTheme(e.matches ? 'dark' : 'light', false);
});

/* ================================================================== reveal on scroll, with a stagger */
const revealer = new IntersectionObserver((entries) => {
  for (const entry of entries) {
    if (!entry.isIntersecting) continue;
    entry.target.classList.add('in'); revealer.unobserve(entry.target); runAnimations(entry.target);
  }
}, { threshold: 0.12, rootMargin: '0px 0px -6% 0px' });
function reveal(container) {
  $$('[data-reveal]', container).forEach((el, i) => { el.style.setProperty('--d', `${Math.min(i, 6) * 70}ms`); revealer.observe(el); });
}

/* things that animate when their card comes into view */
function runAnimations(root) {
  $$('[data-count]', root).forEach((el) => {
    if (el.dataset.done) return; el.dataset.done = '1';
    const to = Number(el.dataset.count), dec = Number(el.dataset.dec || 0), suffix = el.dataset.suffix || '';
    new Spring(0, { response: 1.1 }).to(to, (x) => { el.textContent = (dec ? x.toFixed(dec) : fmt(Math.round(x))) + suffix; });
  });
  $$('[data-bar]', root).forEach((el, i) => {
    if (el.dataset.done) return; el.dataset.done = '1';
    const pct = clamp(Number(el.dataset.bar), 0, 1);
    setTimeout(() => new Spring(0, { response: 0.8, damping: 0.85 }).to(pct, (x) => { el.style.transform = `scaleX(${clamp(x, 0, 1.04)})`; }), 120 + i * 90);
  });
  $$('[data-ring]', root).forEach((el) => {
    if (el.dataset.done) return; el.dataset.done = '1';
    const C = 2 * Math.PI * 44, pct = clamp(Number(el.dataset.ring), 0, 1);
    el.style.strokeDasharray = `${C}`;
    new Spring(0, { response: 1 }).to(pct, (x) => { el.style.strokeDashoffset = `${C * (1 - clamp(x, 0, 1))}`; });
  });
  $$('[data-donut]', root).forEach((el) => {
    if (el.dataset.done) return; el.dataset.done = '1';
    const vals = el.dataset.donut.split(',').map(Number), total = vals.reduce((a, b) => a + b, 0) || 1;
    const C = 2 * Math.PI * 70, segs = $$('.seg', el), gap = vals.filter((v) => v > 0).length > 1 ? 3 : 0;
    new Spring(0, { response: 1.2, damping: 0.9 }).to(1, (s) => {
      let start = 0;
      segs.forEach((seg, i) => {
        const len = (vals[i] / total) * C, visible = clamp(s * C - start, 0, len);
        const draw = Math.max(0, visible - (visible >= len ? gap : 0));
        seg.style.strokeDasharray = `${draw} ${C}`; seg.style.strokeDashoffset = `${-start}`; start += len;
      });
    });
  });
}

/* ================================================================== engine status */
function setPill(kind, text) {
  const pill = $('#enginePill'); pill.className = `pill ${kind}`; $('#enginePillText').textContent = text;
}
async function pollStatus() {
  try {
    const st = await api('/api/status'); state.status = st;
    if (st.error) { setPill('bad', 'Needs attention'); showBanner('bad', `<span><b>The evidence could not be loaded.</b> ${esc(st.error)}</span>`); }
    else if (!st.ready) setPill('warm', 'Getting ready');
    else {
      setPill('ready', 'Ready'); showBanner();
      const missing = [!st.tools.tesseract && 'Tesseract (reads text from pictures)', !st.tools.pdftotext && 'Poppler (reads PDFs)'].filter(Boolean);
      if (missing.length) showBanner('warn', `<span><b>Missing helper programs:</b> ${missing.join(' and ')}. Some evidence may not be read.</span>`);
    }
    renderSetup(); fillFacts();
    if (!st.ready && !st.error) setTimeout(pollStatus, 700);
    return st;
  } catch { setPill('bad', 'Server not reachable'); setTimeout(pollStatus, 2000); }
}
function showBanner(kind, html) {
  const el = $('#banner'); if (!kind) { el.innerHTML = ''; return; }
  el.innerHTML = `<div class="banner ${kind}" role="alert">${html}</div>`;
}
function fillFacts() {
  const d = state.status?.dataset; if (!d || !d.requests) return;
  for (const [id, val] of [['#factRequests', d.requests], ['#factEvidence', d.evidence_files], ['#factPractice', d.practice_cases]]) {
    const el = $(id); if (el.dataset.set === String(val)) continue; el.dataset.set = String(val);
    new Spring(0, { response: 0.9 }).to(val, (x) => { el.textContent = fmt(Math.round(x)); });
  }
  $('#readingsHelp').textContent = d.readings
    ? `${d.readings} statuses were read from screenshots. Turn this off to see what they change.`
    : 'No screenshot readings are available.';
}

/* ================================================================== set-up card */
const thumb = $('#segThumb');
function positionThumb() {
  const active = $(`#modeSeg button[aria-selected="true"]`); if (!active) return;
  thumb.style.width = `${active.offsetWidth}px`; thumb.style.transform = `translateX(${active.offsetLeft}px)`;
}
new ResizeObserver(positionThumb).observe($('#modeSeg'));
document.fonts?.ready.then(positionThumb);
$$('#modeSeg button').forEach((btn) => btn.addEventListener('click', () => setMode(btn.dataset.mode)));
function setMode(mode) {
  state.mode = mode;
  $$('#modeSeg button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.mode === mode)));
  positionThumb();
  for (const [id, m] of [['#panelBuiltin', 'builtin'], ['#panelUpload', 'upload']]) {
    const el = $(id), show = mode === m;
    if (show && el.hidden) { el.hidden = false; el.style.animation = 'none'; void el.offsetWidth; el.style.animation = ''; }
    else if (!show) el.hidden = true;
  }
  renderSetup();
}
$('#readingsSwitch').addEventListener('click', (e) => {
  state.useReadings = !state.useReadings; e.currentTarget.setAttribute('aria-checked', String(state.useReadings));
});
function renderSetup() {
  const ready = !!state.status?.ready, busy = state.running;
  const usable = state.batch ? (state.batch.matched ?? state.batch.rows) : 0;      // requests that belong to a known customer
  const haveBatch = state.mode === 'builtin' || usable > 0;
  const btn = $('#runBtn'); btn.disabled = !(ready && haveBatch) || busy;
  const rows = state.mode === 'builtin' ? state.status?.dataset?.requests : usable;
  $('#runHint').textContent = !state.status ? 'Connecting…' : state.status.error ? 'The evidence could not be loaded.'
    : !ready ? 'Getting the evidence ready (the first time takes a moment)…'
    : state.mode === 'upload' && state.batch && usable === 0 ? 'None of the emails in this file are in the customer list.'
    : !haveBatch ? 'Choose a CSV file to continue.' : `Ready to check ${fmt(rows || 0)} request${rows === 1 ? '' : 's'}.`;
}

/* ---------- upload ---------- */
const drop = $('#drop'), fileInput = $('#fileInput');
drop.addEventListener('click', () => fileInput.click());
fileInput.addEventListener('change', () => { if (fileInput.files[0]) upload(fileInput.files[0]); fileInput.value = ''; });
['dragenter', 'dragover'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add('over'); }));
['dragleave', 'drop'].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove('over'); }));
drop.addEventListener('drop', (e) => { const f = e.dataTransfer?.files?.[0]; if (f) upload(f); });
window.addEventListener('dragover', (e) => e.preventDefault());
window.addEventListener('drop', (e) => e.preventDefault());

async function upload(file) {
  if (!/\.csv$/i.test(file.name) && !/csv|text\/plain/.test(file.type)) { toast('Please choose a .csv file.'); drop.classList.add('shake'); setTimeout(() => drop.classList.remove('shake'), 500); return; }
  drop.querySelector('strong').textContent = 'Checking your file…';
  try {
    const out = await api('/api/batches', { method: 'POST', body: file, headers: { 'X-Filename': encodeURIComponent(file.name), 'Content-Type': 'text/csv' } });
    state.batch = out.batch; showUploaded(out);
  } catch (err) {
    drop.querySelector('strong').textContent = 'Drop a CSV file here';
    drop.classList.add('shake'); setTimeout(() => drop.classList.remove('shake'), 500);
    showUploadError(err);
  }
  renderSetup();
}
function showUploadError(err) {
  const probs = err.data?.problems || [];
  const box = $('#uploadEmpty'); $('.upload-error')?.remove();
  const el = document.createElement('div'); el.className = 'upload-error banner bad'; el.setAttribute('role', 'alert');
  el.innerHTML = `<span><b>${esc(err.message)}</b>${probs.length ? '<br>' + probs.slice(0, 6).map((p) => `Line ${p.line}${p.case_id ? ` (${esc(p.case_id)})` : ''}: ${esc(p.message)}`).join('<br>') : ''}</span>`;
  box.appendChild(el);
}
function showUploaded(out) {
  $('#uploadEmpty').hidden = true; $('.upload-error')?.remove();
  drop.querySelector('strong').textContent = 'Drop a CSV file here';
  const b = out.batch, el = $('#uploadDone'); el.hidden = false;
  const probs = out.problems || [];
  const matched = b.matched ?? b.rows, unmatched = out.unmatched || [];
  const nothing = matched === 0;
  el.innerHTML = `
    <div class="filecard">
      <div class="filecard-top">
        <div class="doc">${icon('doc', 22)}</div>
        <div class="grow"><h3>${esc(b.name)}</h3><div class="meta num">${fmt(b.total_rows)} row${b.total_rows === 1 ? '' : 's'} read</div></div>
        <button type="button" class="icon-btn" id="removeBatch" aria-label="Remove this file" title="Remove">${icon('x', 18)}</button>
      </div>
      <div class="chips">
        <span class="chip ${nothing ? 'warn' : 'good'}">${fmt(matched)} ready to check</span>
        ${b.unmatched_count ? `<span class="chip warn">${fmt(b.unmatched_count)} not in the customer list (will be skipped)</span>` : ''}
        ${out.problem_count ? `<span class="chip warn">${fmt(out.problem_count)} with problems (will be skipped)</span>` : ''}
      </div>
      ${nothing ? `<div class="problems"><div><b>There is nothing to check in this file.</b> The engine can only check customers that exist in its data, and none of these emails do. Use emails from the customer list, or <a href="/api/template.csv" download>download the template</a> for a working example.</div></div>` : ''}
      ${unmatched.length ? `<div class="problems">${unmatched.slice(0, 3).map((u) => `<div>${esc(u.case_id)} · ${esc(u.email)}: ${esc(u.reason)}</div>`).join('')}${b.unmatched_count > 3 ? `<div>…and ${b.unmatched_count - 3} more</div>` : ''}</div>` : ''}
      ${probs.length ? `<div class="problems">${probs.slice(0, 5).map((p) => `<div>Line ${p.line}${p.case_id ? ` · ${esc(p.case_id)}` : ''}: ${esc(p.message)}</div>`).join('')}${out.problem_count > 5 ? `<div>…and ${out.problem_count - 5} more</div>` : ''}</div>` : ''}
      <div class="table-wrap"><table class="mini-table"><thead><tr><th>Case</th><th>Email</th><th>Said</th><th>Request</th></tr></thead><tbody>
        ${out.preview.map((r) => `<tr><td>${esc(r.case_id)}</td><td>${esc(r.email)}</td><td>${esc(REPORTED[r.reported_status] || r.reported_status)}</td><td>${esc(r.request_text)}</td></tr>`).join('')}
      </tbody></table></div>
    </div>`;
  $('#removeBatch').addEventListener('click', async () => {
    const id = state.batch?.id; state.batch = null; el.hidden = true; el.innerHTML = ''; $('#uploadEmpty').hidden = false; renderSetup();
    if (id) { try { await api(`/api/batches/${id}`, { method: 'DELETE' }); } catch { /* already gone */ } }
  });
}

/* ================================================================== running a check */
const RING_C = 2 * Math.PI * 44;
const progress = new Spring(0, { response: 0.55 });
$('#ringFg').style.strokeDasharray = `${RING_C}`;
$('#runBtn').addEventListener('click', () => startRun());

async function startRun() {
  if (state.running) return;
  const batchId = state.mode === 'builtin' ? 'builtin' : state.batch?.id; if (!batchId) return;
  state.running = true; renderSetup();
  try {
    const { job } = await api('/api/jobs', { method: 'POST', body: JSON.stringify({ batch_id: batchId, use_readings: state.useReadings }), headers: { 'Content-Type': 'application/json' } });
    await showRunning(job); await followJob(job.id);
  } catch (err) {
    state.running = false; toast(err.message); showSetup(); renderSetup();
  }
}
async function showRunning(job) {
  progress.x = 0; progress.v = 0; progress.t = 0; paintProgress(0);
  $('#runBatchName').textContent = state.mode === 'builtin' ? 'the built-in batch' : (state.batch?.name || 'your file');
  $('#stageList').innerHTML = job.stages.map((label, i) => `
    <li class="stage" data-i="${i}"><span class="ico"><svg viewBox="0 0 24 24"><circle class="circle" cx="12" cy="12" r="9.5"/><path class="tick" d="M7.6 12.4l3 3 5.8-6.2"/></svg></span><span>${esc(label)}</span></li>`).join('');
  swap($('#setup'), $('#running'));
  $('#runCard').scrollIntoView({ behavior: reduce.matches ? 'auto' : 'smooth', block: 'center' });
}
function showSetup() { swap($('#running'), $('#setup')); }
async function swap(from, to) {
  if (from.hidden === false) { from.style.transition = 'opacity .25s, transform .3s'; from.style.opacity = '0'; from.style.transform = 'scale(.985)'; await sleep(reduce.matches ? 0 : 220); from.hidden = true; from.style.opacity = from.style.transform = from.style.transition = ''; }
  to.hidden = false;
}
function paintProgress(x) {
  const p = clamp(x, 0, 1);
  $('#ringFg').style.strokeDashoffset = `${RING_C * (1 - p)}`;
  $('#barFill').style.transform = `scaleX(${p})`;
  const pct = Math.round(p * 100); $('#ringNum').textContent = `${pct}%`; $('#ringWrap').setAttribute('aria-valuenow', String(pct));
}
function paintStages(job) {
  let queued = 0;                                  // steps that finish together tick off one after another
  $$('#stageList .stage').forEach((li) => {
    const i = Number(li.dataset.i), done = job.state === 'done' || i < job.stage, active = job.state === 'running' && i === job.stage;
    if (done && !li.classList.contains('done')) li.style.setProperty('--td', `${queued++ * 110}ms`);
    li.classList.toggle('done', done); li.classList.toggle('active', active);
  });
  $('#runStage').textContent = job.state === 'done' ? 'All done' : job.stage_label;
  $('#runMsg').textContent = job.message || '';
}
async function followJob(id) {
  for (;;) {
    let job;
    try { job = await api(`/api/jobs/${id}`); } catch { await sleep(600); continue; }
    paintStages(job); progress.to(job.state === 'done' ? 1 : job.progress, paintProgress);
    if (job.state === 'done') { await sleep(reduce.matches ? 0 : 1100); return finish(job); }
    if (job.state === 'error') { state.running = false; showSetup(); renderSetup(); showRunError(job); return; }
    await sleep(220);
  }
}
function showRunError(job) {
  const skipped = job.result?.skipped || [];
  const why = skipped.slice(0, 4).map((s) => `${esc(s.case_id)}: ${esc(s.reason)}`).join('<br>');
  showBanner('bad', `<span><b>That run did not finish.</b> ${esc(job.message)}${why ? `<br>${why}${skipped.length > 4 ? `<br>…and ${skipped.length - 4} more` : ''}` : ''}</span>`);
  window.scrollTo({ top: 0, behavior: reduce.matches ? 'auto' : 'smooth' });
}
async function finish(job) {
  state.running = false; state.job = job; state.filter = 'all'; state.query = ''; state.shown = 40;
  showBanner(); await swap($('#running'), $('#setup')); renderSetup();
  renderResults(job); loadHistory();
  await sleep(120);
  $('#results').scrollIntoView({ behavior: reduce.matches ? 'auto' : 'smooth', block: 'start' });
}

/* ================================================================== results */
function barRows(items, labels, cls = '') {
  const max = Math.max(1, ...items.map((i) => i.count));
  return items.map((it) => `
    <div class="bar-row"><span class="name">${esc(labels[it.operation] || sysName(it.system))}</span>
      <span class="track"><i class="fill ${cls}" data-bar="${(it.count / max).toFixed(4)}"></i></span>
      <span class="val num">${fmt(it.count)}</span></div>`).join('');
}
function renderResults(job) {
  const r = job.result, t = r.totals, el = $('#results');
  const total = t.complete + t.incomplete + t.not_applicable;
  const pct = (n) => total ? `${Math.round((n / total) * 100)}% of requests` : '';
  const C = 2 * Math.PI * 70;
  const claims = r.claims, claimPct = claims.said_complete ? claims.still_has_data / claims.said_complete : 0;
  const sk = r.skipped || [], att = r.attention, pr = r.practice;
  const notes = [];
  if (sk.length) notes.push(['', `<b>${fmt(sk.length)} request${sk.length === 1 ? ' was' : 's were'} set aside</b> because they could not be matched safely. ${esc(sk.slice(0, 2).map((s) => `${s.case_id}: ${s.reason}`).join(' '))} <span class="hint">The full list is in “Skipped requests”.</span>`, '!']);
  if (att.no_identifiable_resource.length) notes.push(['', `<b>${att.no_identifiable_resource.length} case${att.no_identifiable_resource.length === 1 ? '' : 's'} with nothing to check</b> (${esc(att.no_identifiable_resource.slice(0, 4).join(', '))}). No usable evidence was found for these people, so they are marked really done with no steps. Take a closer look.`, '!']);
  if (att.left_out) notes.push(['', `<b>${fmt(att.left_out)} record${att.left_out === 1 ? '' : 's'} could not be judged.</b> They belong to a case, but their state on the check date can’t be known from the evidence, so they are left out of the answer.`, '!']);
  if (att.contract_problem_count) notes.push(['', `<b>${att.contract_problem_count} answer${att.contract_problem_count === 1 ? '' : 's'} failed the engine’s own checks.</b> ${esc((att.contract_problems || []).slice(0, 2).join(' '))}`, '!']);
  notes.push(['ok', job.use_readings
    ? (att.readings_used ? `<b>${att.readings_used} status${att.readings_used === 1 ? '' : 'es'} came from screenshot readings</b> (out of ${att.readings_available} available).` : `<b>Screenshot readings were on,</b> but none applied to these requests.`)
    : `<b>Screenshot readings were switched off</b> for this run.`, '✓']);
  if (!att.contract_problem_count) notes.push(['ok', '<b>Every answer passed the engine’s own checks.</b>', '✓']);

  const dl = r.files.map((f, i) => {
    const primary = f.name === 'output.csv';
    const ico = f.name.endsWith('.zip') ? 'zip' : 'doc';
    return `<a class="dl ${primary ? 'primary' : ''}" href="/api/jobs/${job.id}/download/${f.name}" download>
      <span class="dl-ico">${icon(ico, 22)}</span><b>${esc(f.label)}</b><span>${esc(f.description)}</span><small>${esc(f.name)} · ${bytes(f.size)}</small>
      <span class="get">${icon('download', 20)}</span></a>`;
  }).join('');
  const subm = (state.status?.submission_files || []).map((n) => `
    <a class="dl" href="/api/submission/${n}" download><span class="dl-ico">${icon(n.endsWith('.zip') ? 'zip' : 'doc', 22)}</span><b>${n === 'code.zip' ? 'Code bundle' : 'Chat transcript'}</b>
      <span>${n === 'code.zip' ? 'The runnable solution, ready to submit' : 'The development conversation log'}</span><small>${n}</small><span class="get">${icon('download', 20)}</span></a>`).join('');

  el.hidden = false;
  el.innerHTML = `
    <div class="section-head" data-reveal>
      <div><h2>Results</h2><p>${esc(r.batch.name)} · <span class="num">${fmt(r.batch.ran)}</span> requests checked in <span class="num">${r.seconds}</span> seconds</p></div>
      <div class="btn-row"><button class="btn secondary" id="againBtn" type="button">${icon('refresh', 18)} Run again</button></div>
    </div>

    <div class="hero-stats">
      <div class="card donut-card" data-reveal>
        <div class="donut" data-donut="${t.complete},${t.incomplete},${t.not_applicable}">
          <svg viewBox="0 0 200 200" aria-hidden="true"><circle class="track" cx="100" cy="100" r="70"/>
            <circle class="seg" cx="100" cy="100" r="70" stroke="var(--green-fill)" stroke-linecap="butt" stroke-dasharray="0 ${C}"/>
            <circle class="seg" cx="100" cy="100" r="70" stroke="var(--orange-fill)" stroke-linecap="butt" stroke-dasharray="0 ${C}"/>
            <circle class="seg" cx="100" cy="100" r="70" stroke="var(--gray-fill)" stroke-linecap="butt" stroke-dasharray="0 ${C}"/></svg>
          <div class="center"><b class="num" data-count="${total}">0</b><span>requests</span></div>
        </div>
        <div class="legend">
          <div><i class="good"></i>Really done<b class="num">${fmt(t.complete)}</b></div>
          <div><i class="warn"></i>Something is left<b class="num">${fmt(t.incomplete)}</b></div>
          <div><i class="none"></i>Not a deletion request<b class="num">${fmt(t.not_applicable)}</b></div>
          <div style="margin-top:4px"><span class="hint">${fmt(t.steps)} steps in total · about ${t.avg_steps} per request</span></div>
        </div>
      </div>
      <div class="stat-trio">
        <div class="stat good" data-reveal><div class="label"><i></i>Really done</div><div class="big num" data-count="${t.complete}">0</div><div class="share">${pct(t.complete)}</div></div>
        <div class="stat warn" data-reveal><div class="label"><i></i>Something left</div><div class="big num" data-count="${t.incomplete}">0</div><div class="share">${pct(t.incomplete)}</div></div>
        <div class="stat none" data-reveal><div class="label"><i></i>Not applicable</div><div class="big num" data-count="${t.not_applicable}">0</div><div class="share">${pct(t.not_applicable)}</div></div>
      </div>
    </div>

    <div class="insights">
      <div class="card insight wide" data-reveal>
        <div class="claim">
          <div class="ring-wrap" aria-hidden="true"><svg viewBox="0 0 100 100"><circle class="ring-bg" cx="50" cy="50" r="44"/><circle class="ring-fg" cx="50" cy="50" r="44" data-ring="${claimPct.toFixed(4)}"/></svg>
            <div class="ring-num num" data-count="${Math.round(claimPct * 100)}" data-suffix="%">0%</div></div>
          <div>
            <h3>Claims that did not hold up</h3>
            ${claims.said_complete
              ? `<p class="big" style="margin-top:6px">The company’s system said <b class="num">${fmt(claims.said_complete)}</b> of these requests were complete. In <b class="num">${fmt(claims.still_has_data)}</b> of them, <b>personal data is still there or could come back.</b></p>`
              : `<p class="sub">None of these requests were reported as complete, so there is nothing to compare.</p>`}
          </div>
        </div>
      </div>
      <div class="card insight" data-reveal>
        <h3>What was found</h3><p class="sub">Problems that still exist, across all requests.</p>
        ${r.findings.length ? `<div class="bars">${barRows(r.findings, FINDING_BARS, 'o')}</div>` : '<p class="empty">Nothing was found.</p>'}
      </div>
      <div class="card insight" data-reveal>
        <h3>Where it is hiding</h3><p class="sub">The systems that still hold someone’s data.</p>
        ${r.systems.length ? `<div class="bars">${barRows(r.systems, {}, '')}</div>` : '<p class="empty">No system holds leftover data.</p>'}
      </div>
      <div class="card insight" data-reveal>
        <h3>What needs to be done</h3><p class="sub">The fixes in the plan, by type.</p>
        ${r.fixes.length ? `<div class="bars">${barRows(r.fixes, FIX_BARS, 'g')}</div>` : '<p class="empty">No fixes are needed.</p>'}
      </div>
      <div class="card insight" data-reveal>
        <h3>How accurate is it?</h3><p class="sub">Measured on ${pr.cases} practice cases that come with the correct answers.</p>
        <div class="score-grid">
          <div class="score"><b class="num">${pr.status_correct}/${pr.cases}</b><span>verdicts correct</span></div>
          <div class="score"><b class="num">${pr.exact}/${pr.cases}</b><span>cases exactly right</span></div>
          <div class="score"><b class="num">${Math.round(pr.precision * 100)}%</b><span>of its steps were correct</span></div>
          <div class="score"><b class="num">${Math.round(pr.recall * 100)}%</b><span>of the expected steps were found</span></div>
        </div>
        <p class="hint" style="margin-top:14px">There are no correct answers for new requests, so this is the best available measure.</p>
      </div>
      <div class="card insight wide" data-reveal>
        <h3>Worth a closer look</h3><p class="sub">Things the engine could not settle on its own.</p>
        <div class="notes">${notes.map(([cls, html, ic]) => `<div class="note ${cls}"><span class="ni">${ic}</span><span>${html}</span></div>`).join('')}</div>
      </div>
    </div>

    <div class="section-head" data-reveal><div><h2>Download</h2><p>Everything this run produced.</p></div></div>
    <div class="card" data-reveal>
      <div class="downloads">${dl}</div>
      ${subm ? `<div class="sub-head">Submission files</div><div class="downloads">${subm}</div>` : ''}
    </div>

    <div class="section-head" data-reveal><div><h2>Every request</h2><p>Open any request to see what was found, what to fix, and how to check it.</p></div></div>
    <div class="card" data-reveal>
      <div class="tools">
        <label class="search"><span class="sr-only">Search requests</span>${icon('search', 18)}<input type="search" id="caseSearch" placeholder="Search by case, email or finding" autocomplete="off"></label>
        <div class="filters" id="caseFilters" role="group" aria-label="Filter by result"></div>
      </div>
      <ul class="cases" id="caseList"></ul>
    </div>`;
  $('#againBtn').addEventListener('click', () => { window.scrollTo({ top: 0, behavior: reduce.matches ? 'auto' : 'smooth' }); setTimeout(() => $('#runBtn').focus({ preventScroll: true }), 400); });
  $('#caseSearch').addEventListener('input', (e) => { state.query = e.target.value.trim().toLowerCase(); state.shown = 40; renderCases(); });
  renderFilters(); renderCases(); reveal(el);
}

/* ---------- case explorer ---------- */
function renderFilters() {
  const cases = state.job.result.cases, count = (s) => cases.filter((c) => c.status === s).length;
  const defs = [['all', 'All', cases.length], ['INCOMPLETE', 'Something left', count('INCOMPLETE')], ['COMPLETE', 'Really done', count('COMPLETE')], ['NOT_APPLICABLE', 'Not applicable', count('NOT_APPLICABLE')], ['MISMATCH', 'Said complete, isn’t', cases.filter((c) => c.reported === 'COMPLETE' && c.status === 'INCOMPLETE').length]];
  $('#caseFilters').innerHTML = defs.map(([key, label, n]) => `<button type="button" class="filter" data-f="${key}" aria-pressed="${state.filter === key}">${label}<span class="n">${fmt(n)}</span></button>`).join('');
  $$('#caseFilters .filter').forEach((b) => b.addEventListener('click', () => { state.filter = b.dataset.f; state.shown = 40; $$('#caseFilters .filter').forEach((x) => x.setAttribute('aria-pressed', String(x === b))); renderCases(); }));
}
function matching() {
  const q = state.query;
  return state.job.result.cases.filter((c) => {
    if (state.filter === 'MISMATCH') { if (!(c.reported === 'COMPLETE' && c.status === 'INCOMPLETE')) return false; }
    else if (state.filter !== 'all' && c.status !== state.filter) return false;
    return !q || c.id.toLowerCase().includes(q) || c.email.toLowerCase().includes(q) || c.headline.toLowerCase().includes(q);
  });
}
function renderCases() {
  const list = $('#caseList'), all = matching(), shown = all.slice(0, state.shown);
  if (!all.length) { list.innerHTML = '<li class="no-results">No requests match.</li>'; return; }
  list.innerHTML = shown.map((c, i) => {
    const alert = c.reported === 'COMPLETE' && c.status === 'INCOMPLETE';
    return `<li class="case ${sClass(c.status)}" data-id="${esc(c.id)}" style="--i:${Math.min(i, 14)}">
      <button type="button" class="case-row" aria-expanded="false"><span class="dot"></span><span class="case-id">${esc(c.id)}</span><span class="case-head">${esc(c.headline)}</span>
        <span class="case-tag ${alert ? 'alert' : ''}">${alert ? 'Said complete — isn’t' : esc(REPORTED[c.reported] || c.reported)}</span><span class="chev">${icon('chev', 18)}</span></button>
      <div class="case-body"><div><div class="case-inner"><div class="loading-line">Loading…</div></div></div></div></li>`;
  }).join('') + (all.length > shown.length ? `<li class="more-row"><button type="button" class="btn secondary small" id="moreBtn">Show ${Math.min(60, all.length - shown.length)} more <span class="hint">(${fmt(all.length - shown.length)} left)</span></button></li>` : '');
  $$('.case', list).forEach((li) => li.querySelector('.case-row').addEventListener('click', () => toggleCase(li)));
  $('#moreBtn')?.addEventListener('click', () => { state.shown += 60; renderCases(); });
}
async function toggleCase(li) {
  const open = !li.classList.contains('open');
  li.classList.toggle('open', open); li.querySelector('.case-row').setAttribute('aria-expanded', String(open));
  if (!open || li.dataset.loaded) return;
  try {
    const d = await api(`/api/jobs/${state.job.id}/cases/${encodeURIComponent(li.dataset.id)}`);
    li.querySelector('.case-inner').innerHTML = caseDetail(d); li.dataset.loaded = '1';
  } catch (err) { li.querySelector('.case-inner').innerHTML = `<div class="loading-line">${esc(err.message)}</div>`; }
}
function caseDetail(d) {
  const date = (iso) => new Date(iso).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' });
  const groups = { found: [], fix: [], check: [] };
  for (const s of d.steps) { const [g, text] = OPS[s.operation] || ['check', s.operation]; groups[g].push({ s, text }); }
  const phase = (key, title, items) => items.length ? `<div class="phase ${key}"><h5><i></i>${title}</h5><ol class="steps">${items.map(({ s, text }) => `
      <li class="stepline"><span class="no num">${s.step_no}</span><span class="what">${esc(text)}</span>
      <span class="tagline"><span class="tag">${esc(s.resource_id)}</span><span class="tag">${esc(sysName(s.system_id))}</span>${s.evidence_id ? `<span class="tag" title="Evidence this is based on">${esc(s.evidence_id)}</span>` : ''}</span></li>`).join('')}</ol></div>` : '';
  const why = d.status === 'NOT_APPLICABLE' ? `<p class="quote">This was not treated as a deletion request (${esc(d.note.replace(/^different request \((.*)\)$/, '“$1” found in the message').replace(/^asks to keep or not delete the account$/, 'it asks to keep the account'))}).</p>`
    : d.steps.length === 0 ? '<p class="quote">There was nothing identifiable to check for this person in the evidence available on the check date.</p>' : '';
  return `<p class="quote">“${esc(d.request_text)}”</p>
    <div class="kv"><span><b>Email</b> ${esc(d.email)}</span><span><b>System said</b> ${esc(REPORTED[d.reported_status] || d.reported_status)}</span><span><b>Asked on</b> ${date(d.requested_at)}</span><span><b>Checked as of</b> ${date(d.audit_at)}</span></div>
    ${why}${phase('found', 'What we found', groups.found)}${phase('fix', 'What to fix, in this order', groups.fix)}${phase('check', d.status === 'COMPLETE' ? 'How we know' : 'Check afterwards', groups.check)}`;
}

/* ================================================================== recent runs */
async function loadHistory() {
  try {
    const { jobs } = await api('/api/jobs');
    state.history = jobs.filter((j) => j.state === 'done');
    const wrap = $('#recentWrap'), list = $('#recentList');
    wrap.hidden = !state.history.length;
    list.innerHTML = state.history.map((j) => `
      <button type="button" class="recent-item" data-id="${j.id}">
        <div><b>${esc(j.batch_name)}</b><span>${ago(j.created)} · ${fmt(j.ran)} requests${j.use_readings ? '' : ' · readings off'}</span></div>
        <div class="recent-counts"><span class="rc g">${fmt(j.counts.complete)}</span><span class="rc o">${fmt(j.counts.incomplete)}</span><span class="rc n">${fmt(j.counts.not_applicable)}</span></div>
      </button>`).join('');
    $$('.recent-item', list).forEach((b) => b.addEventListener('click', () => openJob(b.dataset.id)));
  } catch { /* history is optional */ }
}
function ago(iso) {
  const s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (s < 60) return 'just now'; if (s < 3600) return `${Math.floor(s / 60)} min ago`; if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
async function openJob(id) {
  try {
    const job = await api(`/api/jobs/${id}`); state.job = job; state.filter = 'all'; state.query = ''; state.shown = 40;
    renderResults(job); await sleep(80); $('#results').scrollIntoView({ behavior: reduce.matches ? 'auto' : 'smooth', block: 'start' });
  } catch (err) { toast(err.message); }
}

/* ================================================================== start */
(async function init() {
  setMode('builtin'); renderSetup(); positionThumb();
  const st = await pollStatus();
  loadHistory();
  const params = new URLSearchParams(location.search);
  if (params.get('autorun') === '1') {                         // used for quick demos and screenshots
    while (!state.status?.ready) await sleep(300);
    startRun();
  }
  void st;
})();
})();
