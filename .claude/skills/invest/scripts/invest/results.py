"""Results saved under the skill's data/results: one new folder per call, published whole or not at all, never overwriting another.

Each call gets its own id, so a later call can never replace what an earlier receipt points to. The folder is written under a temporary name and renamed into place, so a reader never sees half a result. Age decides only when bytes are deleted: whether a value is current is what the receipt's own times say.
"""
import csv
import datetime as dt
import io
import json
import os
from pathlib import Path
import secrets
import shutil
import time

from invest.receipts import LocalIO

# The skill's own data folder, found from this file rather than the cwd; INVEST_DATA moves it (tests give each run its own).
DEFAULT = Path(__file__).resolve().parents[2] / "data"
RECEIPT, TABLE, RECORDS = "receipt.json", "result.csv", "result.json"


def root():
    return Path(os.environ.get("INVEST_DATA") or DEFAULT)


def folder():
    return root() / "results"


def new_id():
    """Time first so a listing sorts by when, then random so two calls in one second never share a folder."""
    return f"{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S}-{secrets.token_hex(3)}"


def paths(ident):
    base = folder() / ident
    return {"receipt": str(base / RECEIPT), "csv": str(base / TABLE), "json": str(base / RECORDS)}


def cell(value):
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return value


def csv_text(columns, rows):
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(columns)
    writer.writerows([cell(v) for v in row] for row in rows)
    return buffer.getvalue()


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=1, allow_nan=False) + "\n"


def publish(ident, receipt, table=None, records=None):
    """Write the receipt and the result file under a temporary name, then rename the folder into place.

    `table` is (columns, rows) for result.csv and `records` any JSON value for result.json. A failure leaves no folder at the final name, so no receipt names a path that does not exist.
    """
    target = folder() / ident
    staging = folder() / f".{ident}.{secrets.token_hex(3)}.part"
    try:
        staging.mkdir(parents=True, mode=0o700)
        if table is not None:
            (staging / TABLE).write_text(csv_text(*table), encoding="utf-8")
        if records is not None:
            (staging / RECORDS).write_text(json_text(records), encoding="utf-8")
        (staging / RECEIPT).write_text(json_text(receipt), encoding="utf-8")
        if target.exists():
            raise FileExistsError(f"{target} already exists")
        os.rename(staging, target)
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise LocalIO(f"The result could not be saved in {folder()}: {exc}",
                      fix="Make the skill's data folder writable (or INVEST_DATA's, when it is set) and run the command again.") from None
    return target


def prune(ttl_days, now=None):
    """Delete saved folders older than the retention window; 0 keeps everything. Leftover partial folders go after an hour."""
    now = now or time.time()
    removed = 0
    for kind in ("results", "filings"):
        base = root() / kind
        if not base.is_dir():
            continue
        for path in base.iterdir():
            try:
                age = now - path.stat().st_mtime
                stale = (path.name.endswith(".part") and age > 3600) or (ttl_days and age > ttl_days * 86400)
                if stale:
                    shutil.rmtree(path) if path.is_dir() else path.unlink()
                    removed += 1
            except OSError:
                pass
    return removed
