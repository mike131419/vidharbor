"""Download jobs: options -> yt-dlp, run on a thread pool, report progress via Qt signals."""
from __future__ import annotations

import html as htmllib
import itertools
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path

import os
import shutil
from urllib.parse import urljoin

from PySide6.QtCore import QObject, QRunnable, Signal

import yt_dlp
from yt_dlp.networking import Request
from yt_dlp.postprocessor.common import PostProcessor
from yt_dlp.utils import DownloadCancelled, DownloadError

from . import engine
from .extractors import EXTRA_EXTRACTORS
from .linkparse import detect_platform, is_short_link, normalize, why_unsupported

_ids = itertools.count(1)


@dataclass
class Options:
    outdir: str
    mode: str = 'video'            # video | mp3 | m4a
    quality: str = 'best'          # best | 2160 | 1080 | 720 | 480
    mp3_bitrate: str = '320'
    h264: bool = True              # prefer H.264/AAC MP4 that plays everywhere
    cookie_mode: str = 'builtin'   # builtin | none | file | firefox | chrome | edge | brave ...
    cookie_path: str = ''
    proxy: str = ''
    subfolders: bool = True
    template: str = '%(title).80B [%(id)s].%(ext)s'
    allow_playlist: bool = False
    embed_meta: bool = True
    rate_limit: str = ''           # e.g. 5M


@dataclass
class Job:
    url: str
    id: int = field(default_factory=lambda: next(_ids))
    headers: dict = field(default_factory=dict)  # e.g. Referer for sniffed media
    title: str = ''
    page_url: str = ''                           # page a sniffed stream came from
    status: str = 'Queued'
    filepath: str = ''
    cancel: threading.Event = field(default_factory=threading.Event)

    @property
    def platform(self):
        return detect_platform(self.page_url or self.url)


# ------------------------------------------------------------------ yt-dlp options
def folder_for(job: Job) -> str:
    """'抖音 Douyin' -> 'Douyin', unknown sites -> 'Web'."""
    p = job.platform
    if p.key == 'other':
        return 'Web'
    return re.sub(r'[\\/:*?"<>|]+', '-', p.label.split(' ', 1)[-1]).strip() or 'Web'


def job_temp_dir(opts: Options, job: Job) -> Path:
    return Path(opts.outdir) / '_partial' / f'job{job.id}'


def _format_for(opts: Options) -> tuple[str, list[str]]:
    if opts.mode != 'video':
        return ('ba[ext=m4a]/ba/b' if opts.mode == 'm4a' else 'ba/b'), []
    sort = []
    if opts.quality != 'best':
        sort.append(f'res:{opts.quality}')
    if opts.h264:
        sort += ['vcodec:h264', 'acodec:aac', 'ext:mp4:m4a']
    return 'bv*+ba/b', sort


def build_opts(opts: Options, job: Job, *, logger=None, progress_hooks=(), pp_hooks=(),
               post_hooks=(), outtmpl: str | None = None) -> dict:
    fmt, sort = _format_for(opts)
    sub = folder_for(job) + '/' if opts.subfolders else ''
    o = {
        'format': fmt,
        'format_sort': sort,
        # each job works in its own temp folder, so parallel jobs never collide
        # and a retried job resumes its own partial download
        'paths': {'home': opts.outdir, 'temp': str(job_temp_dir(opts, job))},
        'outtmpl': {'default': outtmpl or (sub + opts.template)},
        'windowsfilenames': True,
        'noplaylist': not opts.allow_playlist,
        'retries': 10,
        'fragment_retries': 10,
        'concurrent_fragment_downloads': 4,
        'socket_timeout': 30,
        'continuedl': True,
        'noprogress': True,
        'quiet': True,
        'no_warnings': False,
        'logger': logger,
        'progress_hooks': list(progress_hooks),
        'postprocessor_hooks': list(pp_hooks),
        'post_hooks': list(post_hooks),
        'http_headers': dict(job.headers) if job.headers else {},
        'postprocessors': [],
    }
    if ff := engine.exe('ffmpeg'):
        o['ffmpeg_location'] = str(ff.parent)
    if deno := engine.exe('deno'):
        o['js_runtimes'] = {'deno': {'path': str(deno)}}
    if opts.proxy:
        o['proxy'] = opts.proxy
    if opts.rate_limit:
        from yt_dlp.utils import parse_bytes
        o['ratelimit'] = parse_bytes(opts.rate_limit)

    # cookies
    if opts.cookie_mode == 'builtin' and engine.cookie_file().is_file():
        o['cookiefile'] = str(engine.cookie_file())
    elif opts.cookie_mode == 'file' and opts.cookie_path:
        o['cookiefile'] = opts.cookie_path
    elif opts.cookie_mode not in ('builtin', 'none', 'file'):
        o['cookiesfrombrowser'] = (opts.cookie_mode, None, None, None)

    pps = o['postprocessors']
    if opts.mode == 'video':
        o['merge_output_format'] = 'mp4' if opts.h264 else 'mp4/mkv'
    else:
        codec = 'mp3' if opts.mode == 'mp3' else 'm4a'
        pps.append({'key': 'FFmpegExtractAudio', 'preferredcodec': codec,
                    'preferredquality': opts.mp3_bitrate if codec == 'mp3' else '0'})
    if opts.embed_meta:
        pps.append({'key': 'FFmpegMetadata', 'add_metadata': True, 'add_chapters': True})
        o['writethumbnail'] = True
        pps.insert(0, {'key': 'FFmpegThumbnailsConvertor', 'format': 'jpg', 'when': 'before_dl'})
        pps.append({'key': 'EmbedThumbnail', 'already_have_thumbnail': False})
    return o


