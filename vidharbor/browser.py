"""Built-in browser: sign in to sites, keep their cookies in a cookies.txt that
downloads use automatically, and capture video streams from any page
("Detected media") for sites yt-dlp cannot read on its own (Kuaishou,
WeChat article videos, ...)."""
from __future__ import annotations

import re
import time
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, QTimer, QUrl, Qt, Signal
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile,
                                     QWebEngineUrlRequestInfo,
                                     QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QPushButton,
                               QSplitter, QToolBar, QVBoxLayout, QWidget)

from . import engine

CHROME_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
             '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')

QUICK_SITES = [
    ('抖音', 'https://www.douyin.com/'), ('小红书', 'https://www.xiaohongshu.com/explore'),
    ('快手', 'https://www.kuaishou.com/'), ('B站', 'https://www.bilibili.com/'),
    ('微博', 'https://weibo.com/'), ('YouTube', 'https://www.youtube.com/'),
    ('TikTok', 'https://www.tiktok.com/'), ('Instagram', 'https://www.instagram.com/'),
    ('Facebook', 'https://www.facebook.com/'),
]

# Visiting the home page once gives the anonymous cookies these sites check.
WARMUPS = {
    'douyin': ('https://www.douyin.com/', 'douyin.com', ('s_v_web_id',)),
    'kuaishou': ('https://www.kuaishou.com/', 'kuaishou.com', ('did',)),
    'xhs': ('https://www.xiaohongshu.com/explore', 'xiaohongshu.com', ('a1', 'webId')),
}

_MEDIA_EXT = re.compile(r'\.(mp4|m3u8|flv|webm|mov|m4a|mp3)(?:$|[?#])', re.I)
_SKIP = re.compile(r'\.(ts|m4s|aac)(?:$|[?#])|/(ad|ads|adv)/', re.I)


def _netscape_line(c) -> str:
    domain = bytes(c.domain()).decode() if not isinstance(c.domain(), str) else c.domain()
    include_sub = 'TRUE' if domain.startswith('.') else 'FALSE'
    exp = c.expirationDate()
    expires = int(exp.toSecsSinceEpoch()) if exp.isValid() else int(time.time()) + 7 * 86400
    name = bytes(c.name()).decode('utf-8', 'replace')
    value = bytes(c.value()).decode('utf-8', 'replace')
    prefix = '#HttpOnly_' if c.isHttpOnly() else ''
    return '\t'.join([prefix + domain, include_sub, c.path() or '/',
                      'TRUE' if c.isSecure() else 'FALSE', str(expires), name, value])


class MediaInterceptor(QWebEngineUrlRequestInterceptor):
    media = Signal(str, str)  # media url, first-party page url

    def interceptRequest(self, info: QWebEngineUrlRequestInfo):
        url = info.requestUrl().toString()
        if not url.startswith('http') or _SKIP.search(url):
            return
        is_media = info.resourceType() == QWebEngineUrlRequestInfo.ResourceType.ResourceTypeMedia
        if is_media or _MEDIA_EXT.search(urlsplit(url).path + '?'):
            self.media.emit(url, info.firstPartyUrl().toString())


class CookieManager(QObject):
    """Owns the shared browser profile and mirrors its cookies to cookies.txt."""
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.profile = QWebEngineProfile('VidHarbor', self)
        store_dir = str(engine.data_dir() / 'browser')
        self.profile.setPersistentStoragePath(store_dir)
        self.profile.setCachePath(store_dir + '/cache')
        self.profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies)
        self.profile.setHttpUserAgent(CHROME_UA)
        self.interceptor = MediaInterceptor(self)
        self.profile.setUrlRequestInterceptor(self.interceptor)

        self._cookies: dict[tuple, object] = {}
        self._save_timer = QTimer(self, singleShot=True, interval=800, timeout=self.save)
        store = self.profile.cookieStore()
        store.cookieAdded.connect(self._added)
        store.cookieRemoved.connect(self._removed)
        store.loadAllCookies()
        self._warming: dict[str, dict] = {}

    @staticmethod
    def _key(c):
        return (c.domain(), c.path(), bytes(c.name()))

    def _added(self, c):
        self._cookies[self._key(c)] = c
        self._save_timer.start()

    def _removed(self, c):
        self._cookies.pop(self._key(c), None)
        self._save_timer.start()

    def save(self):
        lines = ['# Netscape HTTP Cookie File', '# Written by VidHarbor built-in browser', '']
        lines += [_netscape_line(c) for c in self._cookies.values()]
        engine.cookie_file().write_text('\n'.join(lines) + '\n', 'utf-8')
        self.changed.emit()

    def has(self, domain_suffix: str, names=()) -> bool:
        for c in self._cookies.values():
            if c.domain().lstrip('.').endswith(domain_suffix):
                if not names or bytes(c.name()).decode() in names:
                    return True
        return False

    def domains(self) -> list[str]:
        return sorted({c.domain().lstrip('.') for c in self._cookies.values()})

    def clear(self):
        self.profile.cookieStore().deleteAllCookies()
        self._cookies.clear()
        self.save()

    def warm(self, platform_key: str, callback, timeout_ms: int = 20000):
        """Make sure the site's anonymous cookies exist, loading its home page
        invisibly if needed. callback(ok: bool) runs on the GUI thread."""
        spec = WARMUPS.get(platform_key)
        if not spec or self.has(spec[1], spec[2]):
            callback(True)
            return
        if platform_key in self._warming:
            self._warming[platform_key]['callbacks'].append(callback)
            return
        url, suffix, names = spec
        page = QWebEnginePage(self.profile, self)
        state = {'callbacks': [callback], 'page': page, 'start': time.monotonic()}
        self._warming[platform_key] = state
        poll = QTimer(self, interval=500)

        def check():
            done = self.has(suffix, names)
            if done or (time.monotonic() - state['start']) * 1000 > timeout_ms:
                poll.stop()
                poll.deleteLater()
                self.save()
                QTimer.singleShot(1500, page.deleteLater)  # let late cookies land
                for cb in self._warming.pop(platform_key)['callbacks']:
                    cb(done)
        poll.timeout.connect(check)
        poll.start()
        page.load(QUrl(url))


