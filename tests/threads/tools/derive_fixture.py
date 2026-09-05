#!/usr/bin/env python3
"""Derive a synthetic GraphQL NDJSON skeleton, preserving identity relationships.

Input is never modified and output must be new. Scalar values are replaced;
review enum, cursor and date semantics before using the skeleton in a test.
"""
import argparse
import json
from pathlib import Path
import re

from check_fixtures_pii import IDENTITIES, SECRETS, TEXT, problems


def derive(values):
    identities, strings = {}, {}
    def identity(value):
        return identities.setdefault(str(value), str(1001 + len(identities)))
    def walk(value, key=''):
        if isinstance(value, dict):
            if any(not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', k) for k in value):
                raise ValueError('Structural keys required')
            return {k: walk(v, k) for k, v in value.items()}
        if isinstance(value, list):
            return [walk(v, key) for v in value]
        if value is None or type(value) is bool:
            return value
        if key in IDENTITIES:
            return int(identity(value)) if type(value) is int else identity(value)
        if key in SECRETS:
            return 'synthetic-secret'
        if isinstance(value, str):
            if not value:
                return ''
            number = strings.setdefault(value, str(len(strings) + 1))
            if value.startswith(('https://', 'http://')):
                return 'https://example.invalid/synthetic-' + number
            if key == 'username':
                return 'fixture_user_' + number
            if key == 'code':
                return 'FIX_' + number
            if key in TEXT:
                return 'Synthetic text ' + number
            if key in ('end_cursor', 'after') and value.isdigit():
                return '20'
            return 'synthetic-' + number
        if type(value) in (int, float):
            return type(value)(1 if value else 0)
        raise ValueError('Unsupported value')
    return [walk(value) for value in values]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('capture', type=Path, help='Local GraphQL NDJSON input; no network requests')
    parser.add_argument('output', type=Path, help='New synthetic output file; refuses existing files')
    args = parser.parse_args()
    try:
        source = re.sub(r'^\s*for\s*\(;;\);', '', args.capture.read_text())
        values = [json.loads(line) for line in source.splitlines() if line.strip()]
        if not values or not all(isinstance(value, dict) for value in values):
            raise ValueError
        result = derive(values)
        if problems(result):
            raise ValueError
        with args.output.open('x') as stream:
            stream.write(''.join(json.dumps(v, ensure_ascii=False, allow_nan=False) + '\n' for v in result))
    except (OSError, ValueError):
        parser.exit(2, 'Derivation failed; use structural NDJSON and a new writable output path.\n')
    print(f'Derived {len(result)} synthetic object(s); review semantics before committing.')


if __name__ == '__main__':
    main()
