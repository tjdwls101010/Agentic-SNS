"""Only SEC read URLs cross this identified, paced HTTP boundary."""

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx
from dotenv import dotenv_values
from output import SecError

TICKERS = "https://www.sec.gov/files/company_tickers_exchange.json"


def identity(env_file=None):
    value = dotenv_values(env_file or Path(__file__).with_name(".env")).get("EDGAR_IDENTITY", "") or ""
    if not re.fullmatch(r"(?:[^\r\n]+\s+)?[^\s@]+@[^\s@]+\.[^\s@]+", value.strip()):
        raise SecError(
            "identity_required",
            "A valid requester email is required.",
            'Set EDGAR_IDENTITY="your-email@your-domain" in Scripts/.env or --env-file.',
        )
    os.environ["EDGAR_IDENTITY"] = value.strip()
    return value.strip()


def validate_url(url):
    try:
        parts = urlsplit(url)
        path = unquote(parts.path)
        if path in ("/ix", "/ix.xhtml", "/ixviewer/doc/action"):
            targets = parse_qs(parts.query).get("doc", [])
            if (
                parts.scheme != "https"
                or parts.hostname != "www.sec.gov"
                or parts.username
                or parts.password
                or parts.port not in (None, 443)
                or parts.fragment
                or len(targets) != 1
                or not targets[0].startswith("/Archives/edgar/data/")
            ):
                raise ValueError
            return validate_url("https://www.sec.gov" + targets[0])
        allowed = (
            (
                parts.hostname == "www.sec.gov"
                and (
                    path == "/files/company_tickers_exchange.json"
                    or re.fullmatch(
                        r"/Archives/edgar/data/[0-9]+/(?:[0-9]{18}/(?:[^/]+/)*[^/]+|[0-9]{10}-[0-9]{2}-[0-9]{6}(?:-index\.html?|\.txt))",
                        path,
                    )
                )
            )
            or (
                parts.hostname == "data.sec.gov"
                and re.fullmatch(r"/submissions/CIK[0-9]{10}(?:-submissions-[0-9]+)?\.json", path)
            )
            or (parts.hostname == "efts.sec.gov" and path == "/LATEST/search-index")
        )
        if (
            parts.scheme != "https"
            or parts.username
            or parts.password
            or parts.port not in (None, 443)
            or not allowed
            or parts.fragment
            or "\\" in path
            or "%" in path
            or any(x in (".", "..") for x in path.split("/"))
            or any(ord(c) < 32 for c in url)
        ):
            raise ValueError
    except ValueError:
        raise SecError(
            "unsafe_url",
            "Only official SEC HTTPS read endpoints and filing documents are allowed.",
            "Use a SEC filing index or document URL without credentials, traversal or an external host.",
        ) from None
    return url


def filing_location(url):
    match = re.match(
        r"/Archives/edgar/data/([0-9]+)/(?:([0-9]{18})/|([0-9]{10}-[0-9]{2}-[0-9]{6}))", urlsplit(url).path
    )
    return (str(int(match[1])).zfill(10), (match[2] or match[3]).replace("-", "")) if match else None


class Transport:
    def __init__(self, store, env_file=None):
        self.store = store
        self.identity = identity(env_file)

    def get(self, url, params=None):
        url = validate_url(url)
        requested_filing = filing_location(url)
        retries = redirects = 0
        with httpx.Client(
            headers={"User-Agent": self.identity, "Accept-Encoding": "gzip, deflate"},
            timeout=30,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            while True:
                validate_url(url)
                self.store.reserve()
                try:
                    response = client.get(url, params=params)
                except httpx.TransportError:
                    if retries < 2:
                        retries += 1
                        continue
                    raise SecError(
                        "connection_failed",
                        "SEC did not respond after three attempts.",
                        "Wait and run the query again.",
                    ) from None
                if response.status_code in (403, 429):
                    raise SecError(
                        "access_denied" if response.status_code == 403 else "rate_limited",
                        f"SEC returned HTTP {response.status_code}; no retry was made.",
                        "Check your requester identity and pause requests before trying again.",
                    )
                if response.is_redirect:
                    redirects += 1
                    if redirects > 3 or not response.headers.get("location"):
                        raise SecError(
                            "redirect_failed",
                            "SEC redirect chain is incomplete or too long.",
                            "Use the final official SEC source URL.",
                        )
                    url = validate_url(urljoin(str(response.url), response.headers["location"]))
                    if requested_filing and filing_location(url) != requested_filing:
                        raise SecError(
                            "filing_mismatch",
                            "SEC redirected to a different filing or filer.",
                            "Verify the original filing index and CIK; do not substitute another filing.",
                        )
                    params = None
                    continue
                if response.status_code >= 500 and retries < 2:
                    retries += 1
                    continue
                if response.status_code >= 400:
                    raise SecError(
                        "not_found" if response.status_code == 404 else "http_error",
                        f"SEC returned HTTP {response.status_code}.",
                        "Verify the exact CIK/accession/URL; do not substitute a recent filing.",
                    )
                body = response.content
                prefix = body[:15000].lower().strip()
                title = re.search(rb"<title[^>]*>(.*?)</title>", prefix, re.DOTALL)
                block_titles = (
                    b"sec.gov | request rate threshold exceeded",
                    b"sec.gov | your request originates from an undeclared automated tool",
                )
                if (
                    (title and title[1].strip() in block_titles)
                    or prefix == b"<html>request rate threshold exceeded</html>"
                    or (
                        title
                        and title[1].strip() == b"access denied"
                        and b"you don't have permission to access" in prefix
                    )
                ):
                    raise SecError(
                        "access_denied",
                        "SEC returned an access-error page.",
                        "Check your identity and pause requests before trying again.",
                    )
                source = {
                    "url": str(response.url),
                    "sha256": self.store.put(body),
                    "fetched_at": datetime.now(UTC).isoformat(),
                    "headers": {"content-type": response.headers.get("content-type", "")},
                }
                return body, source

    def json(self, url, params=None):
        body, source = self.get(url, params)
        try:
            value = json.loads(body)
        except (ValueError, UnicodeError):
            raise SecError(
                "invalid_response", "SEC returned a non-JSON response.", "Verify the endpoint and retry later."
            ) from None
        if not isinstance(value, dict) or "error" in value or value.get("status", 200) not in (200, "200"):
            raise SecError(
                "remote_error",
                "SEC returned an error payload, including possibly a search-window error.",
                "Narrow the search dates or verify the endpoint.",
            )
        return value, source
