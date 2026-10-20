from vidharbor.linkparse import detect_platform, extract_urls, is_short_link, normalize, why_unsupported


def test_douyin_share_text():
    text = '7.43 复制打开抖音，看看【某某的作品】今天天气不错 # 日常 https://v.douyin.com/iRNBho6u/ 07/12 F@u.Sy KjC:/'
    assert extract_urls(text) == ['https://v.douyin.com/iRNBho6u/']


def test_rednote_share_text_fullwidth_comma():
    text = '标题 http://xhslink.com/a/AbCd1234，复制本条信息，打开【小红书】App查看精彩内容！'
    assert extract_urls(text) == ['http://xhslink.com/a/AbCd1234']


def test_multiple_and_dedupe():
    text = 'https://youtu.be/abc https://youtu.be/abc\nhttps://www.bilibili.com/video/BV1xx411c7mD).'
    assert extract_urls(text) == ['https://youtu.be/abc', 'https://www.bilibili.com/video/BV1xx411c7mD']


def test_platforms():
    assert detect_platform('https://v.douyin.com/x/').key == 'douyin'
    assert detect_platform('http://xhslink.com/a/x').key == 'xhs'
    assert detect_platform('https://v.kuaishou.com/x').key == 'kuaishou'
    assert detect_platform('https://mp.weixin.qq.com/s/abc').key == 'wx_article'
    assert detect_platform('https://channels.weixin.qq.com/x').key == 'wx_channels'
    assert detect_platform('https://www.facebook.com/reel/1').key == 'facebook'
    assert detect_platform('https://example.org/v').key == 'other'


def test_short_links():
    assert is_short_link('https://v.douyin.com/iRNBho6u/')
    assert is_short_link('http://xhslink.com/a/x')
    assert is_short_link('https://b23.tv/abc')
    assert not is_short_link('https://www.douyin.com/video/123')


def test_normalize_douyin():
    assert normalize('https://www.iesdouyin.com/share/video/7341234567890123456/?region=CN&mid=1') == \
        'https://www.douyin.com/video/7341234567890123456'
    assert normalize('https://www.douyin.com/jingxuan?modal_id=7341234567890123456') == \
        'https://www.douyin.com/video/7341234567890123456'
    assert normalize('https://www.douyin.com/user/MS4w?modal_id=7341234567890123456') == \
        'https://www.douyin.com/video/7341234567890123456'
    assert why_unsupported(normalize('https://www.iesdouyin.com/share/note/7341234567890123456/'))


def test_normalize_rednote_keeps_token():
    u = 'https://www.xiaohongshu.com/discovery/item/674051740000000007027a15?xsec_token=ABC=&xsec_source=app_share'
    assert normalize(u) == ('https://www.xiaohongshu.com/explore/674051740000000007027a15'
                            '?xsec_token=ABC=&xsec_source=app_share')
    u2 = 'https://www.xiaohongshu.com/user/profile/5f00/674051740000000007027a15?xsec_token=T'
    assert normalize(u2) == 'https://www.xiaohongshu.com/explore/674051740000000007027a15?xsec_token=T'


def test_normalize_kuaishou_and_others():
    assert normalize('https://v.m.chenzhongtech.com/fw/photo/3xabc123?fid=1') == \
        'https://www.kuaishou.com/short-video/3xabc123'
    assert normalize('https://m.bilibili.com/video/BV1xx411c7mD?p=1') == \
        'https://www.bilibili.com/video/BV1xx411c7mD'
    assert normalize('https://www.youtube.com/watch?v=x') == 'https://www.youtube.com/watch?v=x'


def test_wechat_channels_rejected():
    assert 'WeChat' in why_unsupported('https://channels.weixin.qq.com/web/pages/feed?oid=1')


def test_yt_dlp_accepts_normalized():
    """The rewritten URLs must match yt-dlp's own extractors."""
    from yt_dlp.extractor import gen_extractor_classes
    from vidharbor.extractors import KuaishouIE
    def ie_for(url):
        for ie in [KuaishouIE, *gen_extractor_classes()]:
            if ie.suitable(url) and ie.ie_key() != 'Generic':
                return ie.ie_key()
    assert ie_for('https://www.douyin.com/video/7341234567890123456') == 'Douyin'
    assert ie_for('https://www.xiaohongshu.com/explore/674051740000000007027a15?xsec_token=T') == 'XiaoHongShu'
    assert ie_for('https://www.kuaishou.com/short-video/3xabc123') == 'Kuaishou'
    assert ie_for('https://www.bilibili.com/video/BV1xx411c7mD') == 'BiliBili'
    assert ie_for('https://m.weibo.cn/status/4789') in ('Weibo', 'WeiboMobile')
