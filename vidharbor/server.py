"""Phone access: a small web server that serves the VidHarbor phone app (a PWA)
and runs downloads on this computer for signed-in phones.

Runs inside the desktop app (Phone access dialog) or headless:
    python -m vidharbor.server --port 8787 --code MYCODE
"""
from __future__ import annotations

import hashlib
import hmac
import json
import mimetypes
import os
import re
import secrets
import shutil
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import quote, urlsplit

from . import __version__, engine
from .core import Events, Job, Options, Runner
from .linkparse import detect_platform, extract_urls

WEB_DIR = Path(__file__).resolve().parent / 'web'
COOKIE = 'vh_token'
MAX_ACTIVE_PER_USER = 4
MAX_LINKS_PER_REQUEST = 10
SAVE_SHEET_LIMIT = 150 * 1024 * 1024   # above this the app offers a plain download instead
mimetypes.add_type('application/manifest+json', '.webmanifest')
mimetypes.add_type('audio/mp4', '.m4a')
mimetypes.add_type('text/javascript', '.js')


def new_access_code() -> str:
    """Easy to read and type on a phone: 3 groups of 4, no look-alike characters."""
    alphabet = 'ABCDEFGHJKMNPQRSTUVWXYZ23456789'
    return '-'.join(''.join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3))


def _norm_code(code: str) -> str:
    return re.sub(r'[\s-]+', '', code or '').upper()


def _code_hash(code: str) -> str:
    return hashlib.sha256(('vidharbor:' + _norm_code(code)).encode()).hexdigest()


# ------------------------------------------------------------------ sign-ins
class TokenStore:
    """Signed-in phones. Tokens survive restarts; changing the access code
    signs everyone out."""

    def __init__(self, path: Path, code: str):
        self.path, self.lock = path, threading.Lock()
        self.code_hash = _code_hash(code)
        try:
            data = json.loads(path.read_text('utf-8'))
            self.tokens = data['tokens'] if data.get('code') == self.code_hash else {}
        except (OSError, ValueError, KeyError):
            self.tokens = {}
        self._save()

    def _save(self):
        tmp = self.path.with_suffix('.tmp')
        tmp.write_text(json.dumps({'code': self.code_hash, 'tokens': self.tokens}), 'utf-8')
        os.replace(tmp, self.path)

    def issue(self, label: str) -> str:
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.tokens[token] = {'created': time.time(), 'label': label[:80], 'seen': time.time()}
            self._save()
        return token

    def check(self, token: str | None) -> bool:
        if not token:
            return False
        with self.lock:
            info = self.tokens.get(token)
            if info and time.time() - info.get('seen', 0) > 3600:
                info['seen'] = time.time()
                self._save()
            return info is not None

    def revoke(self, token: str):
        with self.lock:
            if self.tokens.pop(token, None) is not None:
                self._save()

    def revoke_all(self):
        with self.lock:
            self.tokens.clear()
            self._save()

    def count(self) -> int:
        return len(self.tokens)


class LoginLimiter:
    """Slow down code guessing: per client and overall."""

    def __init__(self, per_client=8, overall=40, window=600):
        self.per_client, self.overall, self.window = per_client, overall, window
        self.fails: dict[str, list[float]] = {}
        self.lock = threading.Lock()

    def _recent(self, key):
        now = time.time()
        lst = [t for t in self.fails.get(key, []) if now - t < self.window]
        self.fails[key] = lst
        return lst

    def blocked(self, client: str) -> bool:
        with self.lock:
            return len(self._recent(client)) >= self.per_client or len(self._recent('*')) >= self.overall

    def fail(self, client: str):
        with self.lock:
            for key in (client, '*'):
                self._recent(key).append(time.time())


