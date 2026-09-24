import json

import pytest

from pages import MAP_CHUNK, MAP_LOADER, MAP_RUNTIME, groups_page, map_page


def test_groups_table_rows_carry_the_screener_filter_and_confirm_group_and_sort(client):
    client.add("https://finviz.com/groups?g=sector&v=110", groups_page())
    result = client.one("groups", "table")
    assert result["data"]["groups"][0] == {"No.": "1", "Name": "Basic Materials", "Stocks": "291", "Market Cap": "2882.47B", "Dividend": "1.93%", "filter": "sec_basicmaterials"}
    assert result["conditions"]["group"] == {"requested": "sector", "status": "confirmed", "evidence": "sector"} and "sort" not in result["conditions"]
    client.add("https://finviz.com/groups?g=industry&sg=basicmaterials&v=120&o=-marketcap", groups_page(selected_group=("groups?g=industry&v=110&o=name&st=d1", "groups?g=industry&sg=basicmaterials&v=110&o=name&st=d1")))
    result = client.one("groups", "table", "--group", "industry/basicmaterials", "--view", "valuation", "--sort=-marketcap")
    assert result["conditions"]["group"]["status"] == "confirmed" and result["conditions"]["sort"]["status"] == "not_applied"


def test_group_and_sort_identifiers_are_closed_choices_in_the_help(client):
    help_text = " ".join(client.raw("groups", "table", "--help", code=0).stdout.split())
    assert "industry/technology" in help_text and "marketcap (Market Capitalization)" in help_text
    assert client.one("groups", "table", "--sort", "bogus", code=2)["error"]["code"] == "invalid_argument"
    assert client.one("groups", "table", "--group", "sectors", code=2)["error"]["code"] == "invalid_argument"
    assert client.one("groups", "options", code=2)["error"]["code"] == "invalid_argument"


def test_groups_performance_returns_source_records_for_every_period(client):
    perf = [{"ticker": "basicmaterials", "label": "Basic Materials", "group": "", "screenerUrl": "screener?f=sec_basicmaterials&v=211", "perfT": -0.83, "perfW": -5.58, "perfYtd": 13.37}]
    client.add("https://finviz.com/api/groups_perf?g=sector", perf)
    assert client.one("groups", "performance")["data"]["groups"] == perf
    client.add("https://finviz.com/api/groups_perf?g=industry&sg=energy", perf)
    result = client.one("groups", "performance", "--group", "industry/energy")
    assert result["data"]["groups"] == perf and result["conditions"]["group"] == {"requested": "industry/energy", "status": "unverified", "evidence": {"first_screener_url": "screener?f=sec_basicmaterials&v=211"}}


def test_quotes_are_records_keyed_by_instrument_and_leave_sparklines_out_until_asked(client):
    quotes = {"6A": {"label": "AUD", "ticker": "6A", "last": 0.71145, "sparkline": [1, 2, 3], "sparklineDateChanges": ["a"]}, "ES": {"label": "S&P 500", "last": 6600.0}, "ALIAS": {"ticker": "ES", "label": "Alias", "last": None}}
    client.add("https://finviz.com/api/futures_all?timeframe=d", quotes)
    result = client.one("market", "quotes", "futures")
    assert result["data"]["quotes"] == [{"label": "AUD", "ticker": "6A", "last": 0.71145}, {"ticker": "ES", "label": "S&P 500", "last": 6600.0}, {"key": "ALIAS", "ticker": "ES", "label": "Alias", "last": None}]
    assert client.one("read", result["id"], "--sparkline", "--limit", "1")["data"]["quotes"][0]["sparkline"] == [1, 2, 3]
    assert client.one("market", "quotes", "futures", "--filter", "S&P", "--fields", "ticker,last")["data"]["quotes"] == [{"ticker": "ES", "last": 6600.0}]
    assert client.one("market", "quotes", "futures", "--currency", "BTC", code=2)["error"]["code"] == "invalid_argument"
    client.add("https://finviz.com/api/crypto_all?timeframe=w&c=BTC", {"ETHBTC": {"label": "ETH", "last": 0.03}})
    assert client.one("market", "quotes", "crypto", "--timeframe", "w", "--currency", "BTC")["data"]["quotes"] == [{"ticker": "ETHBTC", "label": "ETH", "last": 0.03}]


def test_market_performance_lists_every_period_per_instrument_and_confirms_the_crypto_currency(client):
    rows = [{"ticker": "6A", "label": "AUD", "group": "CURRENCIES", "last": 0.70295, "perfDayPct": -0.02, "perfYearPct": 7.21}]
    client.add("https://finviz.com/api/futures/performance", {"rows": rows})
    assert client.one("market", "performance", "futures")["data"]["instruments"] == rows
    client.add("https://finviz.com/api/crypto/performance?c=BTC", {"currency": "BTC", "rows": [{"ticker": "ETHBTC", "perfDayPct": 1.0}]})
    assert client.one("market", "performance", "crypto", "--currency", "BTC")["conditions"]["currency"] == {"requested": "BTC", "status": "confirmed", "evidence": "BTC"}


