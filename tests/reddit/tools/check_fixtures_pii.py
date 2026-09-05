#!/usr/bin/env python3
"""Fail if committed fixtures look like they contain real captured data.

Fixtures under tests/reddit/fixtures/ must be PII-free synthetic skeletons.
Replace all identifying values; never copy captured names or message text. This is a coarse,
allowlist-based gate, not a guarantee: every fixture diff still needs human
review before merge.

SCOPE, STATED PLAINLY: this only pattern-matches structural artifacts (CDN
hosts, token-shaped keys, emails, phone numbers, high-entropy strings). It
has NO detector for free-text PII — a real person's actual name or sensitive
message content, with no token/email/phone/CDN-host/high-entropy-string
anywhere in the line, passes this gate silently. Human review is the actual
control for that category, not this script.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from pathlib import Path

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures"

REAL_CDN_HOSTS = re.compile(
    r"\b(?:[a-z0-9-]+\.)?(?:redd\.it|redditmedia\.com|redditstatic\.com)\b", re.I
)
AUTH_KEYS = re.compile(r'^(?:reddit_session|modhash|cookies?|set[-_]cookie|authorization|auth|'
                       r'proxy[-_]authorization|access_token|refresh_token|id_token|token|'
                       r'csrf_token|x[-_]csrf[-_]token|signature|sig|x[-_]amz[-_]signature)$', re.I)
TOKEN_SHAPED_KEYS = re.compile(r'"' + AUTH_KEYS.pattern[1:-1] + r'"\s*:', re.I)
AUTH_ARTIFACT = re.compile(r'\b(?:reddit_session|modhash|cookie|authorization|auth)\s*[:=]|\bBearer\s+\S+', re.I)
SIGNATURE = re.compile(r'(?:[?&]|\b)(?:signature|sig|x-amz-signature)\s*(?:=|%3[dD])', re.I)

EMAIL = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")
# Requires explicit separators between groups, so a bare long digit run (a
# perfectly normal synthetic numeric value, e.g. "100000000000001")
# doesn't false-positive as a phone number.
PHONE = re.compile(r"\+?\d{1,3}[\s.\-]\d{2,4}[\s.\-]\d{3,4}[\s.\-]?\d{0,4}\b")
# Long runs of base64/hex-ish characters, the shape of a real signed token.
HIGH_ENTROPY_TOKEN = re.compile(r"[A-Za-z0-9+/_=\-]{40,}")


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    freq: dict[str, int] = {}
    for ch in s:
        freq[ch] = freq.get(ch, 0) + 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in freq.values())


def scan_file(path: Path) -> list[str]:
    problems = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), start=1):
        if REAL_CDN_HOSTS.search(line):
            problems.append(f"{path}:{lineno}: real Reddit media host found")
        if TOKEN_SHAPED_KEYS.search(line) or AUTH_ARTIFACT.search(line):
            problems.append(f"{path}:{lineno}: token-shaped cookie/auth field found")
        if SIGNATURE.search(line):
            problems.append(f"{path}:{lineno}: signed URL parameter found")
        if EMAIL.search(line):
            problems.append(f"{path}:{lineno}: email-shaped string found")
        if PHONE.search(line):
            problems.append(f"{path}:{lineno}: phone-shaped string found")
        for match in HIGH_ENTROPY_TOKEN.finditer(line):
            token = match.group(0)
            if shannon_entropy(token) >= 4.0:
                problems.append(
                    f"{path}:{lineno}: high-entropy token-shaped string found (length={len(token)})"
                )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="*", type=Path,
                        help="NDJSON/JSON files or directories to scan recursively; default: sibling fixtures directory")
    args = parser.parse_args()
    paths = args.paths or [FIXTURES_DIR]
    files = []
    for path in paths:
        if not path.exists():
            parser.error("a requested fixture path does not exist")
        if path.is_dir():
            files.extend(p for p in sorted(path.rglob("*")) if p.suffix in {".ndjson", ".json"})
        else:
            files.append(path)
    all_problems: list[str] = []
    for path in files:
        all_problems.extend(scan_file(path))
    if all_problems:
        print("Fixture PII/secret scan FAILED:", file=sys.stderr)
        for problem in all_problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            "\nFixtures must contain synthetic values only. "
            "If this is a false positive on deliberately fake data, "
            "adjust the fixture to use an obviously-fake placeholder instead of "
            "something real-shaped.",
            file=sys.stderr,
        )
        return 1
    print(
        f"Fixture PII/secret scan OK ({len(files)} file(s) checked) "
        "— structural checks only; still needs human review for real names/free-text PII."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
