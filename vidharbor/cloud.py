"""Cloud entry point: run the VidHarbor web app on a server (Render, a VPS,
Docker...). Everyone opens the site's link on their phone; no PC needed.

    python -m vidharbor.cloud

Settings come from environment variables:
    VIDHARBOR_CODE      access code friends type once (required)
    PORT                port to listen on (Render sets this; default 8787)
    VIDHARBOR_COOKIES   optional cookies.txt contents (Netscape format, or "b64:<base64>"),
                        e.g. a YouTube session if YouTube asks to "confirm you're not a bot"
    VIDHARBOR_PROXY     optional proxy for downloads (http://..., socks5://...)
    VIDHARBOR_KEEP_HOURS  hours finished files are kept (default 2)
    VIDHARBOR_WORKERS   downloads at once (default 2)
    VIDHARBOR_AUTO_UPDATE  1 = fetch the newest yt-dlp at start-up (default 1)

yt-dlp is updated before it is imported, so this module must not import
anything that imports yt_dlp at the top.
"""
from __future__ import annotations

import base64
import os
import sys
import threading
import time


def _env(name: str, default: str = '') -> str:
    return (os.environ.get(name) or default).strip()


def _update_engine(log) -> None:
    from vidharbor import engine
    try:
        latest = engine.latest_engine_version(_env('VIDHARBOR_PROXY'))
        have = engine.engine_folder_version() or engine.bundled_version() or '0'
        if engine._vtuple(latest) > engine._vtuple(have):
            log(f'Updating yt-dlp {have} -> {latest}')
            engine.update_engine(log=log, proxy=_env('VIDHARBOR_PROXY'))
        else:
            log(f'yt-dlp {have} is current')
    except Exception as e:  # noqa: BLE001 - never block start-up on this
        log(f'yt-dlp update check failed ({e}); using the installed version')


def _write_cookies(log) -> None:
    from vidharbor import engine
    raw = os.environ.get('VIDHARBOR_COOKIES', '')
    if not raw.strip():
        return
    if raw.startswith('b64:'):
        raw = base64.b64decode(raw[4:]).decode('utf-8', 'replace')
    raw = raw.replace('\\n', '\n').replace('\\t', '\t')
    if not raw.lstrip().startswith('#'):
        raw = '# Netscape HTTP Cookie File\n' + raw
    engine.cookie_file().write_text(raw if raw.endswith('\n') else raw + '\n', 'utf-8')
    log(f'Loaded {sum(1 for l in raw.splitlines() if l.strip() and not l.startswith("# "))} cookies')


def _restart_when_outdated(server, log, every_hours: float = 12) -> None:
    """For always-on hosts: once a newer yt-dlp is out and nothing is
    downloading, exit so the host restarts us with the update."""
    from vidharbor import engine
    import yt_dlp.version
    while True:
        time.sleep(every_hours * 3600)
        try:
            latest = engine.latest_engine_version(_env('VIDHARBOR_PROXY'))
        except Exception:
            continue
        if engine._vtuple(latest) <= engine._vtuple(yt_dlp.version.__version__):
            continue
        while any(p.state in ('queued', 'running') for p in server.jobs.values()):
            time.sleep(60)
        log(f'yt-dlp {latest} is out; restarting to update')
        os._exit(0)


def main() -> int:
    def log(msg):
        print(msg, flush=True)

    code = _env('VIDHARBOR_CODE')
    if not code:
        log('VIDHARBOR_CODE is not set. Set it to the access code friends will type, then restart.')
        return 2

    from vidharbor import engine
    engine.add_bins_to_path()
    if _env('VIDHARBOR_AUTO_UPDATE', '1') == '1':
        _update_engine(log)
    engine.install_engine_finder()        # promotes a just-downloaded engine
    _write_cookies(log)

    import yt_dlp.version                 # first yt_dlp import happens here
    from vidharbor.core import Options
    from vidharbor.server import PhoneServer

    server = PhoneServer(
        port=int(_env('PORT', '8787')), access_code=code,
        keep_hours=float(_env('VIDHARBOR_KEEP_HOURS', '2')), workers=int(_env('VIDHARBOR_WORKERS', '2')),
        options=lambda: Options(outdir='', cookie_mode='builtin', proxy=_env('VIDHARBOR_PROXY'),
                                embed_meta=True),
        log=log)
    server.start()
    log(f'VidHarbor web app ready on port {server.port} (yt-dlp {yt_dlp.version.__version__}, '
        f'ffmpeg: {"yes" if engine.exe("ffmpeg") else "MISSING"}, deno: {"yes" if engine.exe("deno") else "no"})')
    if _env('VIDHARBOR_AUTO_UPDATE', '1') == '1':
        threading.Thread(target=_restart_when_outdated, args=(server, log), daemon=True).start()
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        server.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
