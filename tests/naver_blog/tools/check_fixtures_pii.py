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
# Invented identifiers all start with this prefix, so a real one stands out. Only the fields
# that name a post, a comment or a blog are checked: a timestamp is a long number too.
ALLOWED_ID_PREFIX = '9990'
NUMBER_FIELDS = ('logNo', 'commentNo', 'parentCommentNo', 'blogNo', 'groupId')
FORBIDDEN = [
    (re.compile(r'NID_AUT|NID_SES|NID_JKL|baUserKey', re.I), 'a Naver session cookie name'),
    (re.compile(r'\bhttps?://[^\s"\']*pstatic\.net[^\s"\']*[?&]type='), 'a signed profile or photo URL'),
    (re.compile(r'\b\d{2,3}-\d{3,4}-\d{4}\b'), 'a phone number'),
    (re.compile(r'\b[\w.+-]+@[\w-]+\.[\w.]+\b'), 'an email address'),
]
ID_FIELDS = ('blogId', 'profileUserId', 'blogOwner')


def identifiers(value, found):
    """Collect the values of the fields that name a person, a blog, a post or a comment."""
    if isinstance(value, dict):
        for key, child in value.items():
            if key in ID_FIELDS and isinstance(child, str) and child:
                found.setdefault('blog', set()).add(child)
            if key in NUMBER_FIELDS and str(child).isdigit():
                found.setdefault('number', set()).add(str(child))
            identifiers(child, found)
    elif isinstance(value, list):
        for child in value:
            identifiers(child, found)
    return found


def check(path):
    text = path.read_text(encoding='utf-8')
    problems = []
    for pattern, what in FORBIDDEN:
        for match in pattern.findall(text):
            problems.append(f'{what}: {match if isinstance(match, str) else match[0]}')
    if path.suffix == '.ndjson':
        for line in text.splitlines():
            if not line.strip():
                continue
            found = identifiers(json.loads(line), {})
            problems += [f'a blog id outside the allowlist: {name}'
                         for name in found.get('blog', set()) - ALLOWED_IDS if not name.isdigit()]
            problems += [f'an identifier that is not invented: {number}'
                         for number in found.get('number', set())
                         if not number.startswith(ALLOWED_ID_PREFIX)]
    else:
        for match in re.findall(r'var\s+(?:blogId|blogOwner|userId)\s*=\s*"([^"]+)"', text):
            if match not in ALLOWED_IDS:
                problems.append(f'a blog id outside the allowlist: {match}')
    return problems


def main():
    # rglob, not glob: whole fixture sets live in subdirectories and they ship too.
    files = sorted(ROOT.rglob('*.ndjson')) + sorted(ROOT.rglob('*.html'))
    failures = 0
    for path in files:
        problems = check(path)
        for problem in problems:
            print(f'{path.relative_to(ROOT)}: {problem}')
        failures += len(problems)
    print(f'{len(files)} fixture file(s) checked, {failures} problem(s).')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
