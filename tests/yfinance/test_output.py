"""Selection: which end of a series a limit keeps, what a projection reaches, and what coverage admits it left out."""
import sys

import pytest

from conftest import SCRIPTS, inflate, shape

sys.path.insert(0, str(SCRIPTS))

import leaves  # noqa: E402
import output  # noqa: E402


class Args:
    def __init__(self, **kw):
        self.fields = kw.get("fields")
        self.limit = kw.get("limit")
        self.list_fields = kw.get("list_fields", False)
        self.filter = kw.get("filter", "")
        for key in ("row_start",):
            if key in kw:
                setattr(self, key, kw[key])


def table(n, start=0):
    """A series the source publishes oldest first, with the row's own position as its value."""
    return {"index": [f"20{20 + (start + i) // 250:02d}-01-{(start + i) % 28 + 1:02d}" for i in range(n)],
            "columns": ["Close"], "data": [[float(start + i)] for i in range(n)],
            "index_names": ["Date"], "column_names": [None]}


# ---- B1: the limit keeps the wrong end, silently ------------------------------------------------------------------


def test_a_limit_on_an_oldest_first_series_keeps_the_newest_rows():
    """Reproduces B1. `prices history --period 5y --limit 5` answered with 2021 and status ok: a prefix cut on a
    series published oldest first always returns the oldest fragment, and nothing in the result said so."""
    item = leaves.get("prices", "history")
    assert item.recent is True
    data, coverage = output.select(table(1255), Args(limit=5), item)
    assert [row[0] for row in data["data"]] == [1250, 1251, 1252, 1253, 1254]
    assert coverage == {"received": 1255, "kept": "newest", "truncated_by": "explicit_limit", "shown": 5, "exhaustive": False}


def test_a_limit_on_a_newest_first_series_still_keeps_the_newest_rows():
    """The control the plan demanded: `analysts upgrades` arrives newest first, so the old prefix cut was already
    right there. A single global flip would have regressed this leaf while fixing the others."""
    item = leaves.get("analysts", "upgrades")
    assert item.recent is False
    data, coverage = output.select(table(971), Args(limit=20), item)
    assert [row[0] for row in data["data"]] == list(range(20))
    assert coverage["kept"] == "first"


@pytest.mark.parametrize("key,recent", [(("prices", "history"), True), (("prices", "actions"), True), (("company", "shares"), True),
                                        (("analysts", "history"), True), (("analysts", "upgrades"), False),
                                        (("holders", "insider-transactions"), False), (("company", "filings"), False)])
def test_each_leaf_keeps_the_direction_measured_for_it(key, recent):
    assert leaves.get(*key).recent is recent


def test_coverage_names_the_cut_even_when_the_leaf_chose_it():
    item = leaves.get("company", "filings")
    _, coverage = output.select([{"date": f"2026-01-{i + 1:02d}", "type": "8-K", "title": "t", "edgarUrl": "u"} for i in range(80)], Args(), item)
    assert coverage["truncated_by"] == "leaf_default" and coverage["shown"] == 20 and coverage["exhaustive"] is False


def test_an_untruncated_result_says_so():
    _, coverage = output.select(table(3), Args(), leaves.get("prices", "history"))
    assert coverage["exhaustive"] is True and "kept" not in coverage


# ---- paging: the window walks forward -----------------------------------------------------------------------------


def test_a_paged_read_walks_forward_instead_of_returning_the_same_tail():
    """With `recent` applied to a paged read, every --start returned the same newest rows: the counts summed to the
    whole series while the early rows were never shown once."""
    item = leaves.get("prices", "history")
    seen, start = [], 0
    while True:
        data, coverage = output.select(table(1000), Args(limit=400, row_start=start), item)
        seen += [row[0] for row in data["data"]]
        start += coverage["shown"]
        if start >= coverage["received"]:
            break
    assert seen == list(range(1000))
    assert len(set(seen)) == 1000


def test_a_start_past_the_end_is_refused_rather_than_returning_nothing():
    with pytest.raises(output.InputError, match="past the 10 rows"):
        output.select(table(10), Args(row_start=10), leaves.get("prices", "history"))


