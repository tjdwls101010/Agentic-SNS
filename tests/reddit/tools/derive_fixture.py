#!/usr/bin/env python3
"""Derive synthetic Reddit NDJSON from local JSON/NDJSON only; never fetch URLs.

Standalone adaptation of the Facebook fixture tool. Retains envelopes, enums,
nulls, booleans and empty replies; replaces identifying strings and numbers.
Auth fields are removed even from ordinary logged-in captures with modhash.
Output must be a new file. Review free text and coverage manually: the PII
scanner is a coarse structural gate, not a privacy guarantee.
"""
import argparse
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

from check_fixtures_pii import AUTH_KEYS, scan_file

ENUMS = {
    'kind': {'Listing', 't1', 't2', 't3', 't5', 'more', 'all', 'link', 'comment'},
    'subreddit_type': {'public', 'private', 'restricted', 'gold_restricted', 'archived'},
    'post_hint': {'self', 'link', 'image', 'hosted:video', 'rich:video'},
    'suggested_sort': {'best', 'confidence', 'top', 'new', 'controversial', 'old', 'qa'},
}
FULLNAME = re.compile(r'(t[1235])_([a-z0-9]+)\Z')


def derive(objects):
    """Anonymize one batch consistently, including references across NDJSON lines."""
    ids, strings = {}, {}

    def identity(value):
        match = FULLNAME.fullmatch(value)
        bare = match[2] if match else value
        if bare not in ids:
            # The alphabetic prefix plus hexadecimal counter is valid base36.
            ids[bare] = f'syn{len(ids) + 1:x}'
        return match[1] + '_' + ids[bare] if match else ids[bare]

    def text(value):
        if value not in strings:
            strings[value] = f'synthetic{len(strings) + 1}'
        return strings[value]

    def link(value):
        parts = urlsplit(value)
        match = re.fullmatch(r'(?:/r/([^/]+))?/comments/([a-z0-9]+)(?:/[^/]+(?:/([a-z0-9]+))?)?/?', parts.path)
        if match:
            community, post, comment = match.groups()
            path = (f'/r/{text(community)}' if community else '') + f'/comments/{identity(post)}/_/'
            if comment:
                path += identity(comment) + '/'
            return ('https://www.reddit.com' if parts.scheme else '') + path
        return 'https://example.test/' + text(value)

    def synth(value, key='', kind=None):
        if isinstance(value, dict):
            result = {}
            for field, child in value.items():
                if AUTH_KEYS.fullmatch(field):
                    continue
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', field):
                    raise ValueError('Non-structural keys require a hand-authored fixture')
                result[field] = synth(child, field, value.get('kind', kind))
            return result
        if isinstance(value, list):
            return [synth(child, key, kind) for child in value]
        if isinstance(value, str):
            if value == '' or value in ENUMS.get(key, set()):
                return value
            if key in {'id', 'fullname', 'parent_id', 'link_id', 'subreddit_id', 'author_fullname',
                       'crosspost_parent', 'after', 'before'} or (key == 'children' and kind == 'more'):
                return identity(value)
            if key == 'name' and kind in {'t1', 't3', 't5', 'more'}:
                return identity(value)
            if key in {'permalink', 'link_permalink', 'url'} or value.startswith(('https://', 'http://')):
                return link(value)
            return text(value)
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value if key == 'depth' and 0 <= value <= 20 else int(value != 0)
        if isinstance(value, float):
            return float(value != 0)
        raise ValueError('Unsupported JSON scalar')

    return [synth(obj) for obj in objects]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path, help='Local UTF-8 Reddit JSON or NDJSON; never modified')
    parser.add_argument('output', type=Path, help='New synthetic NDJSON file; existing files are refused')
    args = parser.parse_args()
    try:
        source = args.capture.read_text(encoding='utf-8')
        try:
            objects = [json.loads(source)]
        except ValueError:
            objects = [json.loads(line) for line in source.splitlines() if line.strip()]
        if not objects or not all(isinstance(obj, (dict, list)) for obj in objects):
            raise ValueError('Expected Reddit objects or post-pair arrays')
        output = derive(objects)
        encoded = ''.join(json.dumps(obj, ensure_ascii=False, allow_nan=False) + '\n' for obj in output)
        with args.output.open('x', encoding='utf-8') as stream:
            stream.write(encoded)
        if scan_file(args.output):
            args.output.unlink()
            raise ValueError('Synthetic output failed the PII gate')
    except (OSError, ValueError, TypeError, RecursionError):
        # Never echo source values, paths or parser snippets into diagnostics.
        parser.exit(2, 'Fixture derivation failed; use valid local JSON/NDJSON and a new writable output path.\n')
    print(f'Derived {len(output)} synthetic record(s); manual free-text review is still required.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
