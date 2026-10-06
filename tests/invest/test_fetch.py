"""Which filing URLs are read and how one is received, through invest.sec's entry.

locate is pure, so its cases run in process. fetch goes to a real HTTP server on 127.0.0.1 that answers each path as the case says and counts the requests, so redirects, retries and the deadline are observed on the wire rather than through a patched library.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
import time

import pytest

from invest.receipts import Failure, Invalid
from invest.sec import Located, fetch, locate

CDN = "https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019325000079/aapl-20250927.htm"
ARCHIVE = "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/aapl-20250927.htm"


# ---- locate --------------------------------------------------------------------------------------------------------------

def test_a_yahoo_copy_and_its_archive_url_name_one_document_fetched_from_the_copy():
    assert locate(CDN) == locate(ARCHIVE) == Located(ARCHIVE, CDN)


def test_an_archive_cik_without_leading_zeros_maps_to_the_ten_digit_copy_path():
    located = locate("https://www.sec.gov/Archives/edgar/data/1513845/000110465926094844/nbis-20260812xex99d2.htm")
    assert located.fetch == "https://cdn.yahoofinance.com/prod/sec-filings/0001513845/000110465926094844/nbis-20260812xex99d2.htm"


def test_yahoos_spreadsheet_copy_is_unsupported_before_any_request():
    with pytest.raises(Failure) as error:
        locate("https://s3.amazonaws.com/finance-pri-uw2/sec-filings/0000320193/000032019325000079/Financial_Report.xlsx")
    assert error.value.code == "unsupported"


@pytest.mark.parametrize("url", [
    "http://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019325000079/aapl-20250927.htm",
    "https://example.com/prod/sec-filings/0000320193/000032019325000079/aapl-20250927.htm",
    "https://cdn.yahoofinance.com.evil.test/prod/sec-filings/0000320193/000032019325000079/aapl-20250927.htm",
    "https://user:pw@cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019325000079/aapl-20250927.htm",
    "https://cdn.yahoofinance.com:8443/prod/sec-filings/0000320193/000032019325000079/aapl-20250927.htm",
    "https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019325000079/../secret.htm",
    "https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019325000079/aapl-20250927.htm#part2",
    "https://cdn.yahoofinance.com/prod/sec-filings/0000320193/000032019325000079/aapl-20250927.htm?x=1",
    "https://cdn.yahoofinance.com/prod/sec-filings/320193/000032019325000079/aapl-20250927.htm",
    "https://www.sec.gov/Archives/edgar/data/320193/000032019325000079/",
    "https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK=320193",
    "https://finance.yahoo.com/sec-filing/AAPL/0000320193-25-000079_320193",
    "file:///etc/passwd",
], ids=["http", "other-host", "suffix-host", "credentials", "port", "dot-dot", "fragment", "query", "short-cik", "folder", "edgar-search",
        "yahoo-page", "file"])
def test_any_other_url_is_refused_as_invalid(url):
    with pytest.raises(Invalid):
        locate(url)


# ---- fetch ---------------------------------------------------------------------------------------------------------------

class Server:
    """Answers each path from `routes`: a list of responses served in turn, the last repeated; counts requests per path."""

    def __init__(self):
        self.routes, self.hits = {}, {}
        server = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                server.hits[self.path] = server.hits.get(self.path, 0) + 1
                answers = server.routes[self.path]
                answer = answers[min(server.hits[self.path], len(answers)) - 1]
                if answer.get("delay"):
                    time.sleep(answer["delay"])
                if answer.get("drop"):
                    self.close_connection = True
                    self.connection.shutdown(2)
                    return
                body = answer.get("body", b"")
                self.send_response(answer.get("status", 200))
                for name, value in answer.get("headers", {}).items():
                    self.send_header(name, value)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def located(self, path, *answers):
        self.routes[path] = list(answers)
        return Located(ARCHIVE, f"http://127.0.0.1:{self.httpd.server_port}{path}")


@pytest.fixture
def server():
    running = Server()
    yield running
    running.httpd.shutdown()


def test_a_200_returns_the_bytes_as_the_archive_document_with_its_content_type(server):
    fetched = fetch(server.located("/a.htm", {"body": b"<p>Hello</p>", "headers": {"Content-Type": "text/html; charset=utf-8"}}), 5)
    assert (fetched.body, fetched.url, fetched.content_type) == (b"<p>Hello</p>", ARCHIVE, "text/html; charset=utf-8")


def test_a_redirect_is_not_followed_and_is_upstream(server):
    server.located("/elsewhere.htm", {"body": b"<p>moved</p>"})
    with pytest.raises(Failure) as error:
        fetch(server.located("/a.htm", {"status": 302, "headers": {"Location": "/elsewhere.htm"}}), 5)
    assert error.value.code == "upstream" and server.hits == {"/a.htm": 1}


def test_a_404_is_not_found_without_a_retry(server):
    with pytest.raises(Failure) as error:
        fetch(server.located("/a.htm", {"status": 404}), 5)
    assert error.value.code == "not_found" and server.hits["/a.htm"] == 1


@pytest.mark.parametrize("status", [403, 429])
def test_a_refusal_is_upstream_without_a_retry(server, status):
    with pytest.raises(Failure) as error:
        fetch(server.located("/a.htm", {"status": status}), 5)
    assert error.value.code == "upstream" and server.hits["/a.htm"] == 1


def test_a_server_fault_is_retried_once_and_the_second_answer_counts(server):
    fetched = fetch(server.located("/a.htm", {"status": 503}, {"body": b"<p>ok</p>"}), 5)
    assert fetched.body == b"<p>ok</p>" and server.hits["/a.htm"] == 2


def test_a_server_fault_twice_is_upstream_after_two_attempts(server):
    with pytest.raises(Failure) as error:
        fetch(server.located("/a.htm", {"status": 500}), 5)
    assert error.value.code == "upstream" and server.hits["/a.htm"] == 2 and "2 attempts" in str(error.value)


def test_a_dropped_connection_is_retried_once(server):
    fetched = fetch(server.located("/a.htm", {"drop": True}, {"body": b"<p>ok</p>"}), 5)
    assert fetched.body == b"<p>ok</p>" and server.hits["/a.htm"] == 2


def test_the_deadline_covers_the_retry(server):
    started = time.monotonic()
    with pytest.raises(Failure) as error:
        fetch(server.located("/a.htm", {"delay": 0.6, "status": 503}), 1.0)
    assert error.value.code == "upstream" and time.monotonic() - started < 1.9


def test_the_deadline_bounds_a_body_that_keeps_dripping(server):
    """Each byte arrives before the socket would time out, so only a deadline over the whole read stops it."""
    class Drip(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self.send_response(200)
            self.send_header("Content-Length", "100")
            self.end_headers()
            for _ in range(100):
                self.wfile.write(b"x")
                self.wfile.flush()
                time.sleep(0.05)

    drip = ThreadingHTTPServer(("127.0.0.1", 0), Drip)
    threading.Thread(target=drip.serve_forever, daemon=True).start()
    started = time.monotonic()
    try:
        with pytest.raises(Failure) as error:
            fetch(Located(ARCHIVE, f"http://127.0.0.1:{drip.server_port}/a.htm"), 0.5)
    finally:
        drip.shutdown()
    assert error.value.code == "upstream" and time.monotonic() - started < 1.5


@pytest.mark.parametrize("url", ["https://[invalid/path", "https://cdn.yahoofinance.com:99999/prod/sec-filings/0000320193/000032019325000079/a.htm"])
def test_a_url_that_does_not_parse_is_invalid(url):
    with pytest.raises(Invalid):
        locate(url)


@pytest.mark.parametrize("url", [
    "https://u:p@s3.amazonaws.com/finance-pri-uw2/sec-filings/0000320193/000032019325000079/Financial_Report.xlsx",
    "https://s3.amazonaws.com/finance-pri-uw2/sec-filings/0000320193/000032019325000079/Financial_Report.xlsx#x",
    "https://s3.amazonaws.com/finance-pri-uw2/sec-filings/../x/Financial_Report.xlsx",
    "http://s3.amazonaws.com/finance-pri-uw2/sec-filings/0000320193/000032019325000079/Financial_Report.xlsx",
], ids=["credentials", "fragment", "dot-dot", "http"])
def test_a_malformed_spreadsheet_url_is_invalid_not_unsupported(url):
    with pytest.raises(Invalid):
        locate(url)
