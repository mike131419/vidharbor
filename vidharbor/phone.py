"""Desktop side of phone access: runs the PhoneServer inside VidHarbor, the
Phone access dialog, Tailscale Funnel for a public HTTPS link, QR code."""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (QCheckBox, QDialog, QHBoxLayout, QLabel, QMessageBox,
                               QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from .server import PhoneServer, new_access_code

TAILSCALE_DOWNLOAD = 'https://tailscale.com/download/windows'
_NO_WINDOW = 0x08000000 if sys.platform == 'win32' else 0   # CREATE_NO_WINDOW


# ------------------------------------------------------------------ helpers
def lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(('192.0.2.1', 9))   # no packet is sent; picks the outgoing interface
            return s.getsockname()[0]
    except OSError:
        return '127.0.0.1'


def tailscale_exe() -> str | None:
    if found := shutil.which('tailscale'):
        return found
    for base in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramFiles(x86)', '')):
        p = Path(base or '') / 'Tailscale' / 'tailscale.exe'
        if base and p.is_file():
            return str(p)
    return None


def _ts(*args, timeout=30) -> tuple[int, str]:
    exe = tailscale_exe()
    if not exe:
        return 127, 'Tailscale is not installed.'
    try:
        r = subprocess.run([exe, *args], capture_output=True, text=True, timeout=timeout,
                           creationflags=_NO_WINDOW)
        return r.returncode, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired as e:
        out = ((e.stdout or b'') + (e.stderr or b'')).decode(errors='replace') if isinstance(e.stdout, bytes) else (e.stdout or '')
        return 124, (out.strip() or 'Tailscale did not answer in time.')
    except OSError as e:
        return 1, str(e)


def tailscale_url() -> str | None:
    """https://<pc>.<tailnet>.ts.net/ for this PC, if Tailscale is signed in."""
    code, out = _ts('status', '--json', timeout=15)
    if code != 0:
        return None
    try:
        name = json.loads(out)['Self']['DNSName'].rstrip('.')
    except (ValueError, KeyError, TypeError):
        return None
    return f'https://{name}/' if name else None


def qr_pixmap(text: str, size: int = 220, dark: str = '#1d1d1f') -> QPixmap:
    import qrcode
    q = qrcode.QRCode(border=2, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(text)
    q.make(fit=True)
    m = q.get_matrix()
    n = len(m)
    img = QImage(n, n, QImage.Format.Format_RGB32)
    img.fill(QColor('white'))
    for y, row in enumerate(m):
        for x, on in enumerate(row):
            if on:
                img.setPixelColor(x, y, QColor(dark))
    return QPixmap.fromImage(img.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio,
                                        Qt.TransformationMode.FastTransformation))


def keep_awake(on: bool):
    """Stop Windows sleeping while phone access is on (screen may still turn off)."""
    if sys.platform != 'win32':
        return
    try:
        import ctypes
        ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001
        ctypes.windll.kernel32.SetThreadExecutionState(ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0))
    except Exception:
        pass


