#!/usr/bin/env python3
"""Reject credentials, personal contact data and captured account identifiers."""

import argparse
import json
import re
from pathlib import Path


def check(path):
    failures = []
    for file in sorted(path.rglob("*")):
        if file.suffix not in (".json", ".ndjson"):
            continue
        raw = file.read_text()
        records = (
            [json.loads(line) for line in raw.splitlines() if line.strip()]
            if file.suffix == ".ndjson"
            else [json.loads(raw)]
        )

        def visit(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if re.search(r"^(ct0|auth_token|cookie|authorization|x-csrf-token)$", key, re.I):
                        failures.append(f"{file.name}: credential field {key}")
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)
            elif isinstance(value, str):
                if re.search(
                    r"radamshi99|1818125492823986176|[^\s@]+@[^\s@]+\.[a-z]{2,}|Bearer\s+[A-Za-z0-9%]+", value, re.I
                ):
                    failures.append(f"{file.name}: personal identifier or credential")

        for record in records:
            visit(record)
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "fixtures",
        help="Fixture directory to inspect.",
    )
    args = parser.parse_args()
    errors = check(args.path)
    print("\n".join(errors) if errors else "Fixture PII check passed.")
    raise SystemExit(bool(errors))
