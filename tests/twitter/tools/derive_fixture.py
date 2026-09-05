#!/usr/bin/env python3
"""Derive a synthetic structural fixture from a locally captured JSON envelope."""

import argparse
import json
import re
from pathlib import Path


def derive(value):
    identities = {}

    def identity(raw):
        return identities.setdefault(str(raw), str(100 + len(identities)))

    def visit(value, key=""):
        if isinstance(value, dict):
            return {
                k: visit(v, k)
                for k, v in value.items()
                if not re.search(r"ct0|auth_token|cookie|authorization|csrf", k, re.I)
            }
        if isinstance(value, list):
            return [visit(item, key) for item in value]
        if not isinstance(value, str):
            return value
        if key == "body":
            try:
                return json.dumps(visit(json.loads(value)))
            except ValueError:
                return "Synthetic response"
        if value.isdigit() and ("id" in key.lower() or key == "rest_id"):
            return identity(value)
        if key in ("__typename", "type", "itemType", "cursorType", "direction", "verified_type", "action"):
            return value
        if key in ("entryId", "moduleEntryId"):
            return re.sub(r"\d+", lambda m: identity(m[0]), value)
        if key == "screen_name":
            return "example" + identity(value)
        if key == "created_at":
            return "Sat Sep 05 01:00:00 +0000 2026"
        if "url" in key.lower():
            return "https://example.com/synthetic"
        return "Synthetic " + key

    return visit(value)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Local captured JSON to sanitize; never writes to the source.")
    parser.add_argument("output", type=Path, help="Synthetic NDJSON fixture destination.")
    args = parser.parse_args()
    args.output.write_text(json.dumps(derive(json.loads(args.input.read_text())), ensure_ascii=False) + "\n")
