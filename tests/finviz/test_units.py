"""A unit is declared only where a JSON number was matched against the string the page displays for the same security."""

SCALE = {"millions USD": 1e6, "millions of shares": 1e6, "shares": 1, "USD per share": 1}
SUFFIX = {"K": 1e3, "M": 1e6, "B": 1e9, "T": 1e12}

# (leaf, field, variant) -> (API number, the displayed string it was matched against, relative tolerance, where both came from).
# A tolerance above 1% marks a scale check against a neighbouring displayed value rather than the same figure.
EVIDENCE = {
    ("stock short-interest", "shortInterest", None): (139.749097, "139.75M", 0.001, "AAPL 2026-09-24: last reading vs overview Short Interest"),
    ("stock short-interest", "sharesFloat", None): (14576.2, "14.58B", 0.001, "AAPL 2026-09-24: last reading vs overview Shs Float"),
    ("stock short-interest", "averageVolume", None): (54717173.59375, "53.09M", 0.05, "AAPL 2026-09-24: last reading vs overview Avg Volume, a different averaging window"),
    ("stock earnings", "salesActual", None): (109417 + 111184 + 143756 + 102466, "466.82B", 0.001, "AAPL 2026-09-24: four reported quarters vs overview Sales (ttm)"),
    ("stock earnings", "salesEstimate", None): (109038.8999, "109.42B", 0.05, "AAPL 2026-09-24: 2026Q3 estimate vs the 466.82B-scale actual it preceded (109,417)"),
    ("stock earnings", "epsActual", None): (2.02 + 2.01 + 2.84 + 1.85, "8.72", 0.001, "AAPL 2026-09-24: four reported quarters vs overview EPS (ttm)"),
    ("stock earnings", "epsReportedActual", None): (2.02 + 2.009 + 2.842 + 1.848, "8.72", 0.001, "AAPL 2026-09-24: four reported quarters vs overview EPS (ttm)"),
    ("stock earnings", "epsEstimate", None): (1.9823, "1.98", 0.005, "AAPL 2026-09-24: 2026Q4 estimate vs overview EPS next Q"),
    ("stock earnings", "epsReportedEstimate", None): (1.9823, "1.98", 0.005, "AAPL 2026-09-24: 2026Q4 estimate vs overview EPS next Q"),
    ("stock earnings", "mean", "E"): (1.9823, "1.98", 0.005, "AAPL 2026-09-24: newest 2026Q4 E revision vs overview EPS next Q"),
    ("stock earnings", "mean", "R"): (3.798, "3.798", 0.001, "SNX 2026-09-24: newest 2026Q3 R revision vs the page's epsReportedEstimate for 2026Q3 (4.7019 epsEstimate differs)"),
    ("stock earnings", "mean", "S"): (113250.5697, "109.42B", 0.05, "AAPL 2026-09-24: newest 2026Q4 S revision vs the scale of the 2026Q3 actual"),
    ("stock earnings", "high", "E"): (2.07, "1.98", 0.05, "AAPL 2026-09-24: 2026Q4 high E vs EPS next Q, scale"),
    ("stock earnings", "high", "R"): (2.07, "1.98", 0.05, "AAPL 2026-09-24: 2026Q4 high R vs EPS next Q, scale"),
    ("stock earnings", "high", "S"): (117219.7, "109.42B", 0.08, "AAPL 2026-09-24: 2026Q4 high S vs the 2026Q3 actual, scale"),
    ("stock earnings", "low", "E"): (1.91, "1.98", 0.05, "AAPL 2026-09-24: 2026Q4 low E vs EPS next Q, scale"),
    ("stock earnings", "low", "R"): (1.91, "1.98", 0.05, "AAPL 2026-09-24: 2026Q4 low R vs EPS next Q, scale"),
    ("stock earnings", "low", "S"): (109410.3, "109.42B", 0.05, "AAPL 2026-09-24: 2026Q4 low S vs the 2026Q3 actual, scale"),
    ("stock holdings", "marketCap", None): (4918530.28, "4918.53B", 0.001, "SPY holdings 2026-09-24: AAPL vs AAPL overview Market Cap the same day"),
    ("calendar earnings", "marketCap", None): (401348.32823115773, "401.35B", 0.001, "COST 2026-09-24: calendar item vs overview Market Cap"),
}


def displayed(text):
    return float(text[:-1]) * SUFFIX[text[-1]] if text[-1] in SUFFIX else float(text)


def declared(client):
    for group, names in client.one("schema")["data"]["groups"].items():
        for name in names:
            units = client.one("schema", *([group] + ([name] if name else [])))["data"].get("units") or {}
            for field, unit in units.items():
                if isinstance(unit, dict):
                    for variant, value in unit.items():
                        if variant != "by":
                            yield (group + " " + name, field, variant), value
                else:
                    yield (group + " " + name, field, None), unit


def test_every_declared_unit_has_matched_evidence_and_the_evidence_agrees(client):
    units = dict(declared(client))
    assert units, "no units are declared"
    missing = [key for key, unit in units.items() if unit != "unresolved" and key not in EVIDENCE]
    assert not missing, missing
    for key, (number, text, tolerance, _) in EVIDENCE.items():
        unit = units.get(key)
        assert unit in SCALE, (key, unit)
        assert abs(number * SCALE[unit] - displayed(text)) <= tolerance * displayed(text), (key, number, unit, text)
