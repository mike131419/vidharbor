"""VidHarbor extras for yt-dlp on Android (loaded with --plugin-dirs).

- Douyin without cookies: reads the mobile share page instead of the web API
  that asks for fresh cookies. Falls back to yt-dlp's own Douyin extractor.
- Short links from Chinese apps (v.douyin.com, xhslink.com, v.kuaishou.com,
  b23.tv): followed to the real page before extraction.
- Kuaishou (not in yt-dlp): reads the page's Apollo state.

Plugin extractors are tried before yt-dlp's built-in ones.
"""
import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, float_or_none, int_or_none, traverse_obj

MOBILE_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 '
             '(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1')


def _unescape(s):
    return s.replace('\\u002F', '/').replace('\\/', '/').replace('\\u0026', '&')


class VidHarborShortLinkIE(InfoExtractor):
    IE_NAME = 'vidharbor:shortlink'
    IE_DESC = False
    _VALID_URL = (r'https?://(?:v\.douyin\.com|(?:www\.)?xhslink\.com|v\.kuaishou\.com|b23\.tv|'
                  r'v\.m\.chenzhongtech\.com|v\.ixigua\.com)/(?P<id>[^?#]+)')

    def _real_extract(self, url):
        short_id = self._match_id(url).strip('/') or 'link'
        urlh = self._request_webpage(url, short_id, 'Following short link',
                                     headers={'User-Agent': MOBILE_UA})
        final = urlh.url
        if final.rstrip('/') == url.rstrip('/'):
            raise ExtractorError('This short link did not lead to a video page.', expected=True)
        # RedNote app pages -> the web page yt-dlp understands (keeps xsec_token)
        m = re.search(r'xiaohongshu\.com/(?:discovery/item|explore|user/profile/[^/]+)/([0-9a-f]{24})(\?[^#]*)?', final)
        if m:
            final = f'https://www.xiaohongshu.com/explore/{m.group(1)}{m.group(2) or ""}'
        return self.url_result(final)


class VidHarborDouyinIE(InfoExtractor):
    IE_NAME = 'vidharbor:douyin'
    IE_DESC = False
    _VALID_URL = [
        r'https?://(?:www\.)?iesdouyin\.com/share/(?:video|note|slides)/(?P<id>\d+)',
        r'https?://(?:www\.)?douyin\.com/(?:video|note)/(?P<id>\d+)',
        r'https?://(?:www\.)?douyin\.com/[^?#]*\?(?:[^#]*&)?(?:modal_id|vid)=(?P<id>\d+)',
    ]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        try:
            webpage = self._download_webpage(
                f'https://www.iesdouyin.com/share/video/{video_id}/', video_id,
                'Downloading share page', headers={'User-Agent': MOBILE_UA, 'Referer': 'https://www.douyin.com/'})
            return parse_douyin_router_data(webpage, video_id, self._search_json)
        except ExtractorError as e:
            if 'image post' in str(e):
                raise
            self.report_warning(f'Share page did not work ({e.orig_msg if hasattr(e, "orig_msg") else e}); '
                                'trying the Douyin web page (needs cookies)')
            return self.url_result(f'https://www.douyin.com/video/{video_id}', 'Douyin', video_id)


def parse_douyin_router_data(webpage, video_id, search_json):
    data = search_json(r'window\._ROUTER_DATA\s*=', webpage, 'router data', video_id,
                       end_pattern=r'</script>', default={})
    item = None
    for page in (traverse_obj(data, ('loaderData', {dict.values})) or []):
        item = traverse_obj(page, ('videoInfoRes', 'item_list', 0, {dict}))
        if item:
            break
    if not item:
        raise ExtractorError('Douyin share page has no video data', expected=True)
    video = item.get('video') or {}
    play = traverse_obj(video, ('play_addr', 'url_list', 0)) or ''
    if not play and (uri := traverse_obj(video, ('play_addr', 'uri'))):
        play = f'https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0'
    if not play:
        if item.get('images'):
            raise ExtractorError('This Douyin link is an image post, not a video.', expected=True)
        raise ExtractorError('Douyin did not return a video address', expected=True)
    return {
        'id': str(item.get('aweme_id') or video_id),
        'title': (item.get('desc') or '').strip() or f'douyin_{video_id}',
        'url': play.replace('/playwm/', '/play/'),
        'ext': 'mp4',
        'vcodec': 'h264',
        'acodec': 'aac',
        'uploader': traverse_obj(item, ('author', 'nickname')),
        'thumbnail': traverse_obj(video, ('cover', 'url_list', 0)),
        'duration': float_or_none(video.get('duration'), 1000),
        'timestamp': int_or_none(item.get('create_time')),
        'width': int_or_none(video.get('width')),
        'height': int_or_none(video.get('height')),
        'webpage_url': f'https://www.douyin.com/video/{video_id}',
        'http_headers': {'User-Agent': MOBILE_UA, 'Referer': 'https://www.douyin.com/'},
    }


class VidHarborKuaishouIE(InfoExtractor):
    IE_NAME = 'vidharbor:kuaishou'
    IE_DESC = False
    _VALID_URL = [
        r'https?://(?:www\.)?kuaishou\.com/short-video/(?P<id>[\w-]+)',
        r'https?://(?:[\w-]+\.)?(?:kuaishou\.com|chenzhongtech\.com|gifshow\.com)/(?:fw/)?photo/(?P<id>[\w-]+)',
    ]

    def _real_extract(self, url):
        video_id = self._match_id(url)
        page_url = f'https://www.kuaishou.com/short-video/{video_id}'
        webpage = self._download_webpage(page_url, video_id, headers={'Referer': 'https://www.kuaishou.com/'})
        state = self._search_json(r'window\.__APOLLO_STATE__\s*=', webpage, 'apollo state', video_id, default={})
        photo = next((v for v in (traverse_obj(state, ('defaultClient', {dict.values})) or [])
                      if isinstance(v, dict) and v.get('photoUrl')), None)
        if photo:
            video_url = _unescape(photo['photoUrl'])
            title, thumb = photo.get('caption'), photo.get('coverUrl')
            duration = float_or_none(photo.get('duration'), 1000)
        else:
            m = re.search(r'"photoUrl"\s*:\s*"([^"]+)"', webpage)
            if not m:
                raise ExtractorError('Kuaishou did not return the video (it probably asked for a captcha). '
                                     'Try again later.', expected=True)
            video_url, title, thumb, duration = _unescape(m.group(1)), None, None, None
        return {
            'id': video_id,
            'title': title or self._og_search_title(webpage, default=None) or f'kuaishou_{video_id}',
            'url': video_url,
            'ext': 'mp4',
            'thumbnail': thumb and _unescape(thumb),
            'duration': duration,
            'webpage_url': page_url,
            'http_headers': {'Referer': 'https://www.kuaishou.com/'},
        }
