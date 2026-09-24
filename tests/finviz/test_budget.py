"""A result over --max-chars shows the window that fits, says partial, and continues the same selection to the end of the request."""

import json
import shlex

import pytest

from pages import stock_section


def follow(client, first, budget):
    """Run each continuation verbatim until the request is finished; returns every result document seen."""
    documents, command = [first], first.get("continuation")
    while command:
        doc = client.run(*shlex.split(command), "--max-chars", str(budget), code=None)
        documents.append(doc)
        command = doc.get("continuation")
    return documents


CHAIN = {"expiries": ["2026-10-16"], "currentExpiry": "2026-10-16", "lastClose": 152.0, "lastTime": 1789415995, "options": [{"ticker": "A", "strike": strike, "type": kind, "iv": 1.0 + strike / 1000, "delta": 0.5, "openInterest": strike * 3} for strike in range(100, 200, 5) for kind in ("call", "put")]}


@pytest.mark.xfail(strict=True, reason="D2: the recovery for an oversized chain drops the chosen side and fields")
def test_continuing_a_budgeted_option_chain_returns_exactly_the_unbudgeted_selection(client):
    client.add("https://finviz.com/stock?t=A&ty=oc", stock_section(CHAIN))
    selection = ["stock", "options", "A", "--type", "put", "--strikes", "0", "--fields", "strike,type,iv"]
    whole = client.one(*selection, "--max-chars", "100000")["data"]["contracts"]
    assert len(whole) == 20 and {c["type"] for c in whole} == {"put"}
    first = client.run(*selection, "--max-chars", "900", code=8)
    assert first["status"] == "partial" and first["results"][0]["coverage"]["cut"] == "budget"
    pieces = [c for doc in follow(client, first, 900) for c in doc["results"][0]["data"]["contracts"]]
    assert pieces == whole
    assert all(len(json.dumps(doc, ensure_ascii=False, separators=(",", ":"))) <= 900 for doc in follow(client, first, 900))
