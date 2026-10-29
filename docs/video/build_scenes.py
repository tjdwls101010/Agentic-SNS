"""Build src/scenes.json — every number and quote the demo video shows — from a saved `reddit comments --out` reading.

The reading holds other people's words, so it stays outside the repository; only comment ids with their labels (data/walkman-labels.json) and the few short quotes below are committed. Rerun after a new reading:

    uv run docs/video/build_scenes.py <reading.ndjson> "<the summary line that command printed>"
    uv run docs/video/build_scenes.py --check <reading.ndjson> "<summary line>"   # exit 1 when src/scenes.json disagrees
"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
LABELS = HERE / "data" / "walkman-labels.json"
SCENES = HERE / "src" / "scenes.json"

CATEGORIES = {
    "A": "It's absurdly overpriced",
    "C": "Defending it — someone will buy",
    "B": "\"For that money you could buy…\"",
    "E": "Blame memory-chip prices? (argued)",
    "D": "The specs don't match the price",
    "F": "Wanted a different product",
    "G": "Jokes & off-topic",
}

# (comment id, exact excerpt). The excerpt must appear verbatim in that comment.
QUOTES = {
    "A": ("t1_pgya44h", "One… gold plated screw… how can anyone not want this?"),
    "B": ("t1_pgypjkj", "you could buy an RTX 5090 for the price of the most expensive one."),
    "C": ("t1_ph21a6v", "for those that can afford this, price is never the issue"),
    "E": ("t1_pgzwiac", "The $5900 one has 256gb of storage. Even at today’s crazy prices that’s *maybe* $40 worth."),
    "D": ("t1_ph7savi", "TFT screen on a 6k device lol."),
}

DELETED = {"", "[deleted]", "[removed]"}


def build(reading: Path, summary: str) -> dict:
    rows = [json.loads(line) for line in reading.read_text().splitlines() if line.strip()]
    post = next(r for r in rows if r.get("kind") == "post")
    comment_rows = [r for r in rows if r.get("kind") == "comment"]
    comments = {r["id"]: r for r in comment_rows}
    if len(comments) != len(comment_rows):
        raise SystemExit("the reading repeats a comment id")
    labels = json.loads(LABELS.read_text())

    deleted = [cid for cid, c in comments.items() if (c.get("text") or "").strip() in DELETED]
    unlabeled = [cid for cid in comments if cid not in labels and cid not in deleted]
    stale = [cid for cid in labels if cid not in comments or cid in deleted]
    if unlabeled or stale:
        raise SystemExit(f"labels out of step with the reading: unlabeled {unlabeled}, deleted or not in reading {stale}")
    unknown = sorted({v for v in labels.values()} - CATEGORIES.keys())
    if unknown:
        raise SystemExit(f"unknown labels {unknown}")

    quotes = {}
    for key, (cid, excerpt) in QUOTES.items():
        text = comments[cid].get("text") or ""
        if excerpt not in text:
            raise SystemExit(f"quote for {key} is not in comment {cid}")
        if labels[cid] != key:
            raise SystemExit(f"quote for {key} comes from a comment labeled {labels[cid]}")
        quotes[key] = excerpt.replace("*", "")

    counts = Counter(labels.values())
    requests = re.search(r"requests=(\d+)", summary)
    stopped = re.search(r"stopped=(\w+)", summary)
    saved = re.search(r"(\d+) saved", summary)
    if not requests or not stopped or not saved:
        raise SystemExit("summary line lacks N saved, requests= or stopped=")
    # --out saves the post once, then every comment.
    if int(saved.group(1)) != 1 + len(comments):
        raise SystemExit(f"summary says {saved.group(1)} saved but the reading holds the post and {len(comments)} comments")
    # The path in the summary is this computer's; the video shows only the file name.
    shown_summary = re.sub(r'saved to "[^"]*/([^"/]+)"', r'saved to "\1"', summary.strip())

    return {
        "subreddit": f"r/{post['subreddit']}",
        "title": post["title"],
        "commentsRead": len(comments),
        "deleted": len(deleted),
        "labeled": len(labels),
        "requests": int(requests.group(1)),
        "stopped": stopped.group(1),
        "summaryLine": shown_summary,
        "categories": [
            {"key": k, "label": CATEGORIES[k], "count": counts[k], "quote": quotes.get(k)}
            for k in sorted(CATEGORIES, key=lambda k: (k == "G", -counts[k]))
        ],
    }


def main(argv: list[str]) -> int:
    check = argv[:1] == ["--check"]
    args = argv[1:] if check else argv
    if len(args) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    scenes = build(Path(args[0]), args[1])
    rendered = json.dumps(scenes, ensure_ascii=False, indent=2) + "\n"
    if check:
        if SCENES.read_text() != rendered:
            print("src/scenes.json disagrees with the reading; rerun without --check", file=sys.stderr)
            return 1
        print("src/scenes.json matches the reading")
        return 0
    SCENES.write_text(rendered)
    print(f"wrote {SCENES}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
