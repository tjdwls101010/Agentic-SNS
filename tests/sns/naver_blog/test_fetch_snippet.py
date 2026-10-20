"""The naver fetch page function (web/fetch.js) run for real under node with a recording fetch: what it refuses in the
browser before any request (a host or path off the read surface, traversal however written, a wrong accept), and what it
sends (the Referer per host, form encoding, the image size cap)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from sns.naver_blog import web

FETCH = Path(web.__file__).with_name('fetch.js').read_text(encoding='utf-8')
RUNNER = '''
const sent = [];
const answer = %s;
globalThis.fetch = async (url, init) => {
  sent.push({url, headers: init.headers, credentials: init.credentials, redirect: init.redirect});
  const headers = answer.headers || {};
  return {status: 200, url, headers: {get: (k) => headers[k] === undefined ? null : headers[k]},
          text: async () => 'ok', arrayBuffer: async () => new Uint8Array(answer.size || 4).buffer};
};
const fn = (%s);
fn(%s).then(r => console.log(JSON.stringify({sent, result: r})), e => console.log(JSON.stringify({sent, threw: String(e)})));
'''
needs_node = pytest.mark.skipif(shutil.which('node') is None, reason='node is not installed')


def call(tmp_path, args, answer=None):
    script = tmp_path / 'run.js'
    script.write_text(RUNNER % (json.dumps(answer or {}), FETCH, json.dumps(args)))
    done = subprocess.run(['node', str(script)], capture_output=True, text=True, timeout=30)
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


@needs_node
@pytest.mark.parametrize('args, reason', [
    ({'host': 'evil.example', 'path': '/PostView.naver', 'accept': 'html'}, 'host'),
    ({'host': 'm.blog.naver.com', 'path': '/api/../PostWrite.naver', 'accept': 'json'}, 'path'),
    ({'host': 'postfiles.pstatic.net', 'path': '/a/%2e%2e/b.jpg', 'accept': 'image'}, 'path'),  # the one broad pattern
    ({'host': 'm.blog.naver.com', 'path': '//evil.example/x', 'accept': 'json'}, 'path'),
    ({'host': 'm.blog.naver.com', 'path': '/PostView.naver', 'accept': 'image'}, 'accept'),
], ids=['host', 'dot-dot', 'encoded-dot-dot', 'scheme-relative', 'image-accept-on-a-page-host'])
def test_what_is_off_the_read_surface_is_refused_in_the_browser_before_any_request(tmp_path, args, reason):
    out = call(tmp_path, args)
    assert out['sent'] == [] and out['result'] == {'error': 'refused', 'message': reason}, out


@needs_node
def test_a_page_read_sends_the_referer_of_its_host_and_form_encodes_the_query(tmp_path):
    out = call(tmp_path, {'host': 'm.blog.naver.com', 'path': '/PostView.naver',
                          'query': {'blogId': 'a b', 'logNo': 1}, 'accept': 'html'})
    [sent] = out['sent']
    assert sent['url'] == 'https://m.blog.naver.com/PostView.naver?blogId=a+b&logNo=1'
    assert sent['headers']['referer'] == 'https://m.blog.naver.com/' and sent['redirect'] == 'manual'
    assert out['result']['body'] == 'ok'


@needs_node
def test_a_picture_over_ten_megabytes_is_not_read_into_the_answer(tmp_path):
    out = call(tmp_path, {'host': 'postfiles.pstatic.net', 'path': '/MjAyNjEw/one.jpg', 'query': {'type': 'w800'},
                          'accept': 'image'}, answer={'headers': {'content-length': str(11 * 1024 * 1024)}})
    assert out['result']['oversize'] == 11 * 1024 * 1024 and out['result']['b64'] is None
