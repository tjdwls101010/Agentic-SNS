import json
from pathlib import Path
import pytest
from twitter_skill._bundles import refresh
from twitter_skill._registry import Registry
from twitter_skill._blocked import write_state
from twitter_skill._errors import TwitterError


def bundle():
    f = json.loads((Path(__file__).parent / "fixtures/transaction.json").read_text())
    html = '<meta name="twitter-site-verification" content="' + f["verification"] + '">'
    for i, paths in f["frames"].items():
        html += f'<svg id="loading-x-anim-{i}"><g>' + "".join(f'<path d="{p}"></path>' for p in paths) + "</g></svg>"
    js = ";".join(f"(a[{i}], 16)" for i in f["indices"])
    return {
        "operations": {"Viewer": "new-viewer"},
        "features": {"new_flag": True},
        "txid_ingredients": {"html": html, "ondemand_js": js, "ondemand_url": "https://abs.twimg.com/example.js"},
    }


class FakeTransport:
    def __init__(self, fail=False):
        self.registry = Registry()
        self.material = None
        self.calls = []
        self.fail = fail

    def auxiliary(self, *args):
        return {"body": json.dumps(bundle())}

    def query(self, op, variables):
        self.calls.append((op, variables))
        if self.fail:
            raise TwitterError(6, "failed")
        return {"rest_id": "1"} if op == "UserByScreenName" else []


def test_refresh_preserves_missing_current_ids_and_flags(tmp_path, monkeypatch):
    monkeypatch.setenv("TWITTER_HOME", str(tmp_path))
    write_state(
        "registry.json",
        {
            "operations": {"HomeTimeline": {"query_id": "current"}},
            "features": {"keep_flag": True},
            "missing_features": ["new_flag", "absent_flag"],
        },
    )
    t = FakeTransport()
    result = refresh(t)
    saved = json.loads((tmp_path / "registry.json").read_text())
    assert saved["operations"]["HomeTimeline"]["query_id"] == "current"
    assert (
        saved["features"]["keep_flag"] is True
        and saved["features"]["new_flag"] is True
        and saved["features"]["absent_flag"] is False
    )
    assert result["verified"] == ["UserByScreenName", "SearchTimeline"] and "HomeTimeline" in result["missing"]
    assert [x[0] for x in t.calls] == result["verified"]
    assert (tmp_path / "txid.json").exists()


def test_failed_verification_saves_nothing(tmp_path, monkeypatch):
    monkeypatch.setenv("TWITTER_HOME", str(tmp_path))
    write_state("registry.json", {"features": {"old": True}})
    original = (tmp_path / "registry.json").read_bytes()
    with pytest.raises(TwitterError):
        refresh(FakeTransport(True))
    assert (tmp_path / "registry.json").read_bytes() == original and not (tmp_path / "txid.json").exists()
