"""Yahoo Finance through the yfinance library: the dataset a command names, its response fetched and encoded, and the failures the source reports, in the skill's own terms.

A command (cli.py) names its dataset by key; a feature joins the two into a Leaf with `dataset(key)`.
"""
from yfinance_skill.yahoo.catalog import dataset, fetch
from yfinance_skill.yahoo.refusals import NoData, RateLimited, SourceConstraint, SourceFailure

__all__ = ["NoData", "RateLimited", "SourceConstraint", "SourceFailure", "dataset", "fetch"]
