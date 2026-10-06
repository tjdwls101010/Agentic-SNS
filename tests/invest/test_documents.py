"""Saved filing documents under data/filings: one folder per key, reused for the same source, bytes, text version and declared charset, published whole or not at all."""
import os
from pathlib import Path
import time

import pytest

from invest import documents, results

SOURCE = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"
OTHER = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000080/aapl-20250927.htm"
FILES = {"document.txt": "SOURCE x\nline\n", "map.json": "{}\n", "source.json": "{}\n", "original.htm": b"<p>x</p>"}


@pytest.fixture(autouse=True)
def data(tmp_path, monkeypatch):
    monkeypatch.setenv("INVEST_DATA", str(tmp_path / "data"))
    return tmp_path / "data"


def test_the_key_changes_with_the_source_the_bytes_the_text_version_and_the_declared_charset():
    base = documents.key(SOURCE, "a" * 64, 1, "text/html; charset=utf-8")
    assert len(base) == 16 and base == documents.key(SOURCE, "a" * 64, 1, "text/html; charset=UTF-8")
    assert len({base, documents.key(OTHER, "a" * 64, 1, "text/html; charset=utf-8"), documents.key(SOURCE, "b" * 64, 1, "text/html; charset=utf-8"),
                documents.key(SOURCE, "a" * 64, 2, "text/html; charset=utf-8"), documents.key(SOURCE, "a" * 64, 1, "text/html")}) == 5


def test_a_published_folder_holds_every_file_under_the_skill_data(data):
    path, reused = documents.publish("0123456789abcdef", FILES)
    assert path == data / "filings" / "0123456789abcdef" and reused is False
    assert {p.name: (p.read_bytes() if p.suffix == ".htm" else p.read_text()) for p in path.iterdir()} == FILES


def test_the_same_key_reuses_the_folder_and_never_overwrites_it():
    path, _ = documents.publish("0123456789abcdef", FILES)
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir()}
    again, reused = documents.publish("0123456789abcdef", {**FILES, "document.txt": "changed\n"})
    assert again == path and reused is True
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in path.iterdir()} == before


def test_a_write_that_fails_midway_leaves_neither_the_folder_nor_a_staging_copy(data, monkeypatch):
    original = Path.write_bytes

    def failing(self, payload):
        if self.name == "original.htm":
            raise OSError(28, "No space left on device")
        return original(self, payload)

    monkeypatch.setattr(Path, "write_bytes", failing)
    with pytest.raises(Exception) as error:
        documents.publish("0123456789abcdef", FILES)
    assert getattr(error.value, "code", None) == "local_io"
    assert list((data / "filings").iterdir()) == []


def test_a_folder_another_call_published_first_is_reused_and_this_copy_discarded(data, monkeypatch):
    real = os.rename

    def racing(source, target):
        if not Path(target).exists():
            monkeypatch.setattr(os, "rename", real)
            documents.publish(Path(target).name, {**FILES, "document.txt": "first\n"})  # the other call finishes between our write and our rename
        return real(source, target)

    monkeypatch.setattr(os, "rename", racing)
    path, reused = documents.publish("0123456789abcdef", FILES)
    assert reused is True and (path / "document.txt").read_text() == "first\n"
    assert [p.name for p in (data / "filings").iterdir()] == ["0123456789abcdef"]


def test_old_documents_go_by_age_and_zero_keeps_them(data):
    path, _ = documents.publish("0123456789abcdef", FILES)
    old = time.time() - 30 * 86400
    os.utime(path, (old, old))
    assert results.prune(0) == 0 and path.exists()
    assert results.prune(14) == 1 and not path.exists()
