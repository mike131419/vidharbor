"""Douyin share-page fallback: parsing, and that the URL routes to it."""
import json

import pytest

from vidharbor.extractors import DouyinShareIE, parse_douyin_router_data
from yt_dlp import YoutubeDL
from yt_dlp.utils import ExtractorError

VID = '7341234567890123456'


def _page(item):
    data = {'loaderData': {'video_(id)/page': {'videoInfoRes': {'item_list': [item] if item else []}}}}
    return ('<html><body><script>window._ROUTER_DATA = ' + json.dumps(data, ensure_ascii=False)
            + '</script></body></html>')


def _search_json():
    ie = DouyinShareIE(YoutubeDL({'quiet': True}))
    return ie._search_json


def test_parses_video_without_watermark():
    item = {'aweme_id': VID, 'desc': '周末去海边 #vlog', 'create_time': 1761200000,
            'author': {'nickname': '小明'},
            'video': {'play_addr': {'uri': 'v0300fg', 'url_list': [
                'https://aweme.snssdk.com/aweme/v1/playwm/?video_id=v0300fg&ratio=720p&line=0']},
                'cover': {'url_list': ['https://p3.douyinpic.com/cover.jpg']},
                'duration': 15200, 'width': 720, 'height': 1280}}
    info = parse_douyin_router_data(_page(item), VID, _search_json())
    assert info['id'] == VID and info['title'] == '周末去海边 #vlog' and info['uploader'] == '小明'
    assert '/play/' in info['url'] and '/playwm/' not in info['url']
    assert info['duration'] == 15.2 and info['ext'] == 'mp4'
    assert 'iPhone' in info['http_headers']['User-Agent']


def test_uri_only_and_errors():
    info = parse_douyin_router_data(_page({'video': {'play_addr': {'uri': 'abc'}}}), VID, _search_json())
    assert 'video_id=abc' in info['url'] and info['title'] == f'douyin_{VID}'
    with pytest.raises(ExtractorError, match='image post'):
        parse_douyin_router_data(_page({'images': [{}], 'video': {}}), VID, _search_json())
    with pytest.raises(ExtractorError, match='no video data'):
        parse_douyin_router_data(_page(None), VID, _search_json())


def test_share_url_routes_to_fallback():
    assert DouyinShareIE.suitable(f'https://www.iesdouyin.com/share/video/{VID}/')
    assert not DouyinShareIE.suitable(f'https://www.douyin.com/video/{VID}')
