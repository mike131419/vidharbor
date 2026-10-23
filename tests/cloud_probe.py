"""Try real links from a cloud machine (run inside the Docker image in CI).

Prints a GitHub Actions annotation per site, so results show up on the
workflow run. A failure here is information, not a broken build: sites
change and some block data-centre IPs.
"""
import os
import shutil
import sys
import tempfile
import time

from vidharbor import engine

engine.add_bins_to_path()
engine.install_engine_finder()

from vidharbor.core import Events, Job, Options, Runner  # noqa: E402

LINKS = [
    ('Douyin', '7.43 复制打开抖音，看看 https://www.douyin.com/video/6961737553342991651 07/12'),
    ('RedNote', 'https://www.xiaohongshu.com/discovery/item/674051740000000007027a15'
                '?xsec_token=CBgeL8Dxd1ZWBhwqRd568gAZ_iwG-9JIf9tnApNmteU2E='),
    ('Bilibili', 'https://www.bilibili.com/video/BV13x41117TL'),
    ('Weibo', 'https://m.weibo.cn/status/4189191225395228'),
    ('YouTube', 'https://www.youtube.com/watch?v=BaW_jenozKc'),
    ('YouTube MP3', 'https://www.youtube.com/watch?v=BaW_jenozKc'),
    ('TikTok', 'https://www.tiktok.com/@leenabhushan/video/6748451240264420610'),
    ('Instagram', 'https://www.instagram.com/reel/Chunk8-jurw/'),
    ('Facebook', 'https://www.facebook.com/reel/1195289147628387'),
]


class Collect(Events):
    def __init__(self):
        self.result = None
        self.lines = []

    def done(self, job, result, message, filepath):
        self.result = (result, message, filepath)

    def log(self, text):
        self.lines.append(text)


def one_line(text: str) -> str:
    return ' '.join(text.split())[:300].replace('%', '%25')


def main() -> int:
    from vidharbor.linkparse import extract_urls
    ok = 0
    for name, text in LINKS:
        out = tempfile.mkdtemp()
        url = extract_urls(text)[0]
        opts = Options(outdir=out, mode='mp3' if 'MP3' in name else 'video', quality='480',
                       cookie_mode='none', subfolders=False, embed_meta=False)
        ev = Collect()
        start = time.time()
        Runner(Job(url=url), opts, ev, phone=True).run()
        took = time.time() - start
        result, message, path = ev.result or ('error', 'no result', '')
        if result == 'ok' and path and os.path.isfile(path):
            ok += 1
            size = os.path.getsize(path) / 1e6
            print(f'::notice title={name}::OK {size:.1f} MB {os.path.splitext(path)[1]} in {took:.0f}s')
        else:
            print(f'::warning title={name}::FAILED in {took:.0f}s: {one_line(message)}')
            for line in ev.lines[-4:]:
                print('   ', line[:300])
        shutil.rmtree(out, ignore_errors=True)
        sys.stdout.flush()
    print(f'::notice title=Summary::{ok} of {len(LINKS)} sites downloaded from this cloud machine')
    return 0


if __name__ == '__main__':
    sys.exit(main())
