from twitter_skill._listing import collect
from twitter_skill._errors import TwitterError


def test_pending_tail_uses_no_request():
    def fetch(cursor):
        raise AssertionError("tail must be consumed before fetching")

    result = collect(fetch, limit=2, state={"pending": [{"id": "1"}, {"id": "2"}, {"id": "3"}], "cursor": "next"})
    assert [r["id"] for r in result["results"]] == ["1", "2"]
    assert result["state"]["pending"] == [{"id": "3"}]


def test_partial_failure_keeps_resume_cursor():
    def fetch(cursor):
        if cursor:
            raise TwitterError(5, "limited", "Wait", "rate_limit")
        return [{"id": "1"}], "next", {}

    result = collect(fetch, limit=3)
    assert result["code"] == 8 and result["results"] == [{"id": "1"}]
    assert result["state"]["cursor"] == "next" and result["stop_reason"] == "blocked"


def test_empty_user_pages_stop_at_three():
    count = []

    def fetch(cursor):
        count.append(1)
        return [], str(len(count)), {}

    result = collect(fetch, limit=3, users=True)
    assert result["stop_reason"] == "empty_pages" and len(count) == 3 and result["code"] == 8


def test_duplicate_and_same_cursor_eof():
    result = collect(
        lambda cursor: ([{"id": "1"}, {"id": "2"}], "same", {}), limit=10, state={"cursor": "same", "seen": ["1"]}
    )
    assert result["results"] == [{"id": "2"}] and result["stop_reason"] == "exhausted"


def test_date_window_ignores_pin_and_only_stops_proven_monotonic_surface():
    calls = []

    def fetch(cursor):
        calls.append(cursor)
        return (
            (
                [
                    {"id": "pin", "created_at": "2010-01-01", "is_pinned": True},
                    {"id": "new", "created_at": "2026-01-01"},
                ]
                if not cursor
                else [{"id": "old", "created_at": "2020-01-01"}]
            ),
            "next" if not cursor else "end",
            {},
        )

    result = collect(fetch, limit=10, since="2025-01-01", monotonic=True)
    assert result["stop_reason"] == "window_reached" and [r["id"] for r in result["results"]] == ["new"]
    assert len(calls) == 2
    result = collect(
        lambda cursor: ([{"id": "old", "created_at": "2020-01-01"}], None, {}),
        limit=10,
        since="2025-01-01",
        monotonic=False,
    )
    assert result["stop_reason"] == "exhausted"


def test_parent_and_focal_do_not_spend_reply_display_limit():
    result = collect(
        lambda cursor: (
            [
                {"id": "1", "role": "parent"},
                {"id": "2", "role": "focal"},
                {"id": "3", "role": "reply"},
                {"id": "4", "role": "reply"},
            ],
            "next",
            {},
        ),
        limit=1,
    )
    assert [r["id"] for r in result["results"]] == ["1", "2", "3"]
    assert result["state"]["pending"] == [{"id": "4", "role": "reply"}]


def test_export_filters_date_window_but_tracks_full_response(tmp_path):
    import json
    from twitter_skill._output import OutFile

    path = tmp_path / "window.ndjson"
    out = OutFile(path, {"viewer_id": "1"})
    rows = [
        {"id": "old", "created_at": "2020"},
        {"id": "inside", "created_at": "2025"},
        {"id": "future", "created_at": "2027"},
    ]
    result = collect(lambda cursor: (rows, None, {}), limit=1, since="2024", until="2026", out=out)
    out.close()
    records = [json.loads(line) for line in path.read_text().splitlines()]
    assert [r["id"] for r in records if "id" in r] == ["inside"]
    assert set(result["state"]["seen"]) == {"old", "inside", "future"}


def test_hidden_branches_accumulate_unique_identities_and_thread_export(tmp_path):
    import json
    from twitter_skill._output import OutFile

    out = OutFile(tmp_path / "thread.ndjson", {"viewer_id": "1"})

    def fetch(cursor):
        if not cursor:
            return (
                [{"id": "1", "role": "focal"}, {"id": "2", "role": "reply", "in_reply_to_id": "1"}],
                "next",
                {"focal_id": "1", "reported": 9, "hidden_branch_ids": ["a", "b"], "hidden_branches": 2},
            )
        return (
            [{"id": "3", "role": "reply", "in_reply_to_id": "2"}],
            None,
            {"focal_id": "1", "hidden_branch_ids": [], "hidden_branches": 0},
        )

    result = collect(fetch, limit=10, out=out)
    out.close()
    assert result["hidden_branches"] == 2
    records = [json.loads(line) for line in (tmp_path / "thread.ndjson").read_text().splitlines()]
    markers = [r for r in records if r.get("kind") == "page"]
    metadata = markers[-1]["state"]["metadata"]
    assert {key: metadata[key] for key in ("reported", "direct_shown", "nested_shown", "hidden_branches")} == {
        "reported": 9,
        "direct_shown": 1,
        "nested_shown": 1,
        "hidden_branches": 2,
    }
