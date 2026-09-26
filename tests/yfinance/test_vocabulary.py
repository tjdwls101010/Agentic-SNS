"""Closed choices cli.py spells out as literals, checked against the library values they were copied from.

cli.py does not import yfinance, so a choice list that mirrors a library enum is a copy; this is where a library
upgrade that changes the enum shows up, instead of as a region the CLI silently refuses or forwards.
"""
import yfinance as yf


def test_market_regions_are_the_librarys_market_regions(cli):
    proc, doc = cli("schema", "market", "summary")
    assert proc.returncode == 0, proc.stdout[:300]
    assert doc["results"][0]["data"]["arguments"]["--region"]["choices"] == [r.value for r in yf.MarketRegion]


def test_screen_presets_are_the_librarys_presets_in_its_order(cli):
    proc, doc = cli("schema", "screen", "run")
    assert proc.returncode == 0, proc.stdout[:300]
    assert doc["results"][0]["data"]["arguments"]["--preset"]["choices"] == list(yf.PREDEFINED_SCREENER_QUERIES)
