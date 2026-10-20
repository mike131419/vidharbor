"""Main window, settings and engine dialogs."""
from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QSettings, QThreadPool, QTimer, QUrl, Qt, Signal, QObject
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QComboBox,
                               QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
                               QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QSpinBox, QSplitter,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from . import engine
from .browser import WARMUPS, BrowserWindow, CookieManager
from .downloader import DownloadTask, Job, Options, TaskSignals, run_direct
from .linkparse import PLATFORMS, detect_platform, extract_urls

COOKIE_MODES = [
    ('builtin', 'Built-in browser (recommended)'), ('none', 'No cookies'),
    ('firefox', 'From Firefox'), ('chrome', 'From Chrome'), ('edge', 'From Edge'),
    ('brave', 'From Brave'), ('file', 'cookies.txt file…'),
]
MODES = [('video', 'Video (MP4)'), ('mp3', 'Audio (MP3)'), ('m4a', 'Audio (M4A, no re-encode)')]
QUALITIES = [('best', 'Best available'), ('2160', 'Up to 4K'), ('1080', 'Up to 1080p'),
             ('720', 'Up to 720p'), ('480', 'Up to 480p')]
BITRATES = [('320', '320 kbps'), ('256', '256 kbps'), ('192', '192 kbps'), ('128', '128 kbps')]
COLS = ['Platform', 'Title', 'Progress', 'Size', 'Speed', 'ETA', 'Status']


def human(n: float | int | None, suffix='B') -> str:
    if not n:
        return ''
    for unit in ('', 'K', 'M', 'G'):
        if abs(n) < 1024:
            return f'{n:.1f} {unit}{suffix}' if unit else f'{n:.0f} {suffix}'
        n /= 1024
    return f'{n:.1f} T{suffix}'


def open_in_explorer(path: str):
    p = Path(path)
    if sys.platform == 'win32' and p.exists():
        subprocess.Popen(['explorer', '/select,', str(p)])
    else:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p if p.is_dir() else p.parent)))


def _combo(items, current) -> QComboBox:
    c = QComboBox()
    for key, label in items:
        c.addItem(label, key)
    i = c.findData(current)
    c.setCurrentIndex(max(i, 0))
    return c


# ====================================================================== settings
class Settings:
    DEFAULTS = {
        'outdir': str(Path.home() / 'Downloads' / 'VidHarbor'), 'mode': 'video', 'quality': 'best',
        'mp3_bitrate': '320', 'h264': True, 'cookie_mode': 'builtin', 'cookie_path': '',
        'proxy': '', 'subfolders': True, 'template': '%(title).80B [%(id)s].%(ext)s',
        'allow_playlist': False, 'embed_meta': True, 'rate_limit': '', 'concurrency': 3,
        'watch_clipboard': False,
    }

    def __init__(self):
        self.q = QSettings('VidHarbor', 'VidHarbor')

    def get(self, key):
        default = self.DEFAULTS[key]
        val = self.q.value(key, default)
        if isinstance(default, bool):
            return val in (True, 'true', '1', 1)
        if isinstance(default, int):
            return int(val)
        return val

    def set(self, key, value):
        self.q.setValue(key, value)

    def options(self) -> Options:
        return Options(**{k: self.get(k) for k in Options.__dataclass_fields__})