# ------------------------------------------------------------------ controller
class PhoneAccess(QObject):
    """Owns the server. Lives on the GUI thread; the server calls back from
    worker threads through signals."""
    log = Signal(str)
    changed = Signal()
    _warm_request = Signal(object, object)   # (Job, threading.Event)

    def __init__(self, settings, cookies, parent=None):
        super().__init__(parent)
        self.s, self.cookies = settings, cookies
        self.server: PhoneServer | None = None
        self.public_url: str | None = None
        self._warm_request.connect(self._do_warm)

    # settings
    def code(self) -> str:
        code = self.s.get('phone_code')
        if not code:
            code = new_access_code()
            self.s.set('phone_code', code)
        return code

    @property
    def running(self) -> bool:
        return bool(self.server and self.server.running)

    def start(self) -> str:
        """Start the server; returns an error message or ''."""
        if self.running:
            return ''
        from .ui import Settings

        def options():
            return Settings().options()   # QSettings: a fresh object per thread

        try:
            self.server = PhoneServer(
                port=self.s.get('phone_port'), access_code=self.code(), options=options,
                before_download=self._before_download, keep_hours=self.s.get('phone_keep_hours'),
                log=self.log.emit, log_detail=lambda _t: None, on_change=self.changed.emit)
            self.server.start()
        except OSError as e:
            self.server = None
            return (f'Could not start on port {self.s.get("phone_port")} ({e.strerror or e}). '
                    'Another program may be using it; pick a different port.')
        keep_awake(self.s.get('phone_keep_awake'))
        threading.Thread(target=self._find_public_url, daemon=True).start()
        self.changed.emit()
        return ''

    def stop(self):
        if self.server:
            self.server.stop()
            self.server = None
        keep_awake(False)
        self.changed.emit()

    def new_code(self) -> str:
        code = new_access_code()
        self.s.set('phone_code', code)
        if self.running:
            self.stop()
            self.start()
        return code

    def signed_in(self) -> int:
        return self.server.tokens.count() if self.server else 0

    def local_url(self) -> str:
        port = self.server.port if self.server else self.s.get('phone_port')
        return f'http://{lan_ip()}:{port}/'

    def best_url(self) -> str:
        return self.public_url or self.local_url()

    def _find_public_url(self):
        code, out = _ts('funnel', 'status', timeout=15)
        if code == 0 and 'Funnel on' in out and self._funnel_points_here(out):
            self.public_url = tailscale_url()
        else:
            self.public_url = None
        self.changed.emit()

    def _funnel_points_here(self, status: str) -> bool:
        port = self.server.port if self.server else self.s.get('phone_port')
        return f'127.0.0.1:{port}' in status or f'localhost:{port}' in status

    # Douyin/RedNote/Kuaishou cookies come from the built-in browser profile,
    # which lives on the GUI thread.
    def _before_download(self, job):
        done = threading.Event()
        self._warm_request.emit(job, done)
        done.wait(30)

    def _do_warm(self, job, done):
        if self.s.get('cookie_mode') != 'builtin':
            done.set()
            return
        self.cookies.warm(job.platform.key, lambda _ok: done.set())


# ------------------------------------------------------------------ dialog
class _Worker(QObject):
    finished = Signal(int, str)


