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


EXTRA_EXTRACTORS = [KuaishouIE]