def test_market_map_is_performance_records_and_joins_the_classification_on_request(client):
    client.add("https://finviz.com/api/map_perf?t=sec&st=d1", {"nodes": {"AAPL": 1.0, "MSFT": -0.5}, "subtype": "d1", "version": 15})
    default = client.one("market", "map")
    assert default["data"]["tickers"] == [{"ticker": "AAPL", "d1": 1.0}, {"ticker": "MSFT", "d1": -0.5}]
    assert default["data"]["period"] == "d1" and "dependencies" not in default["source"]
    client.add("https://finviz.com/api/map_perf?t=sec&st=w1", {"nodes": {"AAPL": 1.0}, "subtype": "d1", "version": 15})
    assert client.one("market", "map", "--period", "w1")["conditions"]["period"] == {"requested": "w1", "status": "not_applied", "evidence": "d1"}
    assert client.one("market", "map", "--type", "sec_ixic", code=2)["error"]["code"] == "invalid_argument"
    client.add("https://finviz.com/api/map_perf?t=sec&st=pe", {"nodes": {"AAPL": 35.2}, "subtype": "pe", "version": 15})
    fundamental = client.one("market", "map", "--period", "pe")
    assert fundamental["data"]["tickers"] == [{"ticker": "AAPL", "pe": 35.2}] and fundamental["conditions"]["period"]["status"] == "confirmed"
    assert client.one("market", "map", "--period", "i5", code=2)["error"]["code"] == "invalid_argument"


def test_market_map_resolves_classification_from_the_page_assets_and_degrades_to_partial(client):
    perf = {"nodes": {"RY": 1.2, "TD": -0.4}, "subtype": "d1", "version": 15}
    client.add("https://finviz.com/api/map_perf?t=geo&st=d1", perf)
    client.add("https://finviz.com/map?t=geo", map_page())
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", "/* legacy loader is in a preceding bundle */")
    client.add("https://finviz.com/assets/dist-legacy/1378.v1.61170fe2.js", MAP_LOADER)
    client.add("https://finviz.com/assets/dist-legacy/runtime.v1.22f44280.js", MAP_RUNTIME)
    client.add("https://finviz.com/assets/dist-legacy/62.v1.bbb222.js", MAP_CHUNK)
    result = client.one("market", "map", "--type", "geo", "--classification")
    assert result["data"]["tickers"] == [{"ticker": "RY", "d1": 1.2, "groups": ["World", "Canada"], "description": "Royal Bank Of Canada", "weight": 294647}, {"ticker": "TD", "d1": -0.4}]
    assert result["data"]["classification_source"].endswith("62.v1.bbb222.js")
    client.add("https://finviz.com/assets/dist-legacy/62.v1.bbb222.js", "module.exports={name:'Other'}")
    degraded = client.one("market", "map", "--type", "geo", "--classification", code=8)
    assert degraded["status"] == "partial" and degraded["error"]["code"] == "asset_structure"
    assert degraded["data"]["tickers"] == [{"ticker": "RY", "d1": 1.2}, {"ticker": "TD", "d1": -0.4}]
    assert client.one("read", degraded["source"]["dependencies"][-1], code=6)["error"]["code"] == "asset_structure"
    assert client.one("read", degraded["id"], code=8)["status"] == "partial"  # a replay does not launder the gap


@pytest.mark.parametrize("map_type,chunk,label", [("geo", 6207, "World"), ("sec_all", 7791, "All stocks"), ("sec", 8119, "S&P 500")])
def test_map_loads_the_requested_universe_from_the_current_entry_script(client, map_type, chunk, label):
    loader = 'function o(e){switch(e){case i.IZ.World:return a(n.e(6207).then(n.t.bind(n,68379,23)));case i.IZ.SectorFull:return a(n.e(7791).then(n.t.bind(n,20375,23)));default:return a(n.e(8119).then(n.t.bind(n,10163,23)))}}'
    loader = "switch(layout){case i.IZ.World:render();break;default:return n.e(9999)};" + loader
    client.add(f"https://finviz.com/api/map_perf?t={map_type}&st=d1", {"nodes": {"TEST": 1.2}, "subtype": "d1"})
    client.add(f"https://finviz.com/map?t={map_type}", map_page())
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", loader)
    client.add("https://finviz.com/assets/dist-legacy/1378.v1.61170fe2.js", "/* no map loader */")
    client.add("https://finviz.com/assets/dist-legacy/4740.v1.b05b832c.js", "/* no map loader */")
    client.add("https://finviz.com/assets/dist-legacy/runtime.v1.22f44280.js", 'r.u=e=>e+".v1."+{6207:"world-test",7791:"full-test",8119:"sector-test"}[e]+".js"')
    suffix = {6207: "world-test", 7791: "full-test", 8119: "sector-test"}[chunk]
    url = f"https://finviz.com/assets/dist-legacy/{chunk}.v1.{suffix}.js"
    tree = {"name": "Root", "children": [{"name": label, "children": [{"name": "TEST", "value": 123, "newField": "kept"}]}]}
    client.add(url, "module.exports=" + json.dumps(tree))
    result = client.one("market", "map", "--type", map_type, "--classification")
    assert result["data"]["tickers"] == [{"ticker": "TEST", "d1": 1.2, "groups": [label], "description": None, "weight": 123}] and result["data"]["classification_source"] == url
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", loader + loader.replace(str(chunk), "9999"))
    ambiguous = client.one("market", "map", "--type", map_type, "--classification", code=8)
    assert ambiguous["error"]["code"] == "asset_structure" and ambiguous["data"]["tickers"] == [{"ticker": "TEST", "d1": 1.2}]
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", loader)
    client.add(url, "a.exports=" + json.dumps(tree) + ";b.exports=" + json.dumps(tree))
    roots = client.one("market", "map", "--type", map_type, "--classification", code=8)
    assert roots["error"]["code"] == "asset_structure" and "found 2" in roots["error"]["message"]