class PhoneDialog(QDialog):
    def __init__(self, access: PhoneAccess, parent=None):
        super().__init__(parent)
        self.a, self.s = access, access.s
        self.setWindowTitle('Phone access')
        self.setMinimumWidth(640)
        v = QVBoxLayout(self)
        v.setSpacing(10)

        intro = QLabel(
            'Let your phone, and a few friends\' iPhones or Android phones, use VidHarbor through a web '
            'app. Downloads run on <b>this PC</b>, so it must be switched on with VidHarbor open.')
        intro.setWordWrap(True)
        v.addWidget(intro)

        top = QHBoxLayout()
        self.toggle = QPushButton()
        self.toggle.setObjectName('primary')
        self.toggle.setMinimumHeight(36)
        self.toggle.clicked.connect(self._toggle)
        self.state = QLabel()
        top.addWidget(self.toggle)
        top.addWidget(self.state, 1)
        v.addLayout(top)

        body = QHBoxLayout()
        left_box = QWidget()
        left_box.setFixedSize(236, 262)   # fixed, so the layout can never squeeze the QR code
        left = QVBoxLayout(left_box)
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(6)
        self.qr = QLabel(alignment=Qt.AlignmentFlag.AlignCenter)
        self.qr.setFixedSize(230, 230)
        self.qr.setStyleSheet('background: white; border-radius: 8px;')
        left.addWidget(self.qr, 0, Qt.AlignmentFlag.AlignHCenter)
        qr_note = QLabel('Scan with the iPhone camera')
        qr_note.setAlignment(Qt.AlignmentFlag.AlignCenter)
        qr_note.setStyleSheet('color: gray')
        left.addWidget(qr_note)
        body.addWidget(left_box, 0, Qt.AlignmentFlag.AlignTop)

        right = QVBoxLayout()
        right.addWidget(QLabel('<b>Access code</b> – friends type this once'))
        code_row = QHBoxLayout()
        self.code_label = QLabel()
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.code_label.setStyleSheet('font-size: 22px; font-weight: 700; letter-spacing: 2px;')
        copy_code = QPushButton('Copy')
        copy_code.clicked.connect(lambda: self._copy(self.a.code()))
        new_code = QPushButton('New code')
        new_code.setToolTip('Makes a new code and signs out every phone')
        new_code.clicked.connect(self._new_code)
        code_row.addWidget(self.code_label, 1)
        code_row.addWidget(copy_code)
        code_row.addWidget(new_code)
        right.addLayout(code_row)
        self.phones = QLabel()
        self.phones.setStyleSheet('color: gray')
        right.addWidget(self.phones)

        right.addSpacing(6)
        right.addWidget(QLabel('<b>Link</b>'))
        self.links = QLabel()
        self.links.setWordWrap(True)
        self.links.setTextInteractionFlags(Qt.TextInteractionFlag.TextBrowserInteraction)
        self.links.setOpenExternalLinks(True)
        right.addWidget(self.links)
        link_row = QHBoxLayout()
        copy_link = QPushButton('Copy link')
        copy_link.clicked.connect(lambda: self._copy(self.a.best_url()))
        self.funnel_btn = QPushButton()
        self.funnel_btn.clicked.connect(self._funnel)
        link_row.addWidget(copy_link)
        link_row.addWidget(self.funnel_btn)
        link_row.addStretch()
        right.addLayout(link_row)
        right.addStretch()
        body.addLayout(right, 1)
        v.addLayout(body)

        opts = QHBoxLayout()
        self.autostart = QCheckBox('Start when VidHarbor opens', checked=self.s.get('phone_enabled'))
        self.autostart.toggled.connect(lambda c: self.s.set('phone_enabled', c))
        self.awake = QCheckBox('Keep this PC awake', checked=self.s.get('phone_keep_awake'))
        self.awake.toggled.connect(self._awake)
        self.port = QSpinBox(minimum=1024, maximum=65535, value=self.s.get('phone_port'))
        self.port.valueChanged.connect(lambda p: self.s.set('phone_port', p))
        opts.addWidget(self.autostart)
        opts.addWidget(self.awake)
        opts.addStretch()
        opts.addWidget(QLabel('Port'))
        opts.addWidget(self.port)
        v.addLayout(opts)

        self.out = QPlainTextEdit(readOnly=True, maximumHeight=90)
        self.out.setPlaceholderText('Tailscale messages appear here')
        self.out.setVisible(False)
        v.addWidget(self.out)

        help_ = QLabel(
            '<b>How friends install it on iPhone:</b> open the link in <b>Safari</b> → enter the code → '
            'tap Share → <b>Add to Home Screen</b>. Then: copy a link in Douyin/RedNote/any app → open '
            'VidHarbor → Paste → Download → <b>Save video</b>.<br>'
            '<b>On your Wi-Fi only</b> the plain link works right away (allow VidHarbor through the Windows '
            'firewall if asked). <b>For use anywhere</b>, turn on the internet link (free, uses Tailscale '
            'Funnel; nothing to install on the phones).')
        help_.setWordWrap(True)
        help_.setStyleSheet('color: gray')
        v.addWidget(help_)

        self.a.changed.connect(self._refresh)
        self._timer = QTimer(self, interval=5000, timeout=self._refresh)
        self._timer.start()
        self._refresh()
        self.adjustSize()
        self._fit()

    def _fit(self):
        """Keep the window tall enough for its contents. Qt underestimates
        word-wrapped labels, which squeezed the QR code row, so compute the
        height for the actual width ourselves."""
        lay = self.layout()
        lay.activate()
        min_w = max(640, lay.totalMinimumSize().width())   # e.g. the access code must fit in full
        self.setMinimumWidth(min_w)
        w = max(self.width(), min_w)
        h = lay.totalHeightForWidth(w) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        h = max(h, lay.totalMinimumSize().height())
        self.setMinimumHeight(h)
        if self.height() < h:
            self.resize(w, h)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            QTimer.singleShot(0, self._fit)   # narrower window -> taller wrapped text

    # ---------------------------------------------------------------- actions
    def _copy(self, text: str):
        QGuiApplication.clipboard().setText(text)

    def _toggle(self):
        if self.a.running:
            self.a.stop()
        elif err := self.a.start():
            QMessageBox.warning(self, 'Phone access', err)
        self._refresh()

    def _new_code(self):
        if QMessageBox.question(self, 'New access code',
                                'Make a new code? Every phone will have to sign in again with it.') \
                == QMessageBox.StandardButton.Yes:
            self.a.new_code()
            self._refresh()

    def _awake(self, on: bool):
        self.s.set('phone_keep_awake', on)
        if self.a.running:
            keep_awake(on)

    def _run_ts(self, args: list[str], after):
        self.funnel_btn.setEnabled(False)
        self.out.setVisible(True)
        self._fit()
        self.out.appendPlainText('> tailscale ' + ' '.join(args))
        w = _Worker(self)

        def done(code, text):
            self.out.appendPlainText(text or f'(exit {code})')
            self.funnel_btn.setEnabled(True)
            after(code, text)
        w.finished.connect(done)
        threading.Thread(target=lambda: w.finished.emit(*_ts(*args, timeout=60)), daemon=True).start()

    def _funnel(self):
        if not tailscale_exe():
            QMessageBox.information(
                self, 'Internet link',
                'The internet link uses Tailscale (free).\n\n'
                '1. Install Tailscale for Windows and sign in (Google or Microsoft account is fine).\n'
                '2. Come back here and click "Turn on internet link".\n\n'
                'Your friends do not need Tailscale; they just open the link.')
            QDesktopServices.openUrl(QUrl(TAILSCALE_DOWNLOAD))
            return
        if not self.a.running and (err := self.a.start()):
            QMessageBox.warning(self, 'Phone access', err)
            return
        port = self.a.server.port
        if self.a.public_url:
            def off(code, _t):
                self.a.public_url = None
                self._refresh()
            self._run_ts(['funnel', '--https=443', 'off'], off)
            return

        def on(code, text):
            if code == 0:
                threading.Thread(target=self.a._find_public_url, daemon=True).start()
            elif 'login.tailscale.com' in text or 'enable' in text.lower():
                self.out.appendPlainText('\nTailscale needs Funnel switched on for your account: open the '
                                         'link above, approve it, then click the button again.')
        self._run_ts(['funnel', '--bg', str(port)], on)

    # ---------------------------------------------------------------- display
    def _refresh(self):
        running = self.a.running
        self.toggle.setText('Stop phone access' if running else 'Start phone access')
        self.state.setText('<span style="color:#1f8a4c">● Running</span>' if running
                           else '<span style="color:gray">● Off</span>')
        self.code_label.setText(self.a.code())
        n = self.a.signed_in()
        self.phones.setText(f'{n} phone(s) signed in' if running else '')
        self.port.setEnabled(not running)

        lines = []
        if running:
            lines.append(f'On this Wi-Fi: <a href="{self.a.local_url()}">{self.a.local_url()}</a>')
            if self.a.public_url:
                lines.insert(0, f'Anywhere: <a href="{self.a.public_url}"><b>{self.a.public_url}</b></a>')
            else:
                lines.append('<span style="color:gray">Internet link is off – the app only works on '
                             'this Wi-Fi, and iPhone can\'t install it as an app without the https link.</span>')
        else:
            lines.append('<span style="color:gray">Start phone access to get the link.</span>')
        self.links.setText('<br>'.join(lines))
        if hasattr(self, '_timer'):
            QTimer.singleShot(0, self._fit)   # link text changed height
        if not tailscale_exe():
            self.funnel_btn.setText('Set up internet link…')
        else:
            self.funnel_btn.setText('Turn off internet link' if self.a.public_url else 'Turn on internet link')

        if running:
            self.qr.setPixmap(qr_pixmap(self.a.best_url()))
        else:
            self.qr.setText('<span style="color:gray">QR code appears<br>when running</span>')

    def done(self, r):
        self._timer.stop()
        try:
            self.a.changed.disconnect(self._refresh)
        except (RuntimeError, TypeError):
            pass
        super().done(r)