# ------------------------------------------------------------------ jobs
@dataclass
class PhoneJob:
    job: Job
    owner: str
    mode: str
    quality: str = '1080'
    state: str = 'queued'        # queued | running | done | error | cancelled
    status: str = 'Waiting…'
    percent: float | None = None
    speed: float = 0
    eta: int | None = None
    error: str = ''
    created: float = field(default_factory=time.time)
    finished: float = 0

    def public(self) -> dict:
        path = Path(self.job.filepath) if self.job.filepath else None
        size = path.stat().st_size if path and path.is_file() else 0
        return {
            'id': self.job.id, 'url': self.job.url, 'title': self.job.title,
            'platform': self.job.platform.label, 'mode': self.mode, 'state': self.state,
            'status': self.status, 'percent': self.percent, 'speed': self.speed, 'eta': self.eta,
            'error': self.error, 'created': self.created,
            'file': {'name': path.name, 'size': size, 'type': _mime(path),
                     'shareable': size <= SAVE_SHEET_LIMIT} if size else None,
        }


def _mime(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or 'application/octet-stream'


class _JobEvents(Events):
    def __init__(self, server: 'PhoneServer'):
        self.s = server

    def _pj(self, job):
        return self.s.jobs.get(job.id)

    def status(self, job, text):
        if pj := self._pj(job):
            pj.state, pj.status = 'running', text

    def title(self, job, title):
        pass  # job.title is already set by the runner

    def progress(self, job, d):
        if pj := self._pj(job):
            total, done = d['total'], d['done']
            i, n = d.get('frag') or (None, None)
            pj.state = 'running'
            pj.percent = round(done * 100 / total, 1) if total else (round((i or 0) * 100 / n, 1) if n else None)
            pj.speed, pj.eta = d.get('speed') or 0, d.get('eta')
            pj.status = 'Downloading'

    def done(self, job, result, message, filepath):
        if pj := self._pj(job):
            pj.state = {'ok': 'done'}.get(result, result)
            pj.status = {'ok': 'Ready', 'cancelled': 'Cancelled'}.get(result, 'Failed')
            pj.error = message if result == 'error' else ''
            pj.percent = 100.0 if result == 'ok' else pj.percent
            pj.speed, pj.eta, pj.finished = 0, None, time.time()
        self.s.log(f'Phone #{job.id} {result}: {job.title or job.url}')

    def log(self, text):
        self.s.log_detail(text)


# ------------------------------------------------------------------ server
class PhoneServer:
    def __init__(self, *, port: int, access_code: str, options: Callable[[], Options],
                 before_download: Callable[[Job], None] | None = None,
                 log: Callable[[str], None] = print, log_detail: Callable[[str], None] | None = None,
                 keep_hours: float = 6, workers: int = 2, host: str = '0.0.0.0',
                 files_dir: Path | None = None, on_change: Callable[[], None] | None = None):
        self.port, self.host = port, host
        self.on_change = on_change or (lambda: None)   # e.g. a phone signed in
        self.options, self.before_download = options, before_download
        self.log, self.log_detail = log, (log_detail or (lambda _t: None))
        self.keep_seconds = keep_hours * 3600
        self.files_dir = files_dir or (engine.data_dir() / 'phone-downloads')
        self.tokens = TokenStore(engine.data_dir() / 'phone-tokens.json', access_code)
        self.access_code = access_code
        self.limiter = LoginLimiter()
        self.jobs: dict[int, PhoneJob] = {}
        self.pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix='phone-dl')
        self.httpd: ThreadingHTTPServer | None = None
        self._stop = threading.Event()

    # --- lifecycle
    def start(self):
        handler = type('Handler', (_Handler,), {'app': self})
        self.httpd = ThreadingHTTPServer((self.host, self.port), handler)
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, name='phone-http', daemon=True).start()
        threading.Thread(target=self._janitor, name='phone-cleanup', daemon=True).start()
        self.log(f'Phone access running on port {self.port}')

    def stop(self):
        self._stop.set()
        for pj in self.jobs.values():
            pj.job.cancel.set()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
            self.httpd = None
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.log('Phone access stopped')

    @property
    def running(self) -> bool:
        return self.httpd is not None

    # --- jobs
    def _user_dir(self, token: str) -> Path:
        d = self.files_dir / hashlib.sha256(token.encode()).hexdigest()[:16]
        d.mkdir(parents=True, exist_ok=True)
        return d

    def add_jobs(self, token: str, text: str, mode: str, quality: str) -> tuple[list[dict], str]:
        urls = extract_urls(text)[:MAX_LINKS_PER_REQUEST]
        if not urls:
            return [], 'No link found. Paste a link or a whole share message.'
        active = sum(1 for p in self.jobs.values() if p.owner == token and p.state in ('queued', 'running'))
        if active + len(urls) > MAX_ACTIVE_PER_USER:
            return [], f'You can have up to {MAX_ACTIVE_PER_USER} downloads going at once. Wait for some to finish.'
        out = []
        for url in urls:
            out.append(self._submit(token, Job(url=url), mode, quality).public())
        return out, ''

    def _submit(self, token: str, job: Job, mode: str, quality: str) -> PhoneJob:
        mode = mode if mode in ('video', 'mp3') else 'video'
        quality = quality if quality in ('best', '1080', '720') else '1080'
        pj = PhoneJob(job=job, owner=token, mode=mode, quality=quality)
        self.jobs[job.id] = pj
        opts = self.options()
        opts.outdir = str(self._user_dir(token))
        opts.mode, opts.quality, opts.h264 = mode, quality, True   # H.264 plays on every phone
        opts.subfolders, opts.allow_playlist = False, False
        opts.template = '%(title).70B [%(id)s].%(ext)s'
        runner = Runner(job, opts, _JobEvents(self), phone=True, before_download=self.before_download)
        self.pool.submit(runner.run)
        self.log(f'Phone #{job.id} queued: {job.url}')
        return pj

    def retry(self, token: str, job_id: int) -> PhoneJob | None:
        old = self.jobs.get(job_id)
        if not old or old.owner != token or old.state in ('queued', 'running'):
            return None
        self.remove(token, job_id)
        return self._submit(token, Job(url=old.job.url), old.mode, old.quality)

    def remove(self, token: str, job_id: int) -> bool:
        pj = self.jobs.get(job_id)
        if not pj or pj.owner != token:
            return False
        pj.job.cancel.set()
        self.jobs.pop(job_id, None)
        if pj.job.filepath:
            try:
                os.remove(pj.job.filepath)
            except OSError:
                pass
        return True

    def list_jobs(self, token: str) -> list[dict]:
        return [p.public() for p in sorted(self.jobs.values(), key=lambda p: -p.created) if p.owner == token]

    def _janitor(self):
        while not self._stop.wait(300):
            self.cleanup()

    def cleanup(self):
        now = time.time()
        for jid, pj in list(self.jobs.items()):
            if pj.finished and now - pj.finished > self.keep_seconds:
                self.remove(pj.owner, jid)
        # files left over from earlier runs
        if self.files_dir.is_dir():
            for f in self.files_dir.rglob('*'):
                try:
                    if f.is_file() and now - f.stat().st_mtime > self.keep_seconds + 600:
                        f.unlink()
                except OSError:
                    pass

    def file_for(self, token: str, job_id: int) -> Path | None:
        pj = self.jobs.get(job_id)
        if not pj or pj.owner != token or pj.state != 'done' or not pj.job.filepath:
            return None
        p = Path(pj.job.filepath)
        return p if p.is_file() else None


