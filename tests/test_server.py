"""Phone server tests: real downloads from a local web server, through the API."""
import functools
import http.client
import http.server
import json
import os
import shutil
import subprocess
import threading
import time

import pytest

pytestmark = pytest.mark.skipif(not shutil.which('ffmpeg'), reason='needs ffmpeg')


@pytest.fixture(scope='module')
def media_site(tmp_path_factory):
    root = tmp_path_factory.mktemp('site')
    subprocess.run(['ffmpeg', '-loglevel', 'error', '-y', '-f', 'lavfi', '-i', 'testsrc=size=320x240:rate=25',
                    '-f', 'lavfi', '-i', 'sine=frequency=440', '-t', '2', '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-c:a', 'aac', str(root / 'clip.mp4')], check=True)
    (root / 'page.html').write_text('<html><head><title>测试 Phone video</title></head>'
                                    '<body><video src="/clip.mp4"></video></body></html>', 'utf-8')
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(root))
    handler.log_message = lambda *a: None
    srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f'http://127.0.0.1:{srv.server_address[1]}'
    srv.shutdown()


@pytest.fixture()
def phone(tmp_path, monkeypatch):
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'appdata'))
    from vidharbor.core import Options
    from vidharbor.server import PhoneServer
    srv = PhoneServer(port=0, access_code='ABCD-EFGH-JKMN', host='127.0.0.1', keep_hours=1,
                      options=lambda: Options(outdir='', cookie_mode='none'), log=lambda *_: None)
    srv.start()
    yield srv
    srv.stop()


class Client:
    def __init__(self, port):
        self.port, self.cookie = port, ''

    def req(self, method, path, body=None, headers=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=30)
        h = {'Cookie': self.cookie} if self.cookie else {}
        h.update(headers or {})
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            h['Content-Type'] = 'application/json'
        c.request(method, path, body=data, headers=h)
        r = c.getresponse()
        raw = r.read()
        if sc := r.getheader('Set-Cookie'):
            self.cookie = sc.split(';', 1)[0]
        c.close()
        try:
            return r.status, json.loads(raw), r
        except ValueError:
            return r.status, raw, r

    def login(self, code='abcd efgh jkmn'):
        return self.req('POST', '/api/login', {'code': code})

    def wait(self, ids, timeout=60):
        end = time.time() + timeout
        while time.time() < end:
            _, data, _ = self.req('GET', '/api/jobs')
            jobs = {j['id']: j for j in data['jobs'] if j['id'] in ids}
            if len(jobs) == len(ids) and all(j['state'] not in ('queued', 'running') for j in jobs.values()):
                return jobs
            time.sleep(0.3)
        raise AssertionError('timed out')


def test_static_and_auth(phone):
    c = Client(phone.port)
    s, body, r = c.req('GET', '/')
    assert s == 200 and b'VidHarbor' in body and r.getheader('Content-Security-Policy')
    assert c.req('GET', '/manifest.webmanifest')[0] == 200
    assert c.req('GET', '/../server.py')[0] == 404
    assert c.req('GET', '/api/jobs')[0] == 401
    assert c.login('WRONG-CODE-0000')[0] == 403
    s, _, r = c.login()          # spaces/lower case are accepted
    assert s == 200 and 'HttpOnly' in r.getheader('Set-Cookie')
    assert c.req('GET', '/api/me')[0] == 200
    # cross-site posts are refused
    assert c.req('POST', '/api/jobs', {'text': 'x'}, {'Origin': 'https://evil.example'})[0] == 403


def test_keep_alive_after_rejected_post(phone):
    """A refused POST must not leave its body on the connection for the next request."""
    c = http.client.HTTPConnection('127.0.0.1', phone.port, timeout=10)
    for _ in range(3):
        c.request('POST', '/api/jobs', body=b'{"text": "https://example.com/v"}',
                  headers={'Content-Type': 'application/json'})
        r = c.getresponse()
        r.read()
        assert r.status == 401
    c.request('GET', '/api/ping')
    r = c.getresponse()
    assert r.status == 200 and json.loads(r.read())['ok'] is True
    c.close()


def test_login_rate_limit(phone):
    c = Client(phone.port)
    codes = [c.login('NOPE')[0] for _ in range(9)]
    assert codes[:8] == [403] * 8 and codes[8] == 429
    assert c.login()[0] == 429      # even the right code waits once blocked