class FixThumbnailsPP(PostProcessor):
    """Make cover-image URLs absolute and drop unusable ones, so a broken
    thumbnail can never fail the actual download."""

    def run(self, info):
        base = info.get('webpage_url') or info.get('original_url') or ''
        good = []
        for t in info.get('thumbnails') or []:
            url = urljoin(base, t.get('url') or '')
            if url.startswith(('http://', 'https://')):
                good.append({**t, 'url': url})
        info['thumbnails'] = good
        info['thumbnail'] = good[-1]['url'] if good else None
        return [], info


def make_ydl(params: dict) -> yt_dlp.YoutubeDL:
    ydl = yt_dlp.YoutubeDL(params, auto_init=False)
    for ie in EXTRA_EXTRACTORS:
        ydl.add_info_extractor(ie())
    ydl.add_default_info_extractors()
    ydl.add_post_processor(FixThumbnailsPP(ydl), when='pre_process')
    return ydl


# ------------------------------------------------------------------ friendly errors
_HINTS = [
    ('Fresh cookies', 'Douyin needs fresh cookies. Open 抖音 once in the built-in browser '
                      '(Browser button), then Retry.'),
    ('xsec_token', 'RedNote needs the full share link (with xsec_token). Copy the link from the app again.'),
    ('Sign in to confirm', 'YouTube wants a signed-in session. Sign in to YouTube in the built-in '
                           'browser, then Retry.'),
    ('confirm you', 'The site wants a signed-in session. Sign in in the built-in browser, then Retry.'),
    ('login', 'This video needs you to be signed in. Sign in in the built-in browser, then Retry.'),
    ('Could not copy', 'Could not read the browser\'s cookies (close the browser first, or use the '
                       'built-in browser instead - newer Chrome/Edge versions block this).'),
    ('ffmpeg', 'ffmpeg is missing. Open "Engine & tools" and click "Install ffmpeg + Deno".'),
    ('HTTP Error 403', 'The site refused the download (403). Try the built-in browser\'s '
                       '"Detected media" for this link.'),
    ('geo', 'This video is region-locked. Set a proxy in Settings.'),
]


def friendly(msg: str) -> str:
    clean = re.sub(r'\x1b\[[0-9;]*m', '', msg).replace('ERROR: ', '').strip()
    for needle, hint in _HINTS:
        if needle.lower() in clean.lower():
            return f'{hint}\n\nDetails: {clean}'
    return clean


# ------------------------------------------------------------------ worker
class TaskSignals(QObject):
    status = Signal(int, str)
    title = Signal(int, str)
    progress = Signal(int, dict)
    done = Signal(int, str, str, str)   # id, result(ok|error|cancelled), message, filepath
    log = Signal(str)


class _Logger:
    def __init__(self, sig: TaskSignals, job: Job):
        self.sig, self.job = sig, job

    def debug(self, msg):
        if not msg.startswith('[debug] '):
            self.info(msg)

    def info(self, msg):
        self.sig.log.emit(f'#{self.job.id} {msg}')

    def warning(self, msg):
        self.sig.log.emit(f'#{self.job.id} WARNING {msg}')

    def error(self, msg):
        self.sig.log.emit(f'#{self.job.id} {msg}')


_MEDIA_RE = re.compile(
    r'https?://[^\s"\'<>\\]+?\.(?:mp4|m3u8|flv|webm|mov)(?:\?[^\s"\'<>\\]*)?', re.I)


def sniff_page(ydl: yt_dlp.YoutubeDL, url: str) -> tuple[str | None, str]:
    """Last resort for unsupported pages: look for a media URL in the HTML."""
    with ydl.urlopen(Request(url)) as r:
        page = r.read(4 * 1024 * 1024).decode('utf-8', 'replace')
    flat = page.replace('\\u002F', '/').replace('\\/', '/').replace('&amp;', '&')
    found = list(dict.fromkeys(_MEDIA_RE.findall(flat)))
    mp4 = [u for u in found if '.m3u8' not in u.lower()]
    title = (re.search(r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)', page)
             or re.search(r'<title[^>]*>([^<]+)</title>', page))
    return ((mp4 or found or [None])[0],
            htmllib.unescape(title.group(1)).strip() if title else '')


