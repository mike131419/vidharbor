"""Which way of visiting RedNote gets the note data? (run in CI, results as annotations)

A  yt-dlp as-is (no cookies)                 - what the app does today
B  page fetched with a phone browser identity - parse both desktop and mobile page layouts
C  guest cookies from a real browser visit    - what the app's built-in browser would collect
"""
import json
import re
import sys
import tempfile
import urllib.request

import yt_dlp
from yt_dlp.utils import js_to_json

NOTES = [
    'https://www.xiaohongshu.com/discovery/item/674051740000000007027a15'
    '?xsec_token=CBgeL8Dxd1ZWBhwqRd568gAZ_iwG-9JIf9tnApNmteU2E=',
    'https://www.xiaohongshu.com/explore/6411cf99000000001300b6d9',
]
MOBILE_UA = ('Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 '
             '(KHTML, like Gecko) Version/18.0 Mobile/15E148 Safari/604.1')
DESKTOP_UA = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36')


def note(msg, title, level='notice'):
    print(f'::{level} title={title}::{" ".join(str(msg).split())[:900]}', flush=True)


def ytdlp(url, cookiefile=None):
    opts = {'quiet': True, 'no_warnings': True, 'simulate': True}
    if cookiefile:
        opts['cookiefile'] = cookiefile
    try:
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(url, download=False)
        fmts = info.get('formats') or []
        return f'OK title={info.get("title")!r} formats={len(fmts)}'
    except Exception as e:  # noqa: BLE001
        return f'FAIL {str(e)[:200]}'


def state_summary(html, note_id):
    m = re.search(r'window\.__INITIAL_STATE__\s*=\s*(\{.*?\})\s*</script>', html, re.S)
    if not m:
        title = re.search(r'<title>([^<]*)', html)
        return f'no __INITIAL_STATE__ (page title {title.group(1)[:60] if title else "?"!r}, {len(html)} bytes)'
    try:
        st = json.loads(js_to_json(m.group(1)))
    except Exception as e:  # noqa: BLE001
        return f'state not parseable: {e}'
    pc = (((st.get('note') or {}).get('noteDetailMap') or {}).get(note_id) or {}).get('note')
    mob = ((((st.get('noteData') or {}).get('data') or {}).get('noteData')) or None)
    found = pc or mob
    where = 'desktop layout' if pc else 'mobile layout' if mob else None
    if not found:
        return f'state present but no note data; top keys {sorted(st)[:12]}'
    v = found.get('video') or {}
    streams = sum(len(x or []) for x in ((v.get('media') or {}).get('stream') or {}).values()) if v else 0
    return (f'NOTE DATA ({where}) type={found.get("type")} title={found.get("title")!r} '
            f'video_streams={streams} origin_key={bool((v.get("consumer") or {}).get("originVideoKey"))}')


def fetch(url, ua, cookie=''):
    req = urllib.request.Request(url, headers={'User-Agent': ua, 'Referer': 'https://www.xiaohongshu.com/',
                                               **({'Cookie': cookie} if cookie else {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.geturl(), r.read().decode('utf-8', 'replace')


def browser_cookies():
    from playwright.sync_api import sync_playwright
    with sync_playwright() as p:
        b = p.chromium.launch()
        ctx = b.new_context(user_agent=MOBILE_UA, viewport={'width': 390, 'height': 844}, is_mobile=True)
        page = ctx.new_page()
        page.goto('https://www.xiaohongshu.com/explore', wait_until='domcontentloaded', timeout=60000)
        page.wait_for_timeout(10000)
        cookies = ctx.cookies()
        b.close()
    return cookies


def main():
    for url in NOTES:
        nid = re.search(r'([0-9a-f]{24})', url).group(1)
        note(ytdlp(url), f'A yt-dlp plain {nid[:6]}')
        for label, ua in (('desktop', DESKTOP_UA), ('phone', MOBILE_UA)):
            try:
                final, html = fetch(url, ua)
                note(f'{state_summary(html, nid)} | landed on {final[:90]}', f'B page as {label} {nid[:6]}')
            except Exception as e:  # noqa: BLE001
                note(f'fetch failed: {e}', f'B page as {label} {nid[:6]}', 'warning')

    try:
        cookies = browser_cookies()
        names = sorted(c['name'] for c in cookies if 'xiaohongshu' in c['domain'])
        note(f'{len(names)} cookies: {names}', 'C guest cookies')
        jar = tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False)
        jar.write('# Netscape HTTP Cookie File\n')
        for c in cookies:
            dom = c['domain']
            jar.write('\t'.join([dom, 'TRUE' if dom.startswith('.') else 'FALSE', c['path'],
                                 'TRUE' if c['secure'] else 'FALSE', str(int(c.get('expires') or 2e9) if c.get('expires', -1) > 0 else 2000000000),
                                 c['name'], c['value']]) + '\n')
        jar.close()
        header = '; '.join(f'{c["name"]}={c["value"]}' for c in cookies if 'xiaohongshu' in c['domain'])
        for url in NOTES:
            nid = re.search(r'([0-9a-f]{24})', url).group(1)
            note(ytdlp(url, jar.name), f'C yt-dlp + guest cookies {nid[:6]}')
            final, html = fetch(url, MOBILE_UA, header)
            note(state_summary(html, nid), f'C page as phone + cookies {nid[:6]}')
    except Exception as e:  # noqa: BLE001
        note(f'browser step failed: {e}', 'C guest cookies', 'warning')
    return 0


if __name__ == '__main__':
    sys.exit(main())
