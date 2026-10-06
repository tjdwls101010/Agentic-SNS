"""Yahoo Finance through the yfinance library: each dataset fetched and handed back in the skill's own terms (normalised values, their units, when they were true, what they cover) and each failure the source reports read into the skill's failure codes."""
from invest.yahoo.catalog import fetch, kinds

__all__ = ["fetch", "kinds"]
