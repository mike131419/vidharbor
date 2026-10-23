'use strict';

const $ = (id) => document.getElementById(id);
const store = {
  get(k, d) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

const state = {
  mode: store.get('vh.mode', 'video'),
  files: new Map(),      // job id -> File ready for the share sheet
  preparing: new Set(),
  els: new Map(),        // job id -> <li>
  pollTimer: null,
  signedIn: false,
};

const isIOS = /iPad|iPhone|iPod/.test(navigator.userAgent) ||
  (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const standalone = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone === true;
const canShareFiles = (() => {
  try {
    return !!(navigator.canShare && navigator.canShare({ files: [new File(['x'], 'x.mp4', { type: 'video/mp4' })] }));
  } catch { return false; }
})();

// ---------------------------------------------------------------- helpers
function show(view) {
  for (const id of ['loading', 'login', 'offline', 'app']) $(id).classList.toggle('hidden', id !== view);
  $('menuBtn').classList.toggle('hidden', view !== 'app');
}

let toastTimer;
function toast(msg, ms = 3000) {
  const t = $('toast');
  t.textContent = msg;
  t.classList.remove('hidden');
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.classList.add('hidden'), ms);
}

function fmtBytes(n) {
  if (!n) return '';
  const u = ['B', 'KB', 'MB', 'GB'];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtEta(s) {
  if (s == null) return '';
  s = Math.round(s);
  return s >= 60 ? `${Math.floor(s / 60)}m ${s % 60}s left` : `${s}s left`;
}

class AuthError extends Error {}
class WakingError extends Error {}   // the host answered, but VidHarbor isn't up yet

async function api(path, opts = {}) {
  const res = await fetch(path, {
    credentials: 'same-origin',
    headers: opts.body ? { 'Content-Type': 'application/json' } : {},
    ...opts,
    body: opts.body ? JSON.stringify(opts.body) : undefined,
  });
  // Free cloud hosts sleep when idle and reply with their own "starting" page
  // while waking up; only our server sets this header.
  if (!res.headers.get('X-VidHarbor')) throw new WakingError(`host replied ${res.status}`);
  if (res.status === 401) throw new AuthError('signed out');
  let data = {};
  try { data = await res.json(); } catch { /* empty */ }
  if (!res.ok) throw Object.assign(new Error(data.error || `Error ${res.status}`), { status: res.status });
  return data;
}

// ---------------------------------------------------------------- start up
async function boot() {
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('sw.js').catch(() => {});
  setMode(state.mode);
  $('quality').value = store.get('vh.quality', '1080');

  // Shared from another app (Android share sheet, or an iOS Shortcut: /?text=...)
  const params = new URLSearchParams(location.search);
  const shared = [params.get('text'), params.get('url'), params.get('title')].filter(Boolean).join(' ');
  if (shared) {
    $('text').value = shared;
    history.replaceState(null, '', location.pathname);
  }

  show('loading');
  const wakeHint = setTimeout(() => $('wakeMsg').classList.remove('hidden'), 2500);
  const deadline = Date.now() + 120000;   // a sleeping free server takes about a minute
  try {
    for (;;) {
      try {
        await api('/api/me');
        enterApp(!!shared);
        return;
      } catch (e) {
        if (e instanceof AuthError) return show('login');
        if (Date.now() > deadline) return show('offline');
        await new Promise((r) => setTimeout(r, 3000));
      }
    }
  } finally {
    clearTimeout(wakeHint);
    $('wakeMsg').classList.add('hidden');
  }
}

function enterApp(autoSubmit = false) {
  state.signedIn = true;
  show('app');
  const dismissed = store.get('vh.installTipClosed', '') === '1';
  $('installTip').classList.toggle('hidden', !(isIOS && !standalone && !dismissed));
  refresh();
  if (autoSubmit && $('text').value.trim()) submit();
}

// ---------------------------------------------------------------- sign in
$('loginForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const err = $('loginErr');
  err.classList.add('hidden');
  const btn = e.submitter || $('loginForm').querySelector('button');
  btn.disabled = true;
  try {
    await api('/api/login', { method: 'POST', body: { code: $('code').value } });
    $('code').value = '';
    enterApp(!!$('text').value.trim());
  } catch (ex) {
    err.textContent = ex.status ? ex.message : "Can't reach VidHarbor. Check your connection.";
    err.classList.remove('hidden');
  } finally {
    btn.disabled = false;
  }
});

$('menuBtn').addEventListener('click', async () => {
  if (!confirm('Sign out of VidHarbor on this phone?')) return;
  try { await api('/api/logout', { method: 'POST' }); } catch { /* ignore */ }
  state.signedIn = false;
  clearTimeout(state.pollTimer);
  $('jobs').replaceChildren();
  state.els.clear();
  show('login');
});

$('retryConn').addEventListener('click', boot);
$('installClose').addEventListener('click', () => {
  $('installTip').classList.add('hidden');
  store.set('vh.installTipClosed', '1');
});

// ---------------------------------------------------------------- add downloads
function setMode(mode) {
  state.mode = mode;
  store.set('vh.mode', mode);
  for (const b of document.querySelectorAll('.seg button')) {
    b.setAttribute('aria-checked', String(b.dataset.mode === mode));
  }
  $('qualityRow').classList.toggle('hidden', mode !== 'video');
}
for (const b of document.querySelectorAll('.seg button')) b.addEventListener('click', () => setMode(b.dataset.mode));
$('quality').addEventListener('change', () => store.set('vh.quality', $('quality').value));

$('pasteBtn').addEventListener('click', async () => {
  try {
    const text = await navigator.clipboard.readText();
    if (!text.trim()) return toast('The clipboard is empty. Copy a link first.');
    $('text').value = text;
  } catch {
    $('text').focus();
    toast('Press and hold in the box, then tap Paste.');
  }
});
$('clearBtn').addEventListener('click', () => { $('text').value = ''; $('text').focus(); });

$('addForm').addEventListener('submit', (e) => { e.preventDefault(); submit(); });

async function submit() {
  const err = $('addErr');
  err.classList.add('hidden');
  const text = $('text').value.trim();
  if (!text) {
    err.textContent = 'Paste a link or a share message first.';
    err.classList.remove('hidden');
    return;
  }
  $('goBtn').disabled = true;
  try {
    await api('/api/jobs', { method: 'POST', body: { text, mode: state.mode, quality: $('quality').value } });
    $('text').value = '';
    document.activeElement?.blur();
    refresh();
  } catch (ex) {
    if (ex instanceof AuthError) return show('login');
    err.textContent = ex.status ? ex.message : "Can't reach VidHarbor. Check your connection.";
    err.classList.remove('hidden');
  } finally {
    $('goBtn').disabled = false;
  }
}

// ---------------------------------------------------------------- job list
async function refresh() {
  clearTimeout(state.pollTimer);
  if (!state.signedIn) return;
  let jobs = null;
  try {
    jobs = (await api('/api/jobs')).jobs;
  } catch (ex) {
    if (ex instanceof AuthError) { state.signedIn = false; return show('login'); }
  }
  if (jobs) render(jobs);
  const busy = jobs && jobs.some((j) => j.state === 'queued' || j.state === 'running');
  if (!document.hidden) state.pollTimer = setTimeout(refresh, busy ? 1000 : 5000);
}

document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });

