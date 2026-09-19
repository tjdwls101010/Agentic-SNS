"""Immutable observations, saved once per adapter return so a paid request survives a result that did not fit.

What is saved is the encoded library return *before* local selection, and nothing else: no query cache, no automatic
refresh, no stored HTTP text. That boundary is the point. A store that recorded the request rather than the response
would let a recovery sentence promise rows the adapter never received, and a store that refreshed itself would make
`read` a second request wearing the name of the first.

Age is a disk-cleanup policy, never a validity test. A quote saved one minute ago is stale the moment the market is
closed, and a statement saved last week is not: freshness is what the source's own timestamp says, which is why
`source_time` travels with the record and `--ttl-days` only decides when bytes are deleted.
"""

import hashlib
import json
import os
from pathlib import Path
import time

from output import InputError, dump

ID_LENGTH = 16  # 성진: 64자 전체를 실으면 다종목 회복 문장이 id만으로 예산을 먹는다; 16자는 충돌 확률이 무시할 만하고 한 줄에 열 개가 들어간다.


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, directory=None):
        self.root = Path(directory) if directory else Path(os.environ.get("YF_STORE") or (Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "yfinance-skill"))
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, ident):
        if not ident or not all(c in "0123456789abcdef" for c in ident) or len(ident) != ID_LENGTH:
            raise InputError(f"'{ident}' is not an observation id; ids are {ID_LENGTH} hex characters and appear as the id field of an earlier result.")
        return self.root / (ident + ".json")

    def save(self, record):
        """Content-addressed: the same observation saved twice is one file, and a changed byte changes the id."""
        data = json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ident = digest(data)[:ID_LENGTH]
        target = self.root / (ident + ".json")
        if not target.exists():
            temporary = target.with_suffix(".part")
            temporary.write_bytes(data)
            temporary.replace(target)
        return ident

    def load(self, ident):
        path = self.path(ident)
        if path.is_symlink():
            raise InputError("Saved observations must not be symbolic links; use a fresh --store directory.")
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            raise InputError(f"No saved observation {ident} in {self.root}. Observations are per store directory; rerun the original command to observe it again.") from None
        if digest(data)[:ID_LENGTH] != ident:
            raise InputError("Saved bytes do not match their identifier; use a fresh --store directory and rerun the original command.")
        return json.loads(data)

    def prune(self, ttl_days):
        """Delete bytes older than the retention window. This says nothing about whether newer bytes are current."""
        if not ttl_days:
            return 0
        cutoff, removed = time.time() - ttl_days * 86400, 0
        for path in self.root.glob("*.json"):
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except OSError:
                pass
        return removed


def record(item, target, request, data, context, warnings, status, conditions, observed_at, source_time):
    """Everything a later read needs to reproduce this observation's meaning, and nothing about how it was printed."""
    return {"command": item.path, "target": target, "request": request, "data": data, "context": context,
            "warnings": list(warnings), "status": status, "conditions": conditions,
            "observed_at": observed_at, "source_time": source_time}


def age_seconds(observed_at):
    import datetime as dt

    try:
        return round((dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(observed_at)).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


def matches_request(saved, request, keys):
    """A continuation is bound to the query that produced it, so a cursor cannot be carried onto different arguments."""
    original = saved.get("request") or {}
    return all(original.get(k) == request.get(k) for k in keys)


def summarize(store):
    return {"directory": str(store.root), "observations": len(list(store.root.glob("*.json"))), "bytes": sum(p.stat().st_size for p in store.root.glob("*.json"))}


def fits(text, budget):
    return len(dump(text) if not isinstance(text, str) else text) <= budget
