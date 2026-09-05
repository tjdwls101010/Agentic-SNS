import json
import pytest
from twitter_skill._output import OutFile, CursorStore
from twitter_skill._errors import TwitterError


def test_page_commit_and_incomplete_tail_recovery(tmp_path):
    path = tmp_path / "out.ndjson"
    ctx = {"viewer_id": "1", "operation": "HomeTimeline"}
    out = OutFile(path, ctx)
    out.commit([{"id": "1"}, {"id": "2"}], {"cursor": "next", "pending": []}, "limit_reached")
    out.close()
    with path.open("ab") as stream:
        stream.write(b'{"id":"uncommitted"}\n')
    recovered = OutFile(path, ctx)
    assert recovered.count == 2 and not recovered.complete and recovered.state["cursor"] == "next"
    recovered.commit([{"id": "2"}, {"id": "3"}], {}, "terminated")
    recovered.close()
    records = [json.loads(x) for x in path.read_text().splitlines()]
    assert [r["id"] for r in records if "id" in r] == ["1", "2", "3"]
    with pytest.raises(TwitterError):
        OutFile(path, dict(ctx, viewer_id="2"))


def test_cursor_account_binding_and_permissions(tmp_path, monkeypatch):
    monkeypatch.setenv("TWITTER_HOME", str(tmp_path))
    store = CursorStore()
    handle = store.save({"viewer_id": "1"}, {"pending": [{"id": "1"}], "cursor": "next"})
    assert (tmp_path / "cursors" / f"{handle}.json").stat().st_mode & 0o777 == 0o600
    assert store.load(handle, {"viewer_id": "1"})["pending"] == [{"id": "1"}]
    with pytest.raises(TwitterError):
        store.load(handle, {"viewer_id": "2"})
