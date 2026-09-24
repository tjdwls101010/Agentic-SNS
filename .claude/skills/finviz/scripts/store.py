"""SQLite observation store: every received response with the envelope extracted from it."""

import json
from pathlib import Path
import sqlite3

from transport import Failure


class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute("CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, envelope TEXT NOT NULL, raw BLOB NOT NULL)")

    def save(self, envelope, raw):
        with self.db:
            self.db.execute("INSERT OR REPLACE INTO observations VALUES (?,?,?)", (envelope["id"], json.dumps(envelope, ensure_ascii=False), raw))

    def get(self, key, raw=False):
        row = self.db.execute("SELECT envelope, raw FROM observations WHERE id=?", (key,)).fetchone()
        if not row:
            raise Failure("unknown_id", "No saved observation with the ID " + key + ".", "Use an id from an earlier result and the same --store.")
        return row[1] if raw else json.loads(row[0])