def test_download_video_and_mp3_with_range(phone, media_site):
    a = Client(phone.port)
    a.login()
    s, data, _ = a.req('POST', '/api/jobs', {'text': f'看看 {media_site}/page.html ，复制本条信息', 'mode': 'video'})
    assert s == 200 and len(data['jobs']) == 1
    s, data2, _ = a.req('POST', '/api/jobs', {'text': f'{media_site}/page.html', 'mode': 'mp3'})
    ids = [data['jobs'][0]['id'], data2['jobs'][0]['id']]
    jobs = a.wait(ids)
    v, m = jobs[ids[0]], jobs[ids[1]]
    assert v['state'] == 'done' and v['file']['name'].endswith('.mp4') and v['file']['type'] == 'video/mp4'
    assert m['state'] == 'done' and m['file']['name'].endswith('.mp3') and m['file']['type'] == 'audio/mpeg'
    assert v['title'].startswith('测试')

    s, body, r = a.req('GET', f'/api/files/{ids[0]}')
    assert s == 200 and len(body) == v['file']['size'] and body[4:8] == b'ftyp'
    assert "filename*=UTF-8''" in r.getheader('Content-Disposition')
    s, part, r = a.req('GET', f'/api/files/{ids[0]}', headers={'Range': 'bytes=0-99'})
    assert s == 206 and len(part) == 100 and r.getheader('Content-Range').endswith(f'/{v["file"]["size"]}')
    s, _, _ = a.req('GET', f'/api/files/{ids[0]}', headers={'Range': 'bytes=999999999-'})
    assert s == 416

    # another phone sees nothing and can't fetch the file
    b = Client(phone.port)
    b.login()
    assert b.req('GET', '/api/jobs')[1]['jobs'] == []
    assert b.req('GET', f'/api/files/{ids[0]}')[0] == 404
    assert b.req('DELETE', f'/api/jobs/{ids[0]}')[1]['ok'] is False

    # removing deletes the file
    path = phone.jobs[ids[1]].job.filepath
    assert os.path.isfile(path)
    assert a.req('DELETE', f'/api/jobs/{ids[1]}')[1]['ok'] is True
    assert not os.path.exists(path)


def test_errors_retry_and_limits(phone, media_site):
    c = Client(phone.port)
    c.login()
    s, data, _ = c.req('POST', '/api/jobs', {'text': 'no links here'})
    assert s == 400 and 'No link' in data['error']
    s, data, _ = c.req('POST', '/api/jobs', {'text': 'https://channels.weixin.qq.com/web/pages/feed?oid=1'})
    jid = data['jobs'][0]['id']
    job = c.wait([jid])[jid]
    assert job['state'] == 'error' and 'WeChat' in job['error']
    s, data, _ = c.req('POST', f'/api/jobs/{jid}/retry')
    assert s == 200 and data['job']['id'] != jid
    many = ' '.join(f'{media_site}/clip.mp4?n={i}' for i in range(6))
    s, data, _ = c.req('POST', '/api/jobs', {'text': many})
    assert s == 400 and 'up to' in data['error']


def test_cleanup_and_code_change(phone, media_site, tmp_path):
    c = Client(phone.port)
    c.login()
    _, data, _ = c.req('POST', '/api/jobs', {'text': f'{media_site}/clip.mp4'})
    jid = data['jobs'][0]['id']
    c.wait([jid])
    path = phone.jobs[jid].job.filepath
    phone.jobs[jid].finished -= 2 * 3600   # pretend it finished 2 hours ago
    phone.cleanup()
    assert jid not in phone.jobs and not os.path.exists(path)

    from vidharbor.server import TokenStore
    token = c.cookie.split('=', 1)[1]
    assert TokenStore('ABCD-EFGH-JKMN').check(token)        # restart, same code: still signed in
    assert not TokenStore('NEW1-CODE-2345').check(token)    # new code signs everyone out
    store = TokenStore('ABCD-EFGH-JKMN')
    assert not store.check(token[:-1] + ('0' if token[-1] != '0' else '1'))   # tampered
    assert not store.check('v1.0.abc.def') and not store.check('garbage')
    store.revoke(token)
    assert not store.check(token)


def test_signed_out_after_logout(phone):
    c = Client(phone.port)
    c.login()
    assert c.req('GET', '/api/me')[0] == 200
    old = c.cookie
    c.req('POST', '/api/logout')
    c.cookie = old                                  # reusing the old token after sign-out fails
    assert c.req('GET', '/api/me')[0] == 401
