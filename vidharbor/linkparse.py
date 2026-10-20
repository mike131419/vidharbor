"""Find links in pasted text (including Chinese app share text), detect the
platform, and rewrite app/mobile/share URLs into the form yt-dlp expects.

Pure functions only - no network, no Qt - so they are easy to test.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlsplit, urlunsplit

# A URL ends at whitespace or at full-width punctuation that share texts put
# right after the link (e.g. "http://xhslink.com/a/AbC，复制本条信息").
_URL_RE = re.compile(r'https?://[^\s<>"\'　-〿＀-￯【】《》“”‘’]+', re.I)
_TRAILING = '.,;:!?)]}>\'"'


@dataclass(frozen=True)
class Platform:
    key: str
    label: str        # shown in the queue
    supported: bool   # False = we know a plain link cannot be downloaded
    note: str = ''    # shown when not supported / needs attention


PLATFORMS = {
    'douyin':    Platform('douyin', '抖音 Douyin', True),
    'xhs':       Platform('xhs', '小红书 RedNote', True),
    'kuaishou':  Platform('kuaishou', '快手 Kuaishou', True, 'experimental'),
    'bilibili':  Platform('bilibili', 'B站 Bilibili', True),
    'weibo':     Platform('weibo', '微博 Weibo', True),
    'ixigua':    Platform('ixigua', '西瓜 Ixigua', True),
    'toutiao':   Platform('toutiao', '头条 Toutiao', True),
    'zhihu':     Platform('zhihu', '知乎 Zhihu', True),
    'youku':     Platform('youku', '优酷 Youku', True),
    'iqiyi':     Platform('iqiyi', '爱奇艺 iQiyi', True),
    'vqq':       Platform('vqq', '腾讯视频 Tencent', True),
    'acfun':     Platform('acfun', 'AcFun', True),
    'huya':      Platform('huya', '虎牙 Huya', True),
    'douyu':     Platform('douyu', '斗鱼 Douyu', True),
    'wx_article': Platform('wx_article', '公众号 WeChat article', True, 'best effort'),
    'wx_channels': Platform(
        'wx_channels', '视频号 WeChat Channels', False,
        'WeChat Channels videos only play inside the WeChat app and are encrypted, '
        'so they cannot be downloaded from a share link.'),
    'youtube':   Platform('youtube', 'YouTube', True),
    'tiktok':    Platform('tiktok', 'TikTok', True),
    'instagram': Platform('instagram', 'Instagram', True),
    'facebook':  Platform('facebook', 'Facebook', True),
    'x':         Platform('x', 'X / Twitter', True),
    'other':     Platform('other', 'Web', True),
}

# host suffix -> platform key (checked longest suffix first)
_HOSTS = {
    'douyin.com': 'douyin', 'iesdouyin.com': 'douyin', 'douyinvod.com': 'douyin',
    'xiaohongshu.com': 'xhs', 'xhslink.com': 'xhs',
    'kuaishou.com': 'kuaishou', 'chenzhongtech.com': 'kuaishou', 'gifshow.com': 'kuaishou',
    'kwai.com': 'kuaishou',
    'bilibili.com': 'bilibili', 'b23.tv': 'bilibili',
    'weibo.com': 'weibo', 'weibo.cn': 'weibo',
    'ixigua.com': 'ixigua', 'toutiao.com': 'toutiao',
    'zhihu.com': 'zhihu', 'youku.com': 'youku', 'iqiyi.com': 'iqiyi',
    'v.qq.com': 'vqq', 'acfun.cn': 'acfun', 'huya.com': 'huya', 'douyu.com': 'douyu',
    'mp.weixin.qq.com': 'wx_article',
    'channels.weixin.qq.com': 'wx_channels', 'finder.video.qq.com': 'wx_channels',
    'youtube.com': 'youtube', 'youtu.be': 'youtube',
    'tiktok.com': 'tiktok', 'instagram.com': 'instagram',
    'facebook.com': 'facebook', 'fb.watch': 'facebook',
    'twitter.com': 'x', 'x.com': 'x',
}

# Short links that only redirect somewhere else; resolve them before yt-dlp.
SHORT_HOSTS = (
    'v.douyin.com', 'xhslink.com', 'v.kuaishou.com', 'b23.tv', 't.cn',
    'url.cn', 'v.ixigua.com', 'm.toutiao.com/is/',
)


def extract_urls(text: str) -> list[str]:
    """Return unique URLs from free text, in order. Handles share text such as
    '7.43 复制打开抖音，看看【xx的作品】... https://v.douyin.com/iRNBho6u/ 07/12'."""
    seen, out = set(), []
    for m in _URL_RE.finditer(text or ''):
        url = m.group(0).rstrip(_TRAILING)
        if url and url not in seen:
            seen.add(url)
            out.append(url)
    return out


def _host(url: str) -> str:
    return (urlsplit(url).hostname or '').lower()


def detect_platform(url: str) -> Platform:
    host = _host(url)
    for suffix in sorted(_HOSTS, key=len, reverse=True):
        if '/' in suffix:
            continue
        if host == suffix or host.endswith('.' + suffix):
            return PLATFORMS[_HOSTS[suffix]]
    if 'weixin.qq.com' in host and ('/sph' in url or 'finder' in url):
        return PLATFORMS['wx_channels']
    return PLATFORMS['other']


def is_short_link(url: str) -> bool:
    host = _host(url)
    full = host + urlsplit(url).path
    return any(full.startswith(h) if '/' in h else (host == h or host.endswith('.' + h))
               for h in SHORT_HOSTS)


def normalize(url: str) -> str:
    """Rewrite app/mobile/share-page URLs into the canonical page yt-dlp handles."""
    parts = urlsplit(url)
    host = (parts.hostname or '').lower()
    path = parts.path
    qs = parse_qs(parts.query)

    # --- Douyin: yt-dlp only accepts https://www.douyin.com/video/<id>
    if host.endswith('douyin.com'):
        if m := re.search(r'/(?:share/)?(?:video|note|slides)/(\d{8,})', path):
            kind = 'note' if '/note/' in path or '/slides/' in path else 'video'
            return f'https://www.douyin.com/{kind}/{m.group(1)}'
        for key in ('modal_id', 'vid', 'aweme_id'):
            if qs.get(key) and qs[key][0].isdigit():
                return f'https://www.douyin.com/video/{qs[key][0]}'

    # --- RedNote: keep xsec_token query, rewrite profile/discovery variants
    if host.endswith('xiaohongshu.com'):
        m = (re.search(r'/(?:explore|discovery/item)/([0-9a-f]{24})', path)
             or re.search(r'/user/profile/[^/]+/([0-9a-f]{24})', path))
        if m:
            return urlunsplit(('https', 'www.xiaohongshu.com', f'/explore/{m.group(1)}',
                               parts.query, ''))

    # --- Kuaishou: mobile share pages -> desktop short-video page
    if host.endswith(('kuaishou.com', 'chenzhongtech.com', 'gifshow.com')):
        m = (re.search(r'/(?:short-video|fw/photo|photo)/([\w-]+)', path))
        if m:
            return f'https://www.kuaishou.com/short-video/{m.group(1)}'
        if qs.get('photoId'):
            return f'https://www.kuaishou.com/short-video/{qs["photoId"][0]}'

    # --- Bilibili mobile
    if host == 'm.bilibili.com' and (m := re.search(r'/video/(BV\w+|av\d+)', path)):
        return f'https://www.bilibili.com/video/{m.group(1)}'

    # --- Weibo: h5 pages
    if host in ('m.weibo.cn', 'weibo.cn') and (m := re.search(r'/(?:status|detail)/(\w+)', path)):
        return f'https://m.weibo.cn/status/{m.group(1)}'

    return url


def why_unsupported(url: str) -> str:
    """Return a user-facing reason if we already know the link can't work."""
    p = detect_platform(url)
    if not p.supported:
        return p.note
    if p.key == 'douyin' and '/note/' in url:
        return 'This Douyin link is an image post (图文), not a video.'
    return ''
