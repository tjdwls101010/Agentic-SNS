"""Immutable content-addressed records and a process-shared request schedule."""

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
from pathlib import Path

from output import SecError


def digest(data):
    return hashlib.sha256(data).hexdigest()


class Store:
    def __init__(self, directory=None):
        self.root = (
            Path(directory)
            if directory
            else Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "sec-skill"
        )
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = self.root / "requests.sqlite3"
        with sqlite3.connect(self.db, timeout=30) as db:
            db.execute("CREATE TABLE IF NOT EXISTS schedule (id INTEGER PRIMARY KEY CHECK(id=1), next REAL NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS cursor_results (cursor TEXT PRIMARY KEY, result TEXT NOT NULL)")

    def reserve(self):
        with sqlite3.connect(self.db, timeout=30) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT next FROM schedule WHERE id=1").fetchone()
            now = time.time()
            slot = max(now, row[0] if row else now)
            db.execute("INSERT OR REPLACE INTO schedule VALUES (1, ?)", (slot + 0.5,))
        time.sleep(max(0, slot - time.time()))

    def put(self, data):
        key = digest(data)
        path = self.root / key
        with tempfile.NamedTemporaryFile(dir=self.root, delete=False) as temporary:
            temp_path = Path(temporary.name)
            temporary.write(data)
        try:
            try:
                os.link(temp_path, path)
            except FileExistsError:
                self.get(key)
        finally:
            temp_path.unlink()
        return key

    def get(self, key):
        if not re.fullmatch(r"[0-9a-f]{64}", key or ""):
            raise SecError("invalid_cursor", "Invalid saved record identifier.", "Restart the query without a cursor.")
        if (self.root / key).is_symlink():
            raise SecError("cache_corrupt", "Saved records must not be symbolic links.", "Use a fresh cache directory.")
        try:
            data = (self.root / key).read_bytes()
        except FileNotFoundError:
            raise SecError(
                "missing_snapshot",
                "The saved record is not in this cache.",
                "Use the original cache directory or restart the query.",
            ) from None
        if digest(data) != key:
            raise SecError(
                "cache_corrupt",
                "Saved bytes do not match their immutable identifier.",
                "Use a fresh cache directory and restart the query.",
            )
        return data

    def save(self, record):
        return self.put(json.dumps(record, sort_keys=True, ensure_ascii=False).encode())

    def resume(self, key, query):
        record = json.loads(self.get(key))
        if record.get("query") != query:
            raise SecError(
                "cursor_mismatch",
                "The cursor belongs to different query options.",
                "Repeat the original command, query, filters and limit or restart without the cursor.",
            )
        for source in record["state"].get("sources", []):
            self.get(source["sha256"])
        return record["state"]

    def replay(self, cursor, query):
        self.resume(cursor, query)
        with sqlite3.connect(self.db, timeout=30) as db:
            row = db.execute("SELECT result FROM cursor_results WHERE cursor=?", (cursor,)).fetchone()
        if row is None:
            return None
        record = json.loads(self.get(row[0]))
        if record.get("cursor") != cursor or record.get("query") != query:
            raise SecError(
                "cache_corrupt",
                "The saved continuation result belongs to another cursor.",
                "Use a fresh cache directory and restart the query.",
            )
        result = record["result"]
        for source in result.get("sources", []):
            self.get(source["sha256"])
        return result

    def complete_cursor(self, cursor, query, result):
        key = self.save({"cursor": cursor, "query": query, "result": result})
        with sqlite3.connect(self.db, timeout=30) as db:
            db.execute("INSERT OR IGNORE INTO cursor_results VALUES (?, ?)", (cursor, key))
        return self.replay(cursor, query)
