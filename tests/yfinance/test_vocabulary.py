"""Closed choices cli.py spells out as literals, checked against the library values they were copied from.

cli.py does not import yfinance, so a choice list that mirrors a library enum is a copy; this is where a library
upgrade that changes the enum shows up, instead of as a region the CLI silently refuses or forwards.
"""
import re

import yfinance as yf
from yfinance.const import SECTOR_INDUSTY_MAPPING_LC

from conftest import arguments


def choices(group, flag, kind=None):
    entry = next(typed for tags, typed, _ in arguments(group)[flag] if kind is None or tags is None or kind in tags)
    return re.search(r"\{([^}]*)\}", entry)[1].split(",")


def test_market_regions_are_the_librarys_market_regions():
    assert choices("market", "--region", "summary") == [r.value for r in yf.MarketRegion]


def test_screen_presets_are_the_librarys_presets_in_its_order():
    assert choices("screen", "--preset") == list(yf.PREDEFINED_SCREENER_QUERIES)


def test_the_sector_keys_are_the_librarys_sector_keys():
    """market sector takes these keys as a closed choice; the library's own mapping is the list Yahoo serves sectors under."""
    assert sorted(choices("market", "KEY", "sector")) == sorted(SECTOR_INDUSTY_MAPPING_LC)