class SettingsDialog(QDialog):
    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self.setWindowTitle('Settings')
        self.setMinimumWidth(520)
        f = QFormLayout(self)
        self.conc = QSpinBox(minimum=1, maximum=8, value=s.get('concurrency'))
        self.tmpl = QLineEdit(s.get('template'))
        self.sub = QCheckBox('Put each platform in its own folder', checked=s.get('subfolders'))
        self.pl = QCheckBox('Allow playlists, profiles and collections (downloads every item)',
                            checked=s.get('allow_playlist'))
        self.meta = QCheckBox('Embed title, cover image and metadata', checked=s.get('embed_meta'))
        self.proxy = QLineEdit(s.get('proxy'), placeholderText='e.g. http://127.0.0.1:7890 or socks5://…')
        self.rate = QLineEdit(s.get('rate_limit'), placeholderText='e.g. 5M (blank = unlimited)')
        self.bitrate = _combo(BITRATES, s.get('mp3_bitrate'))
        f.addRow('Downloads at once', self.conc)
        f.addRow('MP3 quality', self.bitrate)
        f.addRow('File name', self.tmpl)
        f.addRow('', QLabel('<span style="color:gray">yt-dlp output template, e.g. '
                            '%(uploader)s - %(title)s.%(ext)s</span>'))
        f.addRow('', self.sub)
        f.addRow('', self.meta)
        f.addRow('', self.pl)
        f.addRow('Proxy', self.proxy)
        f.addRow('Speed limit', self.rate)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        f.addRow(bb)

    def accept(self):
        s = self.s
        s.set('concurrency', self.conc.value())
        s.set('template', self.tmpl.text().strip() or Settings.DEFAULTS['template'])
        s.set('subfolders', self.sub.isChecked())
        s.set('allow_playlist', self.pl.isChecked())
        s.set('embed_meta', self.meta.isChecked())
        s.set('proxy', self.proxy.text().strip())
        s.set('rate_limit', self.rate.text().strip())
        s.set('mp3_bitrate', self.bitrate.currentData())
        super().accept()


# ====================================================================== engine dialog
class _UpdateSignals(QObject):
    found = Signal(dict)


class _BgSignals(QObject):
    log = Signal(str)
    progress = Signal(int, int)
    finished = Signal(bool, str)


class EngineDialog(QDialog):
    def __init__(self, s: Settings, parent=None):
        super().__init__(parent)
        self.s = s
        self.setWindowTitle('Engine & tools')
        self.setMinimumWidth(560)
        v = QVBoxLayout(self)
        self.info = QLabel()
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.info.setWordWrap(True)
        v.addWidget(self.info)
        row = QHBoxLayout()
        self.upd = QPushButton('Update download engine')
        self.upd.setObjectName('primary')
        self.tools = QPushButton('Install ffmpeg + Deno')
        row.addWidget(self.upd)
        row.addWidget(self.tools)
        row.addStretch()
        v.addLayout(row)
        self.bar = QProgressBar(visible=False)
        v.addWidget(self.bar)
        self.out = QPlainTextEdit(readOnly=True, maximumHeight=140)
        v.addWidget(self.out)
        help_ = QLabel(
            '<b>Chinese platforms</b><br>'
            '抖音 Douyin · 小红书 RedNote · B站 Bilibili · 微博 Weibo · 西瓜 Ixigua · 头条 Toutiao · '
            '知乎 Zhihu · 优酷 Youku · 爱奇艺 iQiyi · 腾讯视频 · AcFun · 虎牙 · 斗鱼: direct support.<br>'
            '快手 Kuaishou: experimental; if it fails, open the link in the built-in browser.<br>'
            '公众号 WeChat articles: best effort, browser capture works well.<br>'
            '视频号 WeChat Channels: not possible from a link (the video only plays inside WeChat).')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray')
        v.addWidget(help_)
        self.upd.clicked.connect(self._update_engine)
        self.tools.clicked.connect(self._install_tools)
        self._refresh()

    def _refresh(self):
        import yt_dlp.version as v
        src = 'updated copy' if engine.active_source() == 'engine' else 'built in'
        staged = engine.engine_folder_version(engine.data_dir() / 'engine.new')
        ff, deno = engine.exe('ffmpeg'), engine.exe('deno')
        self.info.setText(
            f'<b>yt-dlp</b> {v.__version__} ({src})'
            + (f' – <b>{staged}</b> installed, restart to use it' if staged else '')
            + f'<br><b>ffmpeg</b>: {ff or "<span style=color:#c0392b>missing – needed for MP3 and HD video</span>"}'
            + f'<br><b>Deno</b>: {deno or "<span style=color:#c0392b>missing – needed for YouTube</span>"}')

    def _run(self, fn, done_msg):
        self.upd.setEnabled(False)
        self.tools.setEnabled(False)
        self.bar.setVisible(True)
        sig = _BgSignals(self)
        sig.log.connect(self.out.appendPlainText)
        sig.progress.connect(lambda d, t: (self.bar.setMaximum(t or 0), self.bar.setValue(d)))

        def finished(ok, msg):
            self.out.appendPlainText(msg)
            self.bar.setVisible(False)
            self.upd.setEnabled(True)
            self.tools.setEnabled(True)
            self._refresh()
        sig.finished.connect(finished)

        def work():
            try:
                res = fn(lambda d, t: sig.progress.emit(d, t), sig.log.emit)
                sig.finished.emit(True, done_msg.format(res))
            except Exception as e:  # noqa: BLE001
                sig.finished.emit(False, f'Failed: {e}')
        threading.Thread(target=work, daemon=True).start()

    def _update_engine(self):
        import yt_dlp.version as v
        proxy = self.s.get('proxy')

        def fn(progress, log):
            latest = engine.latest_engine_version(proxy)
            log(f'Latest yt-dlp: {latest} (running {v.__version__})')
            if engine._vtuple(latest) <= engine._vtuple(v.__version__):
                return 'You already have the latest engine.'
            new = engine.update_engine(progress, log, proxy)
            return f'Engine {new} installed – restart VidHarbor to use it.'
        self._run(fn, '{}')

    def _install_tools(self):
        if sys.platform != 'win32':
            self.out.appendPlainText('Automatic install is for Windows. Install ffmpeg and deno '
                                     'with your package manager.')
            return
        proxy = self.s.get('proxy')
        self._run(lambda p, log: engine.install_tools(p, log, proxy) or 'Tools installed.', '{}')


