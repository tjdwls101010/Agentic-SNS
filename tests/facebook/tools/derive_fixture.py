#!/usr/bin/env python3
"""Derive a synthetic NDJSON skeleton from a local GraphQL capture, without network access.

Preserves JSON keys, nesting, scalar types, nulls and booleans. Replaces names,
text, URLs, ids and numbers; retains only allowlisted structural enum values.
Repeated strings map consistently. Output is a NEW file and is never a copy
of capture values. Review free text and structural coverage before committing;
the accompanying PII gate is a coarse check, not a privacy guarantee.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from check_fixtures_pii import TOKEN_SHAPED_KEYS, scan_file

ENUMS = {
    '__typename': {'User', 'Page', 'Group', 'Story', 'Comment', 'Photo', 'Video',
                   'SearchResult', 'CometSearchResultsEntityResult', 'Profile'},
    'kind': {'image', 'video', 'unknown', 'person', 'page', 'group'},
    'field_section_type': {'directory_work', 'directory_college', 'directory_bio',
                           'directory_places', 'directory_contact', 'directory_family'},
    'field_type': {'work', 'college', 'bio', 'education', 'city', 'website'},
}


def derive(objects: list[dict]) -> list[dict]:
    strings: dict[str, str] = {}
    keys: set[str] = set()

    def collect(value):
        if isinstance(value, dict):
            for key, child in value.items():
                if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
                    raise ValueError('Non-structural JSON keys require a hand-authored fixture')
                if TOKEN_SHAPED_KEYS.search(json.dumps({key: None})):
                    raise ValueError('Auth/cookie fields must not be included in fixtures')
                keys.add(key)
                collect(child)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    for obj in objects:
        collect(obj)

    def synth(value, key=''):
        if isinstance(value, dict):
            return {k: synth(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [synth(v, key) for v in value]
        if isinstance(value, str):
            if value in ENUMS.get(key, set()) or (key == 'path' and value in keys):
                return value
            if value == '':
                return ''
            if value not in strings:
                strings[value] = f'synthetic-{len(strings) + 1:04d}'
            replacement = strings[value]
            if value.startswith(('https://', 'http://')):
                return 'https://example.test/' + replacement
            return replacement
        if value is None or isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value if key in {'path', 'depth'} and 0 <= value <= 20 else int(value != 0)
        if isinstance(value, float):
            return float(value != 0)
        raise ValueError('Unsupported JSON scalar')

    return [synth(obj) for obj in objects]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path, help='Local UTF-8 GraphQL NDJSON capture; never modified')
    parser.add_argument('output', type=Path, help='New synthetic NDJSON file; existing files are refused')
    args = parser.parse_args()
    try:
        text = args.capture.read_text(encoding='utf-8')
        if text.startswith('for (;;);'):
            text = text[len('for (;;);'):]
        objects = [json.loads(line) for line in text.splitlines() if line.strip()]
        if not objects or not all(isinstance(obj, dict) for obj in objects):
            raise ValueError('Expected at least one NDJSON object')
        output = derive(objects)
        with args.output.open('x', encoding='utf-8') as stream:
            for obj in output:
                stream.write(json.dumps(obj, ensure_ascii=False, allow_nan=False) + '\n')
        if scan_file(args.output):
            args.output.unlink()
            raise ValueError('Synthetic output failed the PII gate; write a minimal skeleton by hand')
    except (OSError, ValueError) as exc:
        # Never echo source values, file contents or parser snippets.
        parser.exit(2, f'Fixture derivation failed ({type(exc).__name__}); input must be valid NDJSON with structural keys, and output must be a new writable path.\n')
    print(f'Derived {len(output)} synthetic object(s); review the fixture before committing.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