function render(jobs) {
  const list = $('jobs');
  const seen = new Set();
  jobs.forEach((j, i) => {
    seen.add(j.id);
    let li = state.els.get(j.id);
    if (!li) {
      li = $('jobTpl').content.firstElementChild.cloneNode(true);
      li.querySelector('.remove').addEventListener('click', () => removeJob(j.id));
      state.els.set(j.id, li);
    }
    if (list.children[i] !== li) list.insertBefore(li, list.children[i] || null);
    update(li, j);
  });
  for (const [id, li] of state.els) {
    if (!seen.has(id)) { li.remove(); state.els.delete(id); state.files.delete(id); }
  }
  $('empty').classList.toggle('hidden', jobs.length > 0);
}

function update(li, j) {
  li.className = `job s-${j.state}`;
  li.querySelector('.chip').textContent = j.platform;
  li.querySelector('.kind').textContent = j.mode === 'mp3' ? 'MP3' : 'Video';
  li.querySelector('.title').textContent = j.title || j.url;

  const bar = li.querySelector('.bar');
  const active = j.state === 'queued' || j.state === 'running';
  bar.classList.toggle('indeterminate', active && j.percent == null);
  li.querySelector('.fill').style.width = j.state === 'done' ? '100%' : `${j.percent || 0}%`;

  let status = j.status;
  if (j.state === 'running' && j.percent != null) {
    status = [`${Math.round(j.percent)}%`, j.speed ? `${fmtBytes(j.speed)}/s` : '', fmtEta(j.eta)].filter(Boolean).join(' · ');
  } else if (j.state === 'done' && j.file) {
    status = `Ready · ${fmtBytes(j.file.size)}`;
  }
  li.querySelector('.status').textContent = status;

  const err = li.querySelector('.error');
  err.textContent = j.error || '';
  err.classList.toggle('hidden', !j.error);

  renderActions(li, j);
}