class BrowserWindow(QMainWindow):
    add_page = Signal(str)              # send the current page link through yt-dlp
    add_media = Signal(str, str, str)   # media url, page url, title

    def __init__(self, cookies: CookieManager, parent=None):
        super().__init__(parent)
        self.cookies = cookies
        self.setWindowTitle('VidHarbor – Built-in browser')
        self.resize(1280, 820)

        self.view = QWebEngineView(self)
        self.view.setPage(QWebEnginePage(cookies.profile, self.view))
        self.view.urlChanged.connect(lambda u: self.address.setText(u.toString()))
        self.view.titleChanged.connect(lambda t: self.setWindowTitle(f'{t} – VidHarbor browser'))

        tb = QToolBar('Navigation', self)
        tb.setMovable(False)
        self.addToolBar(tb)
        for text, slot in (('◀', self.view.back), ('▶', self.view.forward), ('⟳', self.view.reload)):
            act = QAction(text, self)
            act.triggered.connect(slot)
            tb.addAction(act)
        self.address = QLineEdit(placeholderText='Paste a link or type an address')
        self.address.returnPressed.connect(lambda: self.open(self.address.text()))
        tb.addWidget(self.address)
        add_btn = QPushButton('Download this page')
        add_btn.setObjectName('primary')
        add_btn.clicked.connect(lambda: self.add_page.emit(self.view.url().toString()))
        tb.addWidget(add_btn)

        sites = QToolBar('Sites', self)
        sites.setMovable(False)
        self.addToolBarBreak()
        self.addToolBar(sites)
        for name, url in QUICK_SITES:
            act = QAction(name, self)
            act.triggered.connect(lambda _=False, u=url: self.open(u))
            sites.addAction(act)

        # right panel: detected media
        panel = QWidget()
        pv = QVBoxLayout(panel)
        pv.setContentsMargins(8, 8, 8, 8)
        head = QLabel('<b>Detected media</b><br><span style="color:gray">Play the video on the page; '
                      'its stream shows up here.</span>')
        head.setWordWrap(True)
        self.media_list = QListWidget()
        self.media_list.itemDoubleClicked.connect(lambda _: self._download_selected())
        row = QHBoxLayout()
        dl = QPushButton('Download selected')
        dl.setObjectName('primary')
        dl.clicked.connect(self._download_selected)
        clr = QPushButton('Clear')
        clr.clicked.connect(self.media_list.clear)
        row.addWidget(dl)
        row.addWidget(clr)
        self.cookie_label = QLabel()
        self.cookie_label.setWordWrap(True)
        self.cookie_label.setStyleSheet('color: gray')
        pv.addWidget(head)
        pv.addWidget(self.media_list, 1)
        pv.addLayout(row)
        pv.addWidget(self.cookie_label)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self.view)
        split.addWidget(panel)
        split.setSizes([960, 320])
        self.setCentralWidget(split)

        self._seen: set[str] = set()
        cookies.interceptor.media.connect(self._on_media)
        cookies.changed.connect(self._update_cookie_label)
        self._update_cookie_label()

    def open(self, url: str):
        url = url.strip()
        if url and not re.match(r'^[a-z]+://', url):
            url = 'https://' + url
        self.view.load(QUrl(url))
        self.show()
        self.raise_()
        self.activateWindow()

    def _update_cookie_label(self):
        doms = [d for d in self.cookies.domains()
                if any(k in d for k in ('douyin', 'xiaohongshu', 'kuaishou', 'bilibili', 'weibo',
                                         'youtube', 'tiktok', 'instagram', 'facebook', 'qq.com'))]
        sites = sorted({'.'.join(d.split('.')[-2:]) for d in doms})
        self.cookie_label.setText(
            'Sign-ins here are saved and used for downloads automatically.'
            + (f'<br>Cookies held for: {", ".join(sites)}' if sites else ''))

    def _on_media(self, url: str, page: str):
        if not self.isVisible():
            return
        key = urlsplit(url)._replace(query='', fragment='').geturl()
        if key in self._seen:
            return
        self._seen.add(key)
        path = urlsplit(url).path
        m = _MEDIA_EXT.search(path + '?')
        kind = m.group(1).upper() if m else 'STREAM'
        host = urlsplit(url).hostname or ''
        item = QListWidgetItem(f'{kind}  ·  {host}\n{self.view.title()[:60]}')
        item.setData(Qt.ItemDataRole.UserRole, (url, page or self.view.url().toString(), self.view.title()))
        item.setToolTip(url)
        self.media_list.insertItem(0, item)
        while self.media_list.count() > 100:
            self.media_list.takeItem(self.media_list.count() - 1)

    def _download_selected(self):
        for item in self.media_list.selectedItems() or [self.media_list.item(0)]:
            if item:
                self.add_media.emit(*item.data(Qt.ItemDataRole.UserRole))