# ------------------------------------------------------------------ HTTP
_STATIC = {'': 'index.html', 'index.html': 'index.html', 'app.js': 'app.js', 'styles.css': 'styles.css',
           'sw.js': 'sw.js', 'manifest.webmanifest': 'manifest.webmanifest',
           'icon-192.png': 'icon-192.png', 'icon-512.png': 'icon-512.png',
           'icon-maskable-512.png': 'icon-maskable-512.png', 'apple-touch-icon.png': 'apple-touch-icon.png',
           'favicon.png': 'icon-192.png'}
_SECURITY_HEADERS = {
    'X-Content-Type-Options': 'nosniff',
    'Referrer-Policy': 'no-referrer',
    'X-Frame-Options': 'DENY',
    'Content-Security-Policy': "default-src 'self'; img-src 'self' data: blob:; media-src 'self' blob:; "
                               "style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'",
}


class _Handler(BaseHTTPRequestHandler):
    app: PhoneServer
    server_version = 'VidHarbor'
    sys_version = ''
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):  # keep the console quiet
        pass

    # --- helpers
    def _client(self) -> str:
        fwd = self.headers.get('X-Forwarded-For', '')
        return (fwd.split(',')[0].strip() or self.client_address[0])

    def _token(self) -> str | None:
        c = SimpleCookie(self.headers.get('Cookie', ''))
        return c[COOKIE].value if COOKIE in c else None

    def _send(self, code: int, body: bytes, ctype: str, headers: dict | None = None):
        self.send_response(code)
        for k, v in {**_SECURITY_HEADERS, **(headers or {})}.items():
            self.send_header(k, v)
        self.send_header('Content-Type', ctype)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)

    def _json(self, code: int, obj, headers: dict | None = None):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode(), 'application/json; charset=utf-8',
                   {'Cache-Control': 'no-store', **(headers or {})})

    def _drain(self):
        """Read the request body before anything else. With keep-alive, a body
        left unread (e.g. after an early 401/403) would be parsed as the next
        request. Oversized bodies close the connection instead."""
        try:
            n = int(self.headers.get('Content-Length') or 0)
        except ValueError:
            n = -1
        if n < 0 or n > 64 * 1024 or self.headers.get('Transfer-Encoding'):
            self.close_connection = True
            self._raw = b''
            return
        self._raw = self.rfile.read(n) if n else b''

    def _body(self) -> dict:
        try:
            data = json.loads(self._raw or b'{}')
            return data if isinstance(data, dict) else {}
        except ValueError:
            return {}

    def _authed(self) -> str | None:
        token = self._token()
        if self.app.tokens.check(token):
            return token
        self._json(401, {'error': 'Sign in with the access code.'})
        return None

    def _same_origin(self) -> bool:
        """Block cross-site form posts (CSRF). Phones send Origin on fetch POSTs."""
        origin = self.headers.get('Origin')
        if not origin:
            return True
        host = self.headers.get('X-Forwarded-Host') or self.headers.get('Host', '')
        return urlsplit(origin).netloc == host

    # --- routing
    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urlsplit(self.path).path
        if path.startswith('/api/'):
            return self._api_get(path)
        name = _STATIC.get(path.lstrip('/'))
        if not name:
            return self._send(404, b'Not found', 'text/plain')
        f = WEB_DIR / name
        cache = 'no-cache' if name in ('index.html', 'sw.js', 'app.js', 'styles.css',
                                         'manifest.webmanifest') else 'public, max-age=86400'
        self._send(200, f.read_bytes(), mimetypes.guess_type(name)[0] or 'application/octet-stream',
                   {'Cache-Control': cache})

    def do_POST(self):
        self._drain()
        path = urlsplit(self.path).path
        if not self._same_origin():
            return self._json(403, {'error': 'Cross-site request blocked.'})
        if path == '/api/login':
            return self._login()
        if path == '/api/logout':
            if token := self._token():
                self.app.tokens.revoke(token)
            return self._json(200, {'ok': True}, {'Set-Cookie': f'{COOKIE}=; Path=/; Max-Age=0'})
        token = self._authed()
        if not token:
            return
        if path == '/api/jobs':
            body = self._body()
            jobs, err = self.app.add_jobs(token, str(body.get('text', ''))[:5000],
                                          str(body.get('mode', 'video')), str(body.get('quality', '1080')))
            return self._json(400 if err else 200, {'jobs': jobs, 'error': err})
        if m := re.fullmatch(r'/api/jobs/(\d+)/retry', path):
            pj = self.app.retry(token, int(m.group(1)))
            return self._json(200 if pj else 404, {'job': pj.public() if pj else None})
        self._json(404, {'error': 'Not found'})

    def do_DELETE(self):
        self._drain()
        if not self._same_origin():
            return self._json(403, {'error': 'Cross-site request blocked.'})
        token = self._authed()
        if not token:
            return
        if m := re.fullmatch(r'/api/jobs/(\d+)', urlsplit(self.path).path):
            return self._json(200, {'ok': self.app.remove(token, int(m.group(1)))})
        self._json(404, {'error': 'Not found'})

    # --- API
    def _login(self):
        client = self._client()
        if self.app.limiter.blocked(client):
            return self._json(429, {'error': 'Too many wrong codes. Try again in 10 minutes.'})
        code = str(self._body().get('code', ''))
        if not hmac.compare_digest(_code_hash(code), self.app.tokens.code_hash):
            self.app.limiter.fail(client)
            time.sleep(0.5)
            return self._json(403, {'error': 'That access code is not right.'})
        token = self.app.tokens.issue(self.headers.get('User-Agent', 'phone'))
        self.app.log(f'A phone signed in ({client})')
        self.app.on_change()
        cookie = f'{COOKIE}={token}; Path=/; Max-Age=31536000; HttpOnly; SameSite=Lax'
        if (self.headers.get('X-Forwarded-Proto') or '').lower() == 'https':
            cookie += '; Secure'
        self._json(200, {'ok': True}, {'Set-Cookie': cookie})

    def _api_get(self, path: str):
        if path == '/api/ping':
            return self._json(200, {'ok': True, 'version': __version__})
        token = self._authed()
        if not token:
            return
        if path == '/api/me':
            return self._json(200, {'ok': True, 'version': __version__})
        if path == '/api/jobs':
            return self._json(200, {'jobs': self.app.list_jobs(token)})
        if m := re.fullmatch(r'/api/files/(\d+)', path):
            f = self.app.file_for(token, int(m.group(1)))
            if not f:
                return self._json(404, {'error': 'File not found (it may have been cleaned up).'})
            return self._send_file(f)
        self._json(404, {'error': 'Not found'})

    def _send_file(self, f: Path):
        size = f.stat().st_size
        start, end = 0, size - 1
        rng = self.headers.get('Range', '')
        partial = False
        if m := re.fullmatch(r'bytes=(\d*)-(\d*)', rng.strip()):
            a, b = m.groups()
            if a == '' and b:
                start = max(0, size - int(b))
            else:
                start = int(a or 0)
                end = min(int(b), size - 1) if b else size - 1
            if start > end or start >= size:
                self.send_response(416)
                self.send_header('Content-Range', f'bytes */{size}')
                self.send_header('Content-Length', '0')
                self.end_headers()
                return
            partial = True
        length = end - start + 1
        ascii_name = re.sub(r'[^\x20-\x7e]+', '_', f.name).replace('"', "'")
        self.send_response(206 if partial else 200)
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.send_header('Content-Type', _mime(f))
        self.send_header('Content-Length', str(length))
        self.send_header('Accept-Ranges', 'bytes')
        self.send_header('Cache-Control', 'private, no-store')
        self.send_header('Content-Disposition',
                         f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(f.name)}')
        if partial:
            self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
        self.end_headers()
        if self.command == 'HEAD':
            return
        with open(f, 'rb') as fh:
            fh.seek(start)
            remaining = length
            while remaining > 0:
                chunk = fh.read(min(256 * 1024, remaining))
                if not chunk:
                    break
                try:
                    self.wfile.write(chunk)
                except (BrokenPipeError, ConnectionResetError):
                    return
                remaining -= len(chunk)


# ------------------------------------------------------------------ headless entry point
def main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(description='Run VidHarbor phone access without the desktop window.')
    p.add_argument('--port', type=int, default=int(os.environ.get('VIDHARBOR_PORT', 8787)))
    p.add_argument('--code', default=os.environ.get('VIDHARBOR_CODE', ''),
                   help='access code friends type on their phone (default: generate one)')
    p.add_argument('--keep-hours', type=float, default=6)
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--proxy', default=os.environ.get('VIDHARBOR_PROXY', ''))
    args = p.parse_args(argv)
    engine.add_bins_to_path()
    code = args.code or new_access_code()
    srv = PhoneServer(port=args.port, access_code=code, keep_hours=args.keep_hours, workers=args.workers,
                      options=lambda: Options(outdir='', cookie_mode='builtin', proxy=args.proxy))
    srv.start()
    print(f'VidHarbor phone access on http://0.0.0.0:{srv.port}  access code: {code}', flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        srv.stop()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
