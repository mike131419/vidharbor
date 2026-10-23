"""Extra extractors for sites yt-dlp does not cover.

These are registered ahead of yt-dlp's own list (see downloader.make_ydl).
"""
from __future__ import annotations

import re

from yt_dlp.extractor.common import InfoExtractor
from yt_dlp.utils import ExtractorError, float_or_none, int_or_none, traverse_obj


def _unescape(s: str) -> str:
    return s.replace('\\u002F', '/').replace('\\/', '/').replace('\\u0026', '&')


class KuaishouIE(InfoExtractor):
    """Experimental: reads the video URL from the page's Apollo state.
    Kuaishou often shows a slider captcha to non-browser clients; in that case
    the user is pointed to the built-in browser, which captures the stream."""
    IE_NAME = 'kuaishou'
    _VALID_URL = r'https?://(?:www\.)?kuaishou\.com/short-video/(?P<id>[\w-]+)'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(url, video_id, headers={'Referer': 'https://www.kuaishou.com/'})

        state = self._search_json(
            r'window\.__APOLLO_STATE__\s*=', webpage, 'apollo state', video_id, default={})
        photo = None
        for value in traverse_obj(state, ('defaultClient', {dict.values})) or []:
            if isinstance(value, dict) and value.get('photoUrl'):
                photo = value
                break

        if photo:
            video_url = _unescape(photo['photoUrl'])
            title = photo.get('caption')
            thumb = photo.get('coverUrl')
            duration = float_or_none(photo.get('duration'), 1000)
            likes = int_or_none(photo.get('realLikeCount') or photo.get('likeCount'))
        else:
            m = re.search(r'"photoUrl"\s*:\s*"([^"]+)"', webpage)
            if not m:
                raise ExtractorError(
                    'Kuaishou did not return the video (it probably asked for a captcha). '
                    'Open the link in the built-in browser and download it from "Detected media".',
                    expected=True)
            video_url, title, thumb, duration, likes = _unescape(m.group(1)), None, None, None, None

        return {
            'id': video_id,
            'title': title or self._og_search_title(webpage, default=None) or f'kuaishou_{video_id}',
            'url': video_url,
            'ext': 'mp4',
            'thumbnail': thumb and _unescape(thumb),
            'duration': duration,
            'like_count': likes,
            'http_headers': {'Referer': 'https://www.kuaishou.com/'},
        }


MOBILE_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 '
             '(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1')


def parse_douyin_router_data(webpage: str, video_id: str, search_json) -> dict:
    """Video info from an iesdouyin.com share page (window._ROUTER_DATA).
    search_json is InfoExtractor._search_json (passed in so this is testable)."""
    data = search_json(r'window\._ROUTER_DATA\s*=', webpage, 'router data', video_id,
                       end_pattern=r'</script>', default={})
    item = None
    for page in (traverse_obj(data, ('loaderData', {dict.values})) or []):
        item = traverse_obj(page, ('videoInfoRes', 'item_list', 0, {dict}))
        if item:
            break
    if not item:
        raise ExtractorError('Douyin share page has no video data (the post may be deleted or private).',
                             expected=True)
    video = item.get('video') or {}
    play = traverse_obj(video, ('play_addr', 'url_list', 0)) or ''
    if not play and (uri := traverse_obj(video, ('play_addr', 'uri'))):
        play = f'https://aweme.snssdk.com/aweme/v1/play/?video_id={uri}&ratio=1080p&line=0'
    if not play:
        if item.get('images'):
            raise ExtractorError('This Douyin link is an image post (图文), not a video.', expected=True)
        raise ExtractorError('Douyin did not return a video address.', expected=True)
    return {
        'id': str(item.get('aweme_id') or video_id),
        'title': (item.get('desc') or '').strip() or f'douyin_{video_id}',
        'url': play.replace('/playwm/', '/play/'),   # the version without the watermark
        'ext': 'mp4',
        'uploader': traverse_obj(item, ('author', 'nickname')),
        'thumbnail': traverse_obj(video, ('cover', 'url_list', 0)),
        'duration': float_or_none(video.get('duration'), 1000),
        'timestamp': int_or_none(item.get('create_time')),
        'width': int_or_none(video.get('width')),
        'height': int_or_none(video.get('height')),
        'http_headers': {'User-Agent': MOBILE_UA, 'Referer': 'https://www.douyin.com/'},
    }


class DouyinShareIE(InfoExtractor):
    """Fallback for Douyin without cookies: reads the mobile share page.
    Used when yt-dlp's own Douyin extractor asks for fresh cookies, which a
    cloud server has no browser to produce."""
    IE_NAME = 'douyin:share'
    _VALID_URL = r'https?://(?:www\.)?iesdouyin\.com/share/(?:video|note|slides)/(?P<id>\d+)'

    def _real_extract(self, url):
        video_id = self._match_id(url)
        webpage = self._download_webpage(
            f'https://www.iesdouyin.com/share/video/{video_id}/', video_id,
            headers={'User-Agent': MOBILE_UA, 'Referer': 'https://www.douyin.com/'})
        return parse_douyin_router_data(webpage, video_id, self._search_json)


EXTRA_EXTRACTORS = [KuaishouIE, DouyinShareIE]
