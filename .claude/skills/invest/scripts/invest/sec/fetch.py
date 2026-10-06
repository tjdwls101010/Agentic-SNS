"""Receiving one document from Yahoo's copy: no redirect followed, one retry for a connection error or server fault, and the whole attempt inside one deadline.

The socket timeout alone bounds only a silence, so a body that keeps arriving a byte at a time would outlast any --timeout; an interval timer (SIGALRM, a Unix main-thread contract like the Yahoo commands' deadline) interrupts the read wherever it is.
"""
import signal
import time

from invest.receipts import Failure
from invest.sec.document import Fetched
from invest.sec.failures import NotFound

# Larger than any filing document measured (TSM's 20-F is the largest); past it a response is not a filing document.
MAX_BYTES = 64 * 1024 * 1024
CHUNK = 1 << 16
RETRY = "Retry later; the copy may be briefly unavailable."


class Retryable(Failure):
    """A connection error or a server fault: worth one more attempt while the deadline allows."""


class Expired(BaseException):
    """A BaseException, so no library handler of Exception swallows the deadline."""


def expired(signum, frame):
    raise Expired()


def fetch(located, timeout):
    """Return Fetched for located.fetch, or raise NotFound (404) or Failure('upstream') for anything else; `timeout` covers the retry too."""
    deadline = time.monotonic() + timeout
    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(signal.ITIMER_REAL, timeout)
    try:
        for attempt in (1, 2):
            try:
                return receive(located, deadline)
            except Retryable as error:
                if attempt == 2 or deadline - time.monotonic() <= 0:
                    raise Failure(f"{error} after {attempt} attempt{'s' if attempt > 1 else ''}.", fix=RETRY) from None
    except Expired:
        raise Failure(f"The --timeout deadline ({timeout} s) passed before {located.fetch} had fully arrived.", fix="Raise --timeout, or retry later.") from None
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def receive(located, deadline):
    import requests

    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise Failure(f"The --timeout deadline passed before {located.fetch} answered.", fix="Raise --timeout, or retry later.")
    try:
        with requests.Session() as session, session.get(located.fetch, timeout=remaining, allow_redirects=False, stream=True) as response:
            status = response.status_code
            if 300 <= status < 400:
                raise Failure(f"Yahoo's copy redirected ({status}) to {response.headers.get('location', 'another address')}, which is not followed.",
                              fix="Pass the document's URL from `company filings` exhibits again; a redirect is not followed to another host.")
            if status == 404:
                raise NotFound(f"Yahoo has no copy at {located.fetch} (404).",
                               fix="Take the URL from `company filings` exhibits; index pages, XBRL viewer pages and some older paths are not copied.")
            if status >= 500:
                raise Retryable(f"Yahoo's copy answered {status}")
            if status != 200:
                raise Failure(f"Yahoo's copy answered {status} for {located.fetch}; it was not retried.", fix=RETRY)
            body = bytearray()
            for chunk in response.iter_content(CHUNK):
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise Failure(f"The response passed {MAX_BYTES // (1024 * 1024)} MB, larger than any filing document.", fix="Check that the URL names one document.")
                if time.monotonic() > deadline:
                    raise Failure(f"The --timeout deadline passed while {located.fetch} was still arriving.", fix="Raise --timeout, or retry later.")
            return Fetched(bytes(body), located.source, response.headers.get("content-type", ""))
    except requests.Timeout:
        raise Retryable(f"No answer from {located.fetch} within the time left") from None
    except (requests.ConnectionError, requests.exceptions.ChunkedEncodingError) as error:
        raise Retryable(f"The connection to {located.fetch} failed ({type(error).__name__})") from None
    except requests.RequestException as error:
        raise Failure(f"The request for {located.fetch} failed ({type(error).__name__}).", fix=RETRY) from None