# ---- projection ----------------------------------------------------------------------------------------------------


def test_a_dotted_path_reaches_a_nested_payload():
    """company news nests its article under content, so only a dotted projection reduces it; a flat --fields could
    name nothing that worked, which is what made the old recovery sentence unfollowable."""
    item = leaves.get("company", "news")
    records = [{"id": f"i{n}", "content": inflate(shape("news_item"), n)["content"]} for n in range(10)]
    data, coverage = output.select(records, Args(fields=["content.title", "content.provider.displayName"]), item)
    assert set(data[0]) == {"content.title", "content.provider.displayName"}
    assert data[0]["content.provider.displayName"] is not None
    assert coverage["fields"]["shown"] == 2 and coverage["fields"]["source"] == "requested"


def test_the_default_projection_drops_the_fields_measured_as_the_bulk():
    item = leaves.get("company", "news")
    records = [{"id": f"i{n}", "content": inflate(shape("news_item"), n)["content"]} for n in range(10)]
    data, _ = output.select(records, Args(), item)
    assert "content.thumbnail" not in data[0] and "content.storyline" not in data[0]
    assert len(output.dump(data)) < len(output.dump(records)) / 2


def test_list_fields_names_the_dotted_paths_a_projection_can_use():
    item = leaves.get("company", "news")
    records = [{"id": "i", "content": inflate(shape("news_item"))["content"]}]
    listed, _ = output.select(records, Args(list_fields=True), item)
    assert "content.title" in listed and "content.provider.displayName" in listed


def test_an_unknown_field_is_refused_with_where_to_look():
    with pytest.raises(output.InputError, match="--list-fields"):
        output.select(table(3), Args(fields=["Opne"]), leaves.get("prices", "history"))


def test_a_default_projection_never_fails_on_a_target_that_lacks_a_field():
    """A default projection describes the common shape; a thinly reported instrument must not become an error."""
    item = leaves.get("prices", "quote")
    data, coverage = output.select({"symbol": "X", "currency": "USD"}, Args(), item)
    assert data == {"symbol": "X", "currency": "USD"}
    assert coverage["fields"]["shown"] == 2


def test_a_table_slice_keeps_its_column_names_and_index():
    """A generic JSON pointer into the encoded rows would return an unlabelled array; the leaf's own selector keeps
    the row labels attached to the rows."""
    data, _ = output.select(table(10), Args(limit=3, fields=["Close"]), leaves.get("prices", "history"))
    assert data["columns"] == ["Close"] and data["index_names"] == ["Date"] and len(data["index"]) == 3


# ---- conditions -----------------------------------------------------------------------------------------------------


def test_a_date_range_is_confirmed_from_the_rows_not_from_the_request():
    rows = {"index": [0, 1], "columns": ["Event Start Date"], "data": [["2026-10-01"], ["2026-10-01"]], "index_names": [None], "column_names": [None]}
    found = output.within_dates(rows, "Event Start Date", "2026-10-01", "2026-10-01")
    assert found["status"] == "confirmed" and found["evidence"]["outside"] == []


def test_a_row_outside_the_requested_range_reports_the_condition_as_not_applied():
    rows = {"index": [0], "columns": ["Event Start Date"], "data": [["2026-11-20"]], "index_names": [None], "column_names": [None]}
    found = output.within_dates(rows, "Event Start Date", "2026-10-01", "2026-10-01")
    assert found["status"] == "not_applied" and found["evidence"]["outside"] == ["2026-11-20"]


def test_an_envelope_carries_no_field_that_merely_echoes_the_request():
    """A004/A3: context reported region="NOTAREGION" for a response that held United States data, so the CLI actively
    asserted a condition it had not checked."""
    envelope = output.result("AAPL", {"a": 1}, context={"currency": "USD"}, coverage={"received": 1, "shown": 1})
    assert "request" not in envelope
    assert envelope["context"] == {"currency": "USD"}


def test_a_source_epoch_is_reported_in_the_same_form_as_every_other_time():
    envelope = output.result("AAPL", {"a": 1}, source_time=1789761602)
    assert envelope["source_time"].startswith("2026-") and envelope["source_time"].endswith("+00:00")
