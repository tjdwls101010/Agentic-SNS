"""Filing documents saved under the skill's data/filings: one folder per key, published whole under a temporary name, reused and never overwritten.

The key names everything the saved text depends on (the original's URL, its bytes, the text version, the charset the server declared), so the same request reads the same folder and any change gets a new one. Age decides only when bytes are deleted, through results.prune.
"""
import hashlib
import os
import re
import secrets
import shutil

from invest import results
from invest.receipts import LocalIO


def folder():
    return results.root() / "filings"


def key(source, sha256, version, content_type):
    charset = re.search(r"charset=[\"']?([^;\"'\s]+)", content_type or "", re.IGNORECASE)
    parts = [source, sha256, str(version), charset.group(1).lower() if charset else ""]
    return hashlib.sha256("\n".join(parts).encode()).hexdigest()[:16]


def publish(name, files):
    """(path, reused) for `files` {file name: str or bytes} saved as data/filings/<name>; a folder already there, or one another call publishes first, is kept and reused."""
    target = folder() / name
    if target.is_dir():
        return target, True
    staging = folder() / f".{name}.{secrets.token_hex(3)}.part"
    try:
        staging.mkdir(parents=True, mode=0o700)
        for file, content in files.items():
            if isinstance(content, bytes):
                (staging / file).write_bytes(content)
            else:
                (staging / file).write_text(content, encoding="utf-8")
        try:
            os.rename(staging, target)
        except OSError:
            if not target.is_dir():
                raise
            shutil.rmtree(staging, ignore_errors=True)  # another call published the same key first; its folder is the same content
            return target, True
    except OSError as exc:
        shutil.rmtree(staging, ignore_errors=True)
        raise LocalIO(f"The document could not be saved in {folder()}: {exc}",
                      fix="Make the skill's data folder writable (or INVEST_DATA's, when it is set) and run the command again.") from None
    except BaseException:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return target, False