function renderActions(li, j) {
  const box = li.querySelector('.actions');
  const key = `${j.state}|${state.files.has(j.id)}|${state.preparing.has(j.id)}`;
  if (box.dataset.key === key) return;
  box.dataset.key = key;
  box.replaceChildren();

  if (j.state === 'done' && j.file) {
    const href = `/api/files/${j.id}`;
    if (canShareFiles && j.file.shareable) {
      const save = document.createElement('button');
      save.type = 'button';
      save.className = 'primary';
      save.textContent = j.mode === 'mp3' ? 'Save to Files' : 'Save video';
      if (state.files.has(j.id)) {
        save.addEventListener('click', () => shareFile(j));
      } else {
        save.disabled = true;
        save.textContent = 'Preparing…';
        prepare(j);
      }
      box.append(save);
    }
    const a = document.createElement('a');
    a.className = `button ${canShareFiles && j.file.shareable ? 'secondary' : 'primary'}`;
    a.href = href;
    a.download = j.file.name;
    a.textContent = 'Download';
    box.append(a);
  } else if (j.state === 'error' || j.state === 'cancelled') {
    const retry = document.createElement('button');
    retry.type = 'button';
    retry.className = 'secondary';
    retry.textContent = 'Try again';
    retry.addEventListener('click', async () => {
      try { await api(`/api/jobs/${j.id}/retry`, { method: 'POST' }); refresh(); }
      catch (ex) { toast(ex.message); }
    });
    box.append(retry);
  }
}

// iOS only allows the share sheet straight from a tap, so the file is fetched
// in advance; the Save tap then opens the sheet immediately.
async function prepare(j) {
  if (state.preparing.has(j.id) || state.files.has(j.id)) return;
  state.preparing.add(j.id);
  try {
    const res = await fetch(`/api/files/${j.id}`, { credentials: 'same-origin' });
    if (!res.ok) throw new Error(`Error ${res.status}`);
    const blob = await res.blob();
    state.files.set(j.id, new File([blob], j.file.name, { type: j.file.type || blob.type }));
  } catch {
    // the Download link still works
  } finally {
    state.preparing.delete(j.id);
    const li = state.els.get(j.id);
    if (li) { li.querySelector('.actions').dataset.key = ''; renderActions(li, j); }
  }
}

async function shareFile(j) {
  const file = state.files.get(j.id);
  if (!file) return;
  try {
    await navigator.share({ files: [file] });
    if (j.mode !== 'mp3' && isIOS) toast('Tip: choose “Save Video” to put it in Photos.');
  } catch (ex) {
    if (ex && ex.name === 'AbortError') return;
    toast('Sharing failed. Use Download instead.');
  }
}

async function removeJob(id) {
  try {
    await api(`/api/jobs/${id}`, { method: 'DELETE' });
  } catch (ex) {
    if (ex instanceof AuthError) return show('login');
  }
  state.files.delete(id);
  refresh();
}

boot();