class DownloadTask(QRunnable):
    def __init__(self, job: Job, opts: Options, signals: TaskSignals):
        super().__init__()
        self.job, self.opts, self.sig = job, opts, signals
        self.setAutoDelete(True)

    def _cleanup_partials(self):
        tmp = job_temp_dir(self.opts, self.job)
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            tmp.parent.rmdir()  # only succeeds once no other job is using it
        except OSError:
            pass

    # hooks run on this worker thread; signals are queued to the GUI thread
    def _progress(self, d):
        if self.job.cancel.is_set():
            raise DownloadCancelled('Cancelled')
        info = d.get('info_dict') or {}
        if info.get('title') and not self.job.title:
            self.job.title = info['title']
            self.sig.title.emit(self.job.id, self.job.title)
        if d['status'] == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            self.sig.progress.emit(self.job.id, {
                'done': d.get('downloaded_bytes') or 0, 'total': total,
                'speed': d.get('speed') or 0, 'eta': d.get('eta'),
                'frag': (d.get('fragment_index'), d.get('fragment_count')),
            })
        elif d['status'] == 'finished':
            self.sig.status.emit(self.job.id, 'Processing…')

    def _pp(self, d):
        if self.job.cancel.is_set():
            raise DownloadCancelled('Cancelled')
        if d['status'] == 'started':
            names = {'FFmpegExtractAudio': 'Converting audio…', 'Merger': 'Merging video + audio…',
                     'FFmpegVideoConvertor': 'Converting…', 'EmbedThumbnail': 'Embedding cover…'}
            if label := names.get(d.get('postprocessor')):
                self.sig.status.emit(self.job.id, label)

    def _post(self, filename):
        self.job.filepath = filename

    def _params(self, **kw):
        return build_opts(self.opts, self.job, logger=_Logger(self.sig, self.job),
                          progress_hooks=[self._progress], pp_hooks=[self._pp],
                          post_hooks=[self._post], **kw)

    def run(self):
        job = self.job
        try:
            self._run()
            self._cleanup_partials()
        except DownloadCancelled:
            self._cleanup_partials()
            self.sig.done.emit(job.id, 'cancelled', 'Cancelled', '')
        except Exception as e:  # noqa: BLE001 - surface everything to the UI
            if job.cancel.is_set():
                self._cleanup_partials()
                self.sig.done.emit(job.id, 'cancelled', 'Cancelled', '')
            else:
                self.sig.done.emit(job.id, 'error', friendly(str(e)), '')

    def _run(self):
        job = self.job
        url = job.url
        with make_ydl(self._params()) as ydl:
            if is_short_link(url):
                self.sig.status.emit(job.id, 'Resolving link…')
                with ydl.urlopen(Request(url)) as r:
                    url = r.url
                self.sig.log.emit(f'#{job.id} {job.url} -> {url}')
            url = normalize(url)
            if reason := why_unsupported(url):
                self.sig.done.emit(job.id, 'error', reason, '')
                return

            self.sig.status.emit(job.id, 'Starting…')
            try:
                ydl.download([url])
            except DownloadError as e:
                if 'Unsupported URL' not in str(e):
                    raise
                self.sig.status.emit(job.id, 'Searching page for video…')
                media, page_title = sniff_page(ydl, url)
                if not media:
                    raise DownloadError(
                        'No downloadable video found on this page. Open it in the built-in '
                        'browser and use "Detected media".') from None
                self.sig.log.emit(f'#{job.id} found media in page: {media}')
                job.headers.setdefault('Referer', url)
                if page_title and not job.title:
                    job.title = page_title
                    self.sig.title.emit(job.id, page_title)
                self._download_direct(media, page_title)
                return

        self.sig.done.emit(job.id, 'ok', 'Done', job.filepath)

    def _download_direct(self, media: str, title: str):
        safe = re.sub(r'[\\/:*?"<>|%\r\n]+', ' ', title or 'video').strip()[:80] or 'video'
        sub = folder_for(self.job) + '/' if self.opts.subfolders else ''
        with make_ydl(self._params(outtmpl=f'{sub}{safe} [%(id)s].%(ext)s')) as ydl:
            ydl.download([media])
        self.sig.done.emit(self.job.id, 'ok', 'Done', self.job.filepath)


def run_direct(job: Job, opts: Options, signals: TaskSignals) -> DownloadTask:
    """Task for a stream URL captured by the built-in browser."""
    return _DirectTask(job, opts, signals)


class _DirectTask(DownloadTask):
    def _run(self):
        self.sig.status.emit(self.job.id, 'Starting…')
        self._download_direct(self.job.url, self.job.title)
