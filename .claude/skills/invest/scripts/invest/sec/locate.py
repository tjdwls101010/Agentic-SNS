"""Which URLs name a filing document this skill reads, and where Yahoo's copy of it is fetched from.

Yahoo's filing list points at its own CDN copies; the same document's EDGAR archive URL maps onto that copy, so either names one document. Anything else is refused before any request, so a URL cannot send the skill to an arbitrary host.
"""
from dataclasses import dataclass
import re
from urllib.parse import urlsplit

from invest.receipts import Invalid
from invest.sec.failures import Unsupported

CDN = "https://cdn.yahoofinance.com/prod/sec-filings/{cik:010d}/{accession}/{name}"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accession}/{name}"
NAME = r"[A-Za-z0-9][A-Za-z0-9._-]*"
PATHS = {"cdn.yahoofinance.com": re.compile(rf"/prod/sec-filings/(?P<cik>\d{{10}})/(?P<accession>\d{{18}})/(?P<name>{NAME})"),
         "www.sec.gov": re.compile(rf"/Archives/edgar/data/(?P<cik>\d{{1,10}})/(?P<accession>\d{{18}})/(?P<name>{NAME})")}
ACCEPTED = ("https://cdn.yahoofinance.com/prod/sec-filings/<cik10>/<accession18>/<file> (an exhibits URL from `company filings`) "
            "or https://www.sec.gov/Archives/edgar/data/<cik>/<accession18>/<file>")


@dataclass(frozen=True)
class Located:
    source: str  # the document's EDGAR archive URL, the same for every alias of it
    fetch: str   # Yahoo's copy, the only URL a request goes to


def locate(url):
    """Map a filing URL to its archive identity and Yahoo's copy; refuse any other URL with Invalid, and Yahoo's spreadsheet copies with Unsupported."""
    parts = urlsplit(url)
    if parts.hostname == "s3.amazonaws.com" and parts.path.startswith("/finance-pri-uw2/sec-filings/"):
        raise Unsupported("This is Yahoo's spreadsheet of the filing's financial report, which this skill does not convert.",
                          fix="Open the filing's main HTML document from `company filings` exhibits; its statements are tables there.")
    pattern = PATHS.get(parts.hostname or "")
    match = pattern.fullmatch(parts.path) if pattern else None
    # A netloc that is exactly the host carries no credentials and no port.
    if parts.scheme != "https" or match is None or parts.netloc.lower() != parts.hostname or parts.query or parts.fragment:
        raise Invalid(f"{url} is not a filing document URL this skill reads.", fix=f"Pass {ACCEPTED}, without a query or fragment.")
    cik, accession, name = int(match["cik"]), match["accession"], match["name"]
    return Located(ARCHIVE.format(cik=cik, accession=accession, name=name), CDN.format(cik=cik, accession=accession, name=name))
