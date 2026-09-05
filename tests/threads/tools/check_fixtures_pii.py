#!/usr/bin/env python3
"""Check synthetic fixture values, including JSON/HTML wrapped in response bodies.

This is an allowlist gate for fixtures, not a general PII detector. Review the
synthetic structure and free text before committing it; never print rejected values.
"""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

IDENTITIES = {'pk', 'id', 'userID', 'postID', 'reply_to_id', 'root_post_id', 'actorID', 'NON_FACEBOOK_USER_ID'}
SECRETS = {'csrf', 'csrf_token', 'csrftoken', 'sessionid', 'cookie', 'authorization', 'fb_dtsg', 'lsd', 'token'}
TEXT = {'text', 'username', 'full_name', 'biography', 'title', 'accessibility_caption'}


def problems(value, key=''):
    found = []
    if isinstance(value, dict):
        for name, child in value.items():
            found += problems(child, name)
    elif isinstance(value, list):
        for child in value:
            found += problems(child, key)
    elif value is not None:
        string = str(value)
        synthetic = string.lower().startswith(('synthetic', 'fixture', 'fix_'))
        if key in SECRETS and not synthetic:
            found.append('non-synthetic credential field')
        if key in IDENTITIES and not re.fullmatch(r'\d{1,6}', string):
            found.append('non-synthetic identity')
        if key in TEXT and string and not synthetic:
            found.append('non-synthetic text or name')
        if isinstance(value, str):
            if key == 'body':
                try:
                    return found + problems(json.loads(value))
                except ValueError:
                    scripts = re.findall(r'<script\b[^>]*type=["\']application/json["\'][^>]*>(.*?)</script>', value, re.S | re.I)
                    if not scripts:
                        return found + ([] if synthetic else ['unreviewed envelope body'])
                    for script in scripts:
                        try:
                            found += problems(json.loads(script))
                        except ValueError:
                            found.append('invalid JSON script')
            if value.startswith(('http://', 'https://')):
                parsed = urlsplit(value)
                allowed = (parsed.hostname or '').endswith(('.invalid', '.test')) or parsed.hostname == 'example.com'
                if parsed.hostname == 'www.threads.com':
                    allowed = parsed.path in ('/', '/graphql/query') or parsed.path.startswith('/@fixture')
                if not allowed or parsed.query:
                    found.append('non-synthetic URL or signature')
            if re.search(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}', value) and '@example.' not in value:
                found.append('email-shaped value')
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', type=Path, nargs='*', help='JSON/NDJSON files or directories; default is the sibling fixtures directory')
    args = parser.parse_args()
    files = []
    for path in args.paths or [Path(__file__).resolve().parent.parent / 'fixtures']:
        if not path.exists():
            parser.error('Fixture path does not exist.')
        files.extend([p for p in path.rglob('*') if p.suffix in ('.json', '.ndjson')] if path.is_dir() else [path])
    failures = []
    for path in files:
        try:
            values = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.suffix == '.ndjson' else [json.loads(path.read_text())]
            for value in values:
                failures += problems(value)
        except (OSError, ValueError):
            failures.append('unreadable fixture')
    if failures:
        print('Fixture scan FAILED: ' + ', '.join(sorted(set(failures))))
        return 1
    print(f'Fixture scan OK: {len(files)} synthetic file(s); manual structure review still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