# ====================================================================== main window
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.s = Settings()
        self.setWindowTitle('VidHarbor – Video & MP3 Downloader')
        self.resize(1180, 760)
        self.pool = QThreadPool(self)
        self.pool.setMaxThreadCount(self.s.get('concurrency'))
        self.sig = TaskSignals()
        self.sig.status.connect(self._on_status)
        self.sig.title.connect(self._on_title)
        self.sig.progress.connect(self._on_progress)
        self.sig.done.connect(self._on_done)
        self.sig.log.connect(self._log)
        self.rows: dict[int, dict] = {}
        self.cookies = CookieManager(self)
        self.browser: BrowserWindow | None = None
        self._clip_seen: set[str] = set()
        self._build()
        QGuiApplication.clipboard().dataChanged.connect(self._on_clipboard)
        QTimer.singleShot(300, self._check_tools)
        QTimer.singleShot(2000, self._check_app_update)

    def _check_app_update(self):
        sig = _UpdateSignals(self)
        sig.found.connect(self._show_update)
        proxy = self.s.get('proxy')

        def work():
            from .updates import latest_release
            try:
                if rel := latest_release(proxy):
                    sig.found.emit(rel)
            except Exception:  # offline, rate-limited, ... - never bother the user
                pass
        threading.Thread(target=work, daemon=True).start()

    def _show_update(self, rel: dict):
        self.update_label.setText(f'<b>VidHarbor {rel["version"]} is available.</b>  '
                                  'Install it over this version; your settings and sign-ins are kept.')
        self.update_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(rel['installer'])))
        self.update_bar.setVisible(True)

    # ------------------------------------------------------------------ layout
    def _build(self):
        root = QWidget()
        v = QVBoxLayout(root)
        v.setContentsMargins(18, 14, 18, 12)
        v.setSpacing(10)

        head = QHBoxLayout()
        title = QLabel('<span style="font-size:20px;font-weight:700">VidHarbor</span>'
                       '<span style="color:gray">  ·  Douyin · RedNote · Bilibili · YouTube · TikTok · '
                       'Instagram · Facebook · 1,000+ sites</span>')
        head.addWidget(title)
        head.addStretch()
        for text, slot in (('Built-in browser', self.open_browser), ('Engine && tools', self.open_engine),
                           ('Settings', self.open_settings)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            head.addWidget(b)
        v.addLayout(head)

        self.update_bar = QFrame(visible=False)
        self.update_bar.setObjectName('updateBar')
        self.update_bar.setStyleSheet('QFrame#updateBar { background: rgba(224,83,61,0.12); border-radius: 6px; }')
        ub = QHBoxLayout(self.update_bar)
        ub.setContentsMargins(10, 6, 6, 6)
        self.update_label = QLabel()
        self.update_btn = QPushButton('Download update')
        self.update_btn.setObjectName('primary')
        later = QPushButton('Later')
        later.clicked.connect(lambda: self.update_bar.setVisible(False))
        ub.addWidget(self.update_label, 1)
        ub.addWidget(self.update_btn)
        ub.addWidget(later)
        v.addWidget(self.update_bar)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.input = QPlainTextEdit()
        self.input.setPlaceholderText(
            'Paste links or whole share messages here – one or many.\n'
            'e.g.  7.43 复制打开抖音，看看【…】 https://v.douyin.com/xxxx/    or    http://xhslink.com/a/xxxx，复制本条信息')
        self.input.setFixedHeight(92)
        self.input.textChanged.connect(self._preview)
        grid.addWidget(self.input, 0, 0, 2, 1)
        self.paste_btn = QPushButton('Paste && Download')
        self.paste_btn.setObjectName('primary')
        self.paste_btn.setMinimumHeight(40)
        self.paste_btn.clicked.connect(self.paste_and_download)
        self.dl_btn = QPushButton('Download')
        self.dl_btn.clicked.connect(self.download_input)
        grid.addWidget(self.paste_btn, 0, 1)
        grid.addWidget(self.dl_btn, 1, 1)
        self.detect = QLabel(' ')
        self.detect.setStyleSheet('color: gray')
        grid.addWidget(self.detect, 2, 0, 1, 2)
        v.addLayout(grid)

        opt = QHBoxLayout()
        self.mode = _combo(MODES, self.s.get('mode'))
        self.quality = _combo(QUALITIES, self.s.get('quality'))
        self.h264 = QCheckBox('Most compatible (H.264)', checked=self.s.get('h264'))
        self.cookie = _combo(COOKIE_MODES, self.s.get('cookie_mode'))
        self.mode.currentIndexChanged.connect(self._mode_changed)
        self.quality.currentIndexChanged.connect(lambda: self.s.set('quality', self.quality.currentData()))
        self.h264.toggled.connect(lambda c: self.s.set('h264', c))
        self.cookie.currentIndexChanged.connect(self._cookie_changed)
        for w in (QLabel('Save as'), self.mode, self.quality, self.h264, QLabel('   Cookies'), self.cookie):
            opt.addWidget(w)
        opt.addStretch()
        v.addLayout(opt)

        folder = QHBoxLayout()
        self.outdir = QLineEdit(self.s.get('outdir'))
        self.outdir.editingFinished.connect(lambda: self.s.set('outdir', self.outdir.text().strip()))
        browse = QPushButton('Change…')
        browse.clicked.connect(self._pick_folder)
        openf = QPushButton('Open folder')
        openf.clicked.connect(lambda: self._open_outdir())
        folder.addWidget(QLabel('Save to'))
        folder.addWidget(self.outdir, 1)
        folder.addWidget(browse)
        folder.addWidget(openf)
        v.addLayout(folder)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(COLS)
        self.tree.setRootIsDecorated(False)
        self.tree.setAlternatingRowColors(True)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.tree.itemDoubleClicked.connect(self._activate)
        hdr = self.tree.header()
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        for col, w in ((0, 175), (2, 150), (3, 90), (4, 90), (5, 60), (6, 200)):
            self.tree.setColumnWidth(col, w)
            hdr.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
        self.logbox = QPlainTextEdit(readOnly=True)
        self.logbox.setMaximumBlockCount(3000)
        self.logbox.setPlaceholderText('Log')
        split = QSplitter(Qt.Orientation.Vertical)
        split.addWidget(self.tree)
        split.addWidget(self.logbox)
        split.setSizes([480, 110])
        v.addWidget(split, 1)

        bottom = QHBoxLayout()
        for text, slot in (('Retry failed', self.retry_failed), ('Clear finished', self.clear_finished),
                           ('Cancel all', self.cancel_all)):
            b = QPushButton(text)
            b.clicked.connect(slot)
            bottom.addWidget(b)
        self.clip = QCheckBox('Auto-download links I copy', checked=self.s.get('watch_clipboard'))
        self.clip.toggled.connect(lambda c: self.s.set('watch_clipboard', c))
        bottom.addWidget(self.clip)
        bottom.addStretch()
        self.engine_label = QLabel()
        self.engine_label.setStyleSheet('color: gray')
        bottom.addWidget(self.engine_label)
        v.addLayout(bottom)
        self.setCentralWidget(root)
        self._mode_changed()
        self._refresh_engine_label()
        QShortcut(QKeySequence('Ctrl+Return'), self, self.download_input)

    # ------------------------------------------------------------------ small slots
    def _log(self, msg: str):
        self.logbox.appendPlainText(msg)

    def _refresh_engine_label(self):
        import yt_dlp.version as v
        self.engine_label.setText(f'yt-dlp {v.__version__}')

    def _mode_changed(self):
        mode = self.mode.currentData()
        self.s.set('mode', mode)
        video = mode == 'video'
        self.quality.setVisible(video)
        self.h264.setVisible(video)

    def _cookie_changed(self):
        mode = self.cookie.currentData()
        if mode == 'file':
            path, _ = QFileDialog.getOpenFileName(self, 'Choose cookies.txt', '', 'Cookies (*.txt);;All files (*)')
            if not path:
                self.cookie.setCurrentIndex(self.cookie.findData(self.s.get('cookie_mode')))
                return
            self.s.set('cookie_path', path)
        if mode in ('chrome', 'edge') and sys.platform == 'win32':
            self._log('Note: recent Chrome/Edge versions encrypt cookies so other apps cannot read '
                      'them. If downloads fail, switch back to "Built-in browser".')
        self.s.set('cookie_mode', mode)

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, 'Save downloads to', self.outdir.text())
        if d:
            self.outdir.setText(d)
            self.s.set('outdir', d)

    def _open_outdir(self):
        p = Path(self.outdir.text())
        p.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(p)))

    def _preview(self):
        urls = extract_urls(self.input.toPlainText())
        if not urls:
            self.detect.setText(' ')
            return
        counts: dict[str, int] = {}
        for u in urls:
            label = detect_platform(u).label
            counts[label] = counts.get(label, 0) + 1
        self.detect.setText(f'{len(urls)} link(s): ' + ', '.join(f'{k} ×{n}' for k, n in counts.items()))

    def _check_tools(self):
        if not engine.exe('ffmpeg'):
            self._log('ffmpeg not found – MP3 conversion and HD video need it. '
                      'Open "Engine & tools" → "Install ffmpeg + Deno".')

    # ------------------------------------------------------------------ dialogs
    def open_settings(self):
        if SettingsDialog(self.s, self).exec():
            self.pool.setMaxThreadCount(self.s.get('concurrency'))

    def open_engine(self):
        EngineDialog(self.s, self).exec()

    def open_browser(self, url: str = ''):
        if self.browser is None:
            self.browser = BrowserWindow(self.cookies)
            self.browser.add_page.connect(lambda u: self.add_urls([u]))
            self.browser.add_media.connect(self.add_media)
        if url:
            self.browser.open(url)
        else:
            if self.browser.view.url().isEmpty():
                self.browser.open('https://www.douyin.com/')
            self.browser.show()
            self.browser.raise_()

    # ------------------------------------------------------------------ adding jobs
    def paste_and_download(self):
        text = QGuiApplication.clipboard().text()
        if not extract_urls(text):
            self.detect.setText('The clipboard has no link in it.')
            return
        self.input.setPlainText(text)
        self.download_input()

    def download_input(self):
        urls = extract_urls(self.input.toPlainText())
        if not urls:
            self.detect.setText('No link found – paste a link or a share message.')
            return
        self.add_urls(urls)
        self.input.clear()

    def _on_clipboard(self):
        if not self.clip.isChecked():
            return
        for url in extract_urls(QGuiApplication.clipboard().text()):
            if url not in self._clip_seen:
                self._clip_seen.add(url)
                self._log(f'Copied link picked up: {url}')
                self.add_urls([url])

    def add_urls(self, urls: list[str]):
        for url in urls:
            self._enqueue(Job(url=url))

    def add_media(self, media_url: str, page_url: str, title: str):
        job = Job(url=media_url, page_url=page_url, title=title,
                  headers={'Referer': page_url, 'User-Agent': self.cookies.profile.httpUserAgent()})
        self._enqueue(job, direct=True)

    def _enqueue(self, job: Job, direct: bool = False):
        item = QTreeWidgetItem([job.platform.label, job.title or job.url, '', '', '', '', 'Queued'])
        item.setToolTip(1, job.url)
        self.tree.addTopLevelItem(item)
        bar = QProgressBar()
        bar.setRange(0, 1000)
        bar.setValue(0)
        bar.setTextVisible(False)
        bar.setFixedHeight(14)
        holder = QWidget()
        hl = QHBoxLayout(holder)
        hl.setContentsMargins(4, 0, 4, 0)
        hl.addWidget(bar)
        self.tree.setItemWidget(item, 2, holder)
        self.rows[job.id] = {'job': job, 'item': item, 'bar': bar, 'state': 'queued', 'direct': direct}
        self._start(job.id)

    def _start(self, job_id: int):
        row = self.rows[job_id]
        job: Job = row['job']
        opts = self.s.options()
        opts.outdir = self.outdir.text().strip() or opts.outdir
        Path(opts.outdir).mkdir(parents=True, exist_ok=True)
        row['state'] = 'running'
        job.cancel.clear()
        if row['direct']:
            self.pool.start(run_direct(job, opts, self.sig))
            return
        key = job.platform.key
        if opts.cookie_mode == 'builtin' and key in WARMUPS:
            self._on_status(job_id, 'Preparing cookies…')

            def go(ok, job=job, opts=opts):
                if not ok:
                    self._log(f'#{job.id} could not get fresh {job.platform.label} cookies automatically; '
                              'trying anyway')
                if not job.cancel.is_set():
                    self.pool.start(DownloadTask(job, opts, self.sig))
                else:
                    self._on_done(job.id, 'cancelled', 'Cancelled', '')
            self.cookies.warm(key, go)
        else:
            self.pool.start(DownloadTask(job, opts, self.sig))

    # ------------------------------------------------------------------ job signals
    def _on_status(self, job_id: int, text: str):
        if row := self.rows.get(job_id):
            row['item'].setText(6, text)

    def _on_title(self, job_id: int, title: str):
        if row := self.rows.get(job_id):
            row['item'].setText(1, title)

    def _on_progress(self, job_id: int, d: dict):
        row = self.rows.get(job_id)
        if not row:
            return
        item, bar = row['item'], row['bar']
        done, total = d['done'], d['total']
        frag_i, frag_n = d.get('frag') or (None, None)
        if total or frag_n:
            bar.setRange(0, 1000)
        if total:
            bar.setValue(int(done * 1000 / total))
        elif frag_n:
            bar.setValue(int((frag_i or 0) * 1000 / frag_n))
        else:
            bar.setRange(0, 0)
        item.setText(3, human(total) if total else human(done))
        item.setText(4, human(d['speed'], 'B/s'))
        eta = d.get('eta')
        item.setText(5, f'{int(eta) // 60}:{int(eta) % 60:02d}' if eta is not None else '')
        pct = f'{done * 100 / total:.0f}%' if total else ''
        item.setText(6, f'Downloading {pct}'.strip())

    def _on_done(self, job_id: int, result: str, message: str, filepath: str):
        row = self.rows.get(job_id)
        if not row:
            return
        item, bar = row['item'], row['bar']
        row['state'] = result
        bar.setRange(0, 1000)
        item.setText(4, '')
        item.setText(5, '')
        if result == 'ok':
            bar.setValue(1000)
            item.setText(6, '✔ Done')
            item.setForeground(6, Qt.GlobalColor.darkGreen)
            if filepath:
                row['job'].filepath = filepath
                item.setToolTip(1, filepath)
                try:
                    item.setText(3, human(os.path.getsize(filepath)))
                except OSError:
                    pass
            self._log(f'#{job_id} saved: {filepath}')
        elif result == 'cancelled':
            item.setText(6, 'Cancelled')
            item.setForeground(6, Qt.GlobalColor.gray)
        else:
            bar.setValue(0)
            first = message.splitlines()[0] if message else 'Failed'
            item.setText(6, '✖ ' + first)
            item.setToolTip(6, message)
            item.setForeground(6, Qt.GlobalColor.red)
            self._log(f'#{job_id} failed: {message}')

    # ------------------------------------------------------------------ queue actions
    def _selected_ids(self) -> list[int]:
        sel = set(map(id, self.tree.selectedItems()))
        return [jid for jid, r in self.rows.items() if id(r['item']) in sel]

    def _activate(self, item, _col):
        for jid, r in self.rows.items():
            if r['item'] is item:
                if r['state'] == 'ok' and r['job'].filepath:
                    QDesktopServices.openUrl(QUrl.fromLocalFile(r['job'].filepath))
                elif r['state'] == 'error':
                    QMessageBox.information(self, 'Why it failed', item.toolTip(6))
                return

    def _menu(self, pos):
        ids = self._selected_ids()
        if not ids:
            return
        m = QMenu(self)
        first = self.rows[ids[0]]
        if first['state'] == 'ok' and first['job'].filepath:
            m.addAction('Play / open file', lambda: QDesktopServices.openUrl(
                QUrl.fromLocalFile(first['job'].filepath)))
            m.addAction('Show in folder', lambda: open_in_explorer(first['job'].filepath))
        m.addAction('Retry', lambda: [self.retry(i) for i in ids])
        m.addAction('Cancel', lambda: [self.cancel(i) for i in ids])
        m.addAction('Open link in built-in browser',
                    lambda: self.open_browser(first['job'].page_url or first['job'].url))
        m.addAction('Copy link', lambda: QGuiApplication.clipboard().setText(
            '\n'.join(self.rows[i]['job'].page_url or self.rows[i]['job'].url for i in ids)))
        m.addSeparator()
        m.addAction('Remove from list', lambda: [self.remove(i) for i in ids])
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def retry(self, job_id: int):
        row = self.rows[job_id]
        if row['state'] == 'running':
            return
        row['item'].setForeground(6, self.tree.palette().text())
        row['item'].setText(6, 'Queued')
        row['bar'].setValue(0)
        self._start(job_id)

    def cancel(self, job_id: int):
        row = self.rows[job_id]
        if row['state'] == 'running':
            row['job'].cancel.set()
            row['item'].setText(6, 'Cancelling…')

    def remove(self, job_id: int):
        self.cancel(job_id)
        row = self.rows.pop(job_id)
        self.tree.takeTopLevelItem(self.tree.indexOfTopLevelItem(row['item']))

    def retry_failed(self):
        for jid, r in list(self.rows.items()):
            if r['state'] in ('error', 'cancelled'):
                self.retry(jid)

    def clear_finished(self):
        for jid, r in list(self.rows.items()):
            if r['state'] in ('ok', 'cancelled'):
                self.remove(jid)

    def cancel_all(self):
        for jid in list(self.rows):
            self.cancel(jid)

    def closeEvent(self, e):
        running = [r for r in self.rows.values() if r['state'] == 'running']
        if running and QMessageBox.question(
                self, 'Downloads running', f'{len(running)} download(s) still running. Quit anyway?'
        ) != QMessageBox.StandardButton.Yes:
            e.ignore()
            return
        self.cancel_all()
        self.cookies.save()
        if self.browser:
            self.browser.close()
        self.pool.waitForDone(3000)
        e.accept()
