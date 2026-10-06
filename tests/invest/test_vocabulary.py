"""Closed choices cli.py spells out as literals, checked against the library values they were copied from, and the kinds it declares against the dataset catalog.

cli.py imports neither yfinance nor invest.yahoo, so its lists are copies; a library upgrade that changes one shows up here instead of as a value the CLI silently refuses or forwards.
"""
import re

import yfinance as yf
from yfinance.const import SECTOR_INDUSTY_MAPPING_LC

from conftest import document
from invest import load


def listed(command, flag):
    line = next(line for line in document(command).splitlines() if line.strip().startswith(flag))
    return re.search(r"\{([^}]*)\}", line)[1].split(",")


def test_market_regions_are_the_librarys_market_regions():
    line = next(line for line in document("market").splitlines() if line.strip().startswith("--region"))
    assert re.search(r"summary: ([A-Z, ]+) \(default US\)", line)[1].split(", ") == [r.value for r in yf.MarketRegion]


def test_screen_presets_are_the_librarys_presets_in_its_order():
    assert listed("screen", "--preset") == list(yf.PREDEFINED_SCREENER_QUERIES)


def test_the_sector_keys_are_the_librarys_sector_keys():
    line = next(line for line in document("market").splitlines() if line.strip().startswith("KEY"))
    assert sorted(re.search(r"sector: ([a-z, -]+);", line)[1].split(", ")) == sorted(SECTOR_INDUSTY_MAPPING_LC)


def test_the_kinds_cli_declares_are_the_catalogs_kinds():
    """The command surface (cli.py) and the datasets (invest.yahoo, through invest.load) must name the same kinds."""
    root = document()
    declared = {}
    for line in root.splitlines()[root.splitlines().index("commands:") + 1:]:
        if not line.strip():
            break
        typed, rest = line.strip().split(None, 1)
        kinds = rest.split("  ")[-1] if " KIND" in line else ""
        declared[typed] = [k.strip() for k in kinds.split("|")] if " KIND" in line else []
    catalog = load.kinds()
    assert {c: sorted(k) for c, k in declared.items()} == {c: sorted(k) for c, k in catalog.items()}