def test_map_does_not_substitute_the_default_for_a_missing_requested_type(client):
    client.add("https://finviz.com/api/map_perf?t=cap&st=d1", {"nodes": {"A": 2}, "subtype": "d1"})
    client.add("https://finviz.com/map?t=cap", map_page())
    client.add("https://finviz.com/assets/dist-legacy/map.v1.aaaa1111.js", MAP_LOADER)
    for name in ("1378.v1.61170fe2.js", "4740.v1.b05b832c.js"):
        client.add("https://finviz.com/assets/dist-legacy/" + name, "/* no map loader */")
    result = client.one("market", "map", "--type", "cap", "--classification", code=8)
    assert result["error"]["code"] == "asset_structure" and "no case for MarketCap" in result["error"]["message"]


def test_bubbles_default_to_a_named_index_and_refuse_an_axis_the_source_rejects(client):
    rows = [{"ticker": "AAPL", "company": "Apple", "x": 1.0, "y": 2.0, "size": 3.0, "color": "Technology", "isETF": False}]
    client.add("https://finviz.com/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=dji", rows)
    result = client.one("market", "bubbles")
    assert result["data"]["stocks"] == rows and result["request"]["index"] == "dji"
    assert result["conditions"]["index"] == {"requested": "dji", "status": "unverified", "evidence": None}
    assert client.one("market", "bubbles", "--index", "sec_all", code=2)["error"]["code"] == "invalid_argument"
    refused = client.one("market", "bubbles", "--x", "industry", code=2)
    assert "marketCap" in refused["error"]["message"] and "--help" in refused["error"]["fix"]
    assert client.one("market", "bubbles", "--size", "sales", code=2)["error"]["code"] == "invalid_argument"
    client.add("https://finviz.com/api/bubbles?x=PE&y=perfYtd&size=averageVolume&color=industry&idx=any", rows)
    assert client.one("market", "bubbles", "--x", "PE", "--y", "perfYtd", "--size", "averageVolume", "--color", "industry", "--index", "any")["data"]["stocks"] == rows


def test_bubble_filters_are_judged_by_the_stocks_that_came_back(client):
    tech = [{"ticker": "AAPL", "color": "Technology"}, {"ticker": "MSFT", "color": "Technology"}]
    client.add("https://finviz.com/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=sp500&sec=technology&tickers=AAPL,MSFT", tech)
    result = client.one("market", "bubbles", "--index", "sp500", "--sector", "technology", "--tickers", "AAPL,MSFT")
    assert result["conditions"]["sector"] == {"requested": "technology", "status": "confirmed", "evidence": {"sectors_returned": ["Technology"]}}
    assert result["conditions"]["tickers"]["status"] == "confirmed"
    client.add("https://finviz.com/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=dji&excludeTickers=AAPL", tech)
    assert client.one("market", "bubbles", "--exclude", "AAPL")["conditions"]["exclude"] == {"requested": "AAPL", "status": "not_applied", "evidence": {"excluded_but_returned": ["AAPL"]}}
    client.add("https://finviz.com/api/bubbles?x=sector&y=lastChange&size=marketCap&color=sector&idx=dji&cap=mega&sh_avgvol=o1000", tech)
    assert client.one("market", "bubbles", "--cap", "mega", "--avg-volume", "o1000")["conditions"]["cap"]["status"] == "unverified"


def test_a_quote_timeframe_changes_only_the_sparkline_and_says_so_without_it(client):
    client.add("https://finviz.com/api/futures_all?timeframe=w", {"ES": {"label": "S&P 500", "last": 6600.0, "change": 0.1, "sparkline": [1, 2]}})
    plain = client.one("market", "quotes", "futures", "--timeframe", "w")
    assert any("--sparkline" in w for w in plain["warnings"])
    assert not client.one("market", "quotes", "futures", "--timeframe", "w", "--sparkline").get("warnings")
