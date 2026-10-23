"""Scrubbing (sns.redact): every platform's recorded scrub cases hold for the one union of their secrets."""
import json
from pathlib import Path

import pytest

from sns.redact import scrub

FIXTURES = Path(__file__).resolve().parents[1]


def cases():
    found = []
    for name in ('x/fixtures/scrub.json', 'naver_blog/fixtures/scrub.json'):
        found += [(name, case) for case in json.loads((FIXTURES / name).read_text())['cases']]
    found += [('reddit/fixtures/stores.json', case)
              for case in json.loads((FIXTURES / 'reddit/fixtures/stores.json').read_text())['scrub']['cases']]
    return found


@pytest.mark.parametrize('source,case', cases())
def test_recorded_scrub_cases(source, case):
    output = scrub(case['input'])
    if 'expected' in case or 'output' in case:
        assert output == case.get('expected', case.get('output')), source
    text = json.dumps(output, ensure_ascii=False) if not isinstance(output, str) else output
    for secret in case.get('expected_absent', []) + case.get('absent', []) + case.get('output_excludes', []):
        assert secret not in text, (source, secret)


def test_meta_and_x_keys_and_signed_hosts():
    assert scrub({'fb_dtsg': 'a', 'lsd': 'b', 'c_user': '1', 'ct0': 'c'}) == \
        {'fb_dtsg': '[REDACTED]', 'lsd': '[REDACTED]', 'c_user': '[REDACTED]', 'ct0': '[REDACTED]'}
    assert scrub('https://scontent-x.cdninstagram.com/v/a.jpg?oh=SIG&oe=1') == 'https://scontent-x.cdninstagram.com/v/a.jpg'
    assert scrub('https://pbs.twimg.com/media/a.jpg?name=large') == 'https://pbs.twimg.com/media/a.jpg'
    assert scrub('https://i.redd.it/a.png?s=SIG') == 'https://i.redd.it/a.png'
    assert scrub('https://www.threads.com/x?lsd=SECRET') == 'https://www.threads.com/x?lsd=[REDACTED]'
