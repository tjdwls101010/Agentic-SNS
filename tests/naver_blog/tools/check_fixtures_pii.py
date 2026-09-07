#!/usr/bin/env python3
"""Naver Blog is a real-name medium: fixtures must be synthetic, and this gate says so.

Real ids, post numbers and profile URLs are what turn a fixture into someone's record, so
the gate refuses anything outside a small allowlist of invented values rather than trying
to recognize a real name. Exit 1 lists every offending file and value.
"""
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'fixtures'

# Everything a fixture may name. Extend deliberately, one invented value at a time.
ALLOWED_IDS = {'testviewer', 'testblog', 'otherblog', 'legacyblog', 'buddyone', 'buddytwo',
               'commenterone', 'commentertwo', 'naverblog', 'emptyblog', 'domainblog'}
# Invented post numbers all start with this prefix so a real 12-digit logNo stands out.
LOG_NO = re.compile(r'\b(\d{7,20})\b')
ALLOWED_LOG_PREFIX = '9990'
FORBIDDEN = [
    (re.compile(r'NID_AUT|NID_SES|NID_JKL|baUserKey', re.I), 'a Naver session cookie name'),
    (re.compile(r'\bhttps?://[^\s"\']*pstatic\.net[^\s"\']*[?&]type='), 'a signed profile or photo URL'),
    (re.compile(r'\b\d{2,3}-\d{3,4}-\d{4}\b'), 'a phone number'),
    (re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b'), 'an email address'),
]
ID_FIELDS = ('blogId', 'profileUserId', 'blogOwner', 'nickName', 'nickname')


def strings(value):
    if isinstance(value, dict):
        for key, child in value.items():
            yield str(key)
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)
    elif isinstance(value, str):
        yield value


def blog_ids(value, found):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ID_FIELDS and isinstance(child, str) and child:
                found.add(child)
            blog_ids(child, found)
    elif isinstance(value, list):
        for child in value:
            blog_ids(child, found)
    return found


def check(path):
    text = path.read_text(encoding='utf-8')
    problems = []
    for pattern, what in FORBIDDEN:
        for match in pattern.findall(text):
            problems.append(f'{what}: {match if isinstance(match, str) else match[0]}')
    for number in set(LOG_NO.findall(text)):
        if len(number) >= 12 and not number.startswith(ALLOWED_LOG_PREFIX):
            problems.append(f'a post number that is not invented: {number}')
    if path.suffix == '.ndjson':
        for line in text.splitlines():
            if line.strip():
                found = blog_ids(json.loads(line), set())
                problems += [f'a blog id outside the allowlist: {name}'
                             for name in found - ALLOWED_IDS if not name.isdigit()]
    else:
        for match in re.findall(r'var\s+(?:blogId|blogOwner|userId)\s*=\s*"([^"]+)"', text):
            if match not in ALLOWED_IDS:
                problems.append(f'a blog id outside the allowlist: {match}')
    return problems


def main():
    files = sorted(ROOT.glob('*.ndjson')) + sorted(ROOT.glob('*.html'))
    failures = 0
    for path in files:
        problems = check(path)
        for problem in problems:
            print(f'{path.name}: {problem}')
        failures += len(problems)
    print(f'{len(files)} fixture file(s) checked, {failures} problem(s).')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
