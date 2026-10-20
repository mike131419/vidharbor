"""Locations, the self-updating yt-dlp engine, and helper tools (ffmpeg, Deno).

YouTube, Douyin and others change often, so a frozen .exe would go stale.
The app therefore loads yt-dlp from a writable "engine" folder when that copy
is newer than the bundled one, and can refresh that folder from PyPI.

Call install_engine_finder() BEFORE anything imports yt_dlp.
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import io
import json
import os
import re
import shutil
import ssl
import sys
import urllib.request
import zipfile
from pathlib import Path

APP_NAME = 'VidHarbor'
ENGINE_PACKAGES = ('yt_dlp', 'yt_dlp_ejs')
PYPI_NAMES = {'yt_dlp': 'yt-dlp', 'yt_dlp_ejs': 'yt-dlp-ejs'}

FFMPEG_ZIP = 'https://github.com/yt-dlp/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip'
DENO_ZIP = 'https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip'


# ---------------------------------------------------------------- locations
def app_dir() -> Path:
    """Folder holding the .exe (or the project root when running from source)."""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    base = os.environ.get('LOCALAPPDATA') or os.path.join(Path.home(), '.local', 'share')
    d = Path(base) / APP_NAME
    d.mkdir(parents=True, exist_ok=True)
    return d


def engine_dir() -> Path:
    return data_dir() / 'engine'


def bin_dirs() -> list[Path]:
    return [app_dir() / 'bin', data_dir() / 'bin']


def cookie_file() -> Path:
    return data_dir() / 'cookies.txt'


def exe(name: str) -> Path | None:
    suffix = '.exe' if os.name == 'nt' else ''
    for d in bin_dirs():
        p = d / (name + suffix)
        if p.is_file():
            return p
    found = shutil.which(name)
    return Path(found) if found else None


def add_bins_to_path() -> None:
    extra = [str(d) for d in bin_dirs() if d.is_dir()]
    if extra:
        os.environ['PATH'] = os.pathsep.join(extra + [os.environ.get('PATH', '')])


# ---------------------------------------------------------------- versions
def _vtuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r'\d+', v or '0'))


def engine_folder_version(root: Path | None = None) -> str | None:
    f = (root or engine_dir()) / 'yt_dlp' / 'version.py'
    try:
        m = re.search(r"__version__\s*=\s*'([^']+)'", f.read_text('utf-8'))
        return m.group(1) if m else None
    except OSError:
        return None


def bundled_version() -> str | None:
    try:
        from importlib.metadata import version
        return version('yt-dlp')
    except Exception:
        return None


# ---------------------------------------------------------------- import hook
class _EngineFinder(importlib.abc.MetaPathFinder):
    """Serve yt_dlp / yt_dlp_ejs from the engine folder, ahead of the frozen copy."""

    def __init__(self, root: Path):
        self.root = str(root)

    def find_spec(self, fullname, path=None, target=None):
        top = fullname.partition('.')[0]
        if top not in ENGINE_PACKAGES:
            return None
        if '.' not in fullname:
            search = [self.root]
        else:
            parent = sys.modules.get(fullname.rpartition('.')[0])
            search = getattr(parent, '__path__', None)
            if not search:
                return None
        return importlib.machinery.PathFinder.find_spec(fullname, list(search))


_active = {'source': 'bundled'}


def install_engine_finder() -> str:
    """Apply a staged update, then use the engine folder if it is newer.
    Returns 'engine' or 'bundled'."""
    staged = data_dir() / 'engine.new'
    if staged.is_dir():
        shutil.rmtree(engine_dir(), ignore_errors=True)
        staged.rename(engine_dir())

    ev, bv = engine_folder_version(), bundled_version()
    if ev and (bv is None or _vtuple(ev) >= _vtuple(bv)):
        sys.meta_path.insert(0, _EngineFinder(engine_dir()))
        _active['source'] = 'engine'
    return _active['source']


def active_source() -> str:
    return _active['source']


# ---------------------------------------------------------------- downloads
def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _fetch(url: str, progress=None, proxy: str = '') -> bytes:
    handlers = [urllib.request.HTTPSHandler(context=_ssl_context())]
    if proxy:
        handlers.append(urllib.request.ProxyHandler({'http': proxy, 'https': proxy}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={'User-Agent': f'{APP_NAME}/1.0'})
    with opener.open(req, timeout=60) as r:
        total = int(r.headers.get('Content-Length') or 0)
        buf, done = io.BytesIO(), 0
        while chunk := r.read(256 * 1024):
            buf.write(chunk)
            done += len(chunk)
            if progress:
                progress(done, total)
        return buf.getvalue()


def latest_engine_version(proxy: str = '') -> str:
    meta = json.loads(_fetch('https://pypi.org/pypi/yt-dlp/json', proxy=proxy))
    return meta['info']['version']


def update_engine(progress=None, log=print, proxy: str = '') -> str:
    """Download the newest yt-dlp + yt-dlp-ejs wheels into engine.new
    (applied on next start). Returns the new yt-dlp version."""
    staged = data_dir() / 'engine.new'
    shutil.rmtree(staged, ignore_errors=True)
    staged.mkdir(parents=True)
    version = ''
    for pkg, pypi in PYPI_NAMES.items():
        meta = json.loads(_fetch(f'https://pypi.org/pypi/{pypi}/json', proxy=proxy))
        files = meta['urls']
        wheel = next((f for f in files if f['filename'].endswith('py3-none-any.whl')), None)
        if not wheel:
            raise RuntimeError(f'No pure-Python wheel found for {pypi}')
        log(f'Downloading {wheel["filename"]}')
        data = _fetch(wheel['url'], progress, proxy)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                if name.startswith(pkg + '/'):
                    z.extract(name, staged)
        if pkg == 'yt_dlp':
            version = meta['info']['version']
    if not engine_folder_version(staged):
        shutil.rmtree(staged, ignore_errors=True)
        raise RuntimeError('Downloaded engine looks incomplete; nothing was changed.')
    return version


def install_tools(progress=None, log=print, proxy: str = '', which=('ffmpeg', 'deno')) -> None:
    """Fetch ffmpeg/ffprobe and Deno for Windows into the per-user bin folder."""
    target = data_dir() / 'bin'
    target.mkdir(parents=True, exist_ok=True)
    jobs = []
    if 'ffmpeg' in which:
        jobs.append((FFMPEG_ZIP, ('ffmpeg.exe', 'ffprobe.exe')))
    if 'deno' in which:
        jobs.append((DENO_ZIP, ('deno.exe',)))
    for url, wanted in jobs:
        log(f'Downloading {url.rsplit("/", 1)[-1]}')
        data = _fetch(url, progress, proxy)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for name in z.namelist():
                base = name.rsplit('/', 1)[-1]
                if base in wanted:
                    with z.open(name) as src, open(target / base, 'wb') as dst:
                        shutil.copyfileobj(src, dst)
                    log(f'Installed {base}')
    add_bins_to_path()
