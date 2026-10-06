"""Every numeric column or record field of every dataset carries a declared unit, and each declaration says whether it is verified.

"No undeclared unit" and "verified" are different claims, so both are checked: the first over every recorded response, the second as the status receipt.json gives each declaration. A column the source adds later arrives as `unverified` with status `undeclared` and the warning unit_undeclared, which fails here on the next recording.
"""
import json

import pytest

from conftest import FIXTURES, recorded

VOCABULARY = {"ratio", "multiple", "shares", "count", "rank", "money:quote", "money:financial", "money:unconfirmed", "per_share:quote",
              "per_share:financial", "per_share:unconfirmed", "date", "datetime", "text", "unverified", "per row: see the unit column"}
FAILING = {"quote-xyzqq", "quote-twtr", "history-arm-2021", "history-xyzqq", "history-intraday-reach", "fund-holdings-aapl"}
# Declarations deliberately left unverified, each with the reason a caller is told not to compute with it.
UNVERIFIED = {"Actual", "Expected", "Last", "Revised",  # economic releases: each row's own unit, which the calendar does not state
              "volume24Hr", "volumeAllCurrencies",       # crypto volume: the currency of the count is not stated
              "rank"}                                    # search: Yahoo's ordering score, not a measurement
CASES = sorted(p.stem for p in (FIXTURES / "yahoo").glob("*.json") if p.stem not in FAILING)


def number(text):
    try:
        float(text)
        return True
    except (TypeError, ValueError):
        return False


def numeric_fields(run):
    """Every numeric column or record field the saved file holds, read from the file itself rather than from what the receipt declares."""
    if not run.doc["file"]:
        return set()
    if run.doc["file"]["format"] == "csv":
        rows = run.rows
        if "unit" in rows[0]:
            assert all(r["unit"] for r in rows if r["value"] != ""), "a metric row with a value has no unit"
            return set()
        return {c for c in rows[0] if c != "target" and any(number(r[c]) and r[c] != "" for r in rows) and all(number(r[c]) for r in rows if r[c] != "")}
    found = set()
    for entry in run.records:
        data = entry["data"]
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict):
                found |= {k for k, v in item.items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
    return found


@pytest.mark.parametrize("case", CASES)
def test_every_numeric_column_has_a_declared_unit(cli, case):
    argv = json.loads((FIXTURES / "yahoo" / f"{case}.json").read_text())["provenance"]["argv"]
    run = cli(*argv, routes=recorded(case))
    assert run.code in (0, 7), run
    receipt = run.receipt
    undeclared = sorted(name for name, status in receipt["unit_status"].items() if status == "undeclared")
    assert undeclared == [], f"{case}: no declared unit for {undeclared}"
    assert "unit_undeclared" not in [w["code"] for w in receipt["warnings"]]
    assert set(receipt["units"].values()) <= VOCABULARY, set(receipt["units"].values()) - VOCABULARY
    assert set(receipt["unit_status"].values()) <= {"verified", "declared"}
    for name in numeric_fields(run):
        assert name in receipt["units"] and receipt["unit_status"].get(name) in ("verified", "declared"), f"{case}: {name} is numeric in the file but has no declared unit"
    unverified = {name for name, unit in receipt["units"].items() if unit == "unverified"}
    if run.doc["file"] and run.doc["file"]["format"] == "csv" and "unit" in receipt["columns"]:
        unverified |= {r["metric"] for r in run.rows if r["unit"] == "unverified"}
        unverified -= {"Total Net Assets"}  # fund operations: does not reconcile with totalAssets; the receipt's note says so
    assert unverified <= UNVERIFIED, unverified - UNVERIFIED


def test_the_verified_declarations_are_the_ones_with_a_relation_behind_them(cli):
    run = cli("quote", "KO", routes=recorded("quote-ko"))
    status = run.receipt["unit_status"]
    verified = {name for name, s in status.items() if s == "verified"}
    assert {"dividendYield", "trailingAnnualDividendYield", "payoutRatio", "debtToEquity", "fiftyTwoWeekChangePercent", "52WeekChange",
            "regularMarketChangePercent", "fiftyDayAverageChangePercent", "marketCap", "trailingEps"} <= verified
    assert status["fiveYearAvgDividendYield"] == "declared" and status["heldPercentInsiders"] == "declared"


def test_the_recorded_fixtures_carry_their_provenance():
    for path in sorted((FIXTURES / "yahoo").glob("*.json")):
        provenance = json.loads(path.read_text())["provenance"]
        assert provenance["yfinance"] == "1.7.0" and provenance["recorded_at"] and provenance["argv"], path.name


def test_every_command_kind_has_a_recorded_response():
    """The completeness check above only reaches what was recorded, so every kind the CLI offers must have a recording."""
    argvs = [tuple(json.loads(p.read_text())["provenance"]["argv"][:2]) for p in (FIXTURES / "yahoo").glob("*.json")]
    covered = {a[0] if a[0] in ("quote", "history", "search") else f"{a[0]}.{a[1]}" for a in argvs}
    from invest import load
    expected = {c if not kinds else f"{c}.{k}" for c, kinds in load.kinds().items() for k in (kinds or [None])}
    assert expected - covered == set(), expected - covered


def test_a_numeric_column_without_a_declaration_is_reported_not_guessed(cli):
    rows = [{"symbol": "EX", "currency": "USD", "brandNewMetric": 1.5}]
    routes = [{"path": "/v1/finance/screener", "json": {"finance": {"result": [{"quotes": rows, "total": 1, "start": 0, "count": 1}], "error": None}}}]
    run = cli("screen", "run", "--query", '{"operator":"EQ","operands":["region","us"]}', routes=routes)
    assert run.code == 0, run
    assert run.receipt["units"]["brandNewMetric"] == "unverified" and run.receipt["unit_status"]["brandNewMetric"] == "undeclared"
    assert "unit_undeclared" in [w["code"] for w in run.doc["warnings"]]

