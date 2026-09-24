"""curl transport and the Finviz read-URL boundary; no page interpretation and no storage here."""

import argparse
import json
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import tempfile
from urllib.parse import urljoin, urlsplit
from uuid import uuid4


class Failure(Exception):
    """An error with a stable code and a recovery instruction; may carry the observation it happened on."""

    def __init__(self, code, message, fix, observation=None):
        super().__init__(message)
        self.code, self.message, self.fix, self.observation = code, str(message), fix, observation

    def info(self):
        return {"code": self.code, "message": self.message, "fix": self.fix}

    def record(self):
        """Persist the failure on its observation even when a caller returns a partial result."""
        if self.observation is not None:
            self.observation.result.update(status="error", error=self.info())


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON object key: " + key)
        result[key] = value
    return result


PAGES = {
    "/", "/screener", "/screener.ashx", "/stock", "/quote", "/quote.ashx", "/groups", "/groups.ashx", "/map", "/map.ashx",
    "/bubbles", "/bubbles.ashx", "/news", "/news.ashx", "/insidertrading", "/insidertrading.ashx", "/futures",
    "/futures.ashx", "/forex", "/forex.ashx", "/crypto", "/crypto.ashx",
}
APIS = {
    "suggestions", "statement", "quote", "groups_perf", "map_perf", "map_perf_screener", "map_perf_groups", "bubbles",
    "futures_all", "futures_perf", "forex_all", "forex_perf", "crypto_all", "crypto_perf",
}
ROUTES = (
    r"/news/\d+/[\w-]+",
    r"/(?:api/)?calendar/(?:earnings(?:/season-preview)?|dividends|economic)",
    r"/api/stocks-why-moving/by-id/\d+",
    r"/api/(?:futures|forex|crypto)/performance",
    r"/assets/dist(?:-legacy)?/[\w.-]+\.js",
)


SETTINGS = {"FINVIZ_CONNECT_TIMEOUT": ("connect_timeout", float, 10.0), "FINVIZ_TIMEOUT": ("timeout", float, 60.0), "FINVIZ_MAX_BYTES": ("max_bytes", int, 16 * 1024 * 1024)}


def settings():
    """Transport limits belong to whoever runs the CLI, not to the question: they come from the environment and doctor reports them."""
    values = {}
    for variable, (name, kind, fallback) in SETTINGS.items():
        raw = os.environ.get(variable)
        try:
            values[name] = kind(raw) if raw not in (None, "") else fallback
        except ValueError:
            raise Failure("invalid_argument", variable + " is not a number: " + raw, "Set " + variable + " to a positive number or unset it to use " + str(fallback) + ".")
        if values[name] <= 0:
            raise Failure("invalid_argument", variable + " must be positive.", "Set " + variable + " above zero or unset it to use " + str(fallback) + ".")
    return argparse.Namespace(**values)


def limits_in_force(options):
    return ", ".join(variable + "=" + format(getattr(options, name), "g") for variable, (name, _, _) in SETTINGS.items())


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.netloc not in ("finviz.com", "www.finviz.com") or parts.fragment or parts.port:
        raise Failure("unsupported_url", "Only HTTPS finviz.com read URLs are supported.", "Use a finviz.com data URL without credentials, port or fragment; external articles and SEC filings need their own readers.")
    path = parts.path
    allowed = path in PAGES or (path.startswith("/api/") and path[5:] in APIS) or any(re.fullmatch(r, path) for r in ROUTES)
    if not allowed:
        raise Failure("unsupported_route", "This Finviz route is outside the read interface.", "Use a command from --help or a URL to a screener, stock, groups, map, news, calendar, insider or market page.")
    return url


class Observation:
    """One received response and the result envelope being built from it."""

    def __init__(self, url, requested_url, http_status, headers, raw, redirects, complete):
        self.id = uuid4().hex
        self.url, self.requested_url, self.http_status, self.headers = url, requested_url, http_status, headers
        self.raw, self.redirects, self.complete = raw, redirects, complete
        self.result = {
            "id": self.id,
            "observed_at": now(),
            "source": {"url": url, "requested_url": requested_url, "http_status": http_status, "redirects": redirects, "received_complete": complete, "headers": headers},
            "status": "ok",
            "context": {},
            "collections": {},
        }

    @property
    def text(self):
        return self.raw.decode("utf-8-sig", errors="replace")

    def json(self):
        head = self.text[:4000].lower()
        if head.lstrip().startswith("<") and ("challenge-form" in head or "just a moment" in head):
            raise self.fail("access_restricted", "Finviz returned a verification page instead of data.", "Wait before retrying and do not bypass the verification; the raw page is saved.")
        try:
            return json.loads(self.text, object_pairs_hook=unique_object)
        except ValueError as exc:
            raise Failure("parse_error", "The response is not the JSON this command expects: " + str(exc)[:200], "Read the saved raw response with read ID --raw; the provider structure may have changed.", self)

    def fail(self, code, message, fix):
        return Failure(code, message, fix, self)


def parse_headers(text):
    fields = {}
    for line in text.splitlines():
        if line.lower().startswith("http/"):
            fields = {}
        elif ":" in line:
            key, value = line.split(":", 1)
            fields[key.strip().lower()] = value.strip()
    return fields


def fetch(url, options, keep=None):
    """GET a Finviz URL through curl, following up to five same-site redirects; raise Failure carrying the observation on any non-2xx outcome. Every response received on the way, including a redirect's own, is handed to `keep` so the envelope's promise that received responses are saved holds for the whole chain."""
    validate_url(url)
    origin, redirects = url, []
    for _ in range(6):
        with tempfile.TemporaryDirectory(prefix="finviz-") as tmp:
            body, header_file = Path(tmp) / "body", Path(tmp) / "headers"
            command = [
                "curl", "-q", "--silent", "--show-error", "--proto", "=https", "--connect-timeout", str(options.connect_timeout),
                "--max-time", str(options.timeout), "--max-filesize", str(options.max_bytes), "--dump-header", str(header_file),
                "--output", str(body), "--write-out", "%{http_code}", url,
            ]
            try:
                proc = subprocess.run(command, capture_output=True, timeout=options.timeout + 5)
            except FileNotFoundError:
                raise Failure("missing_curl", "curl is not installed.", "Install curl 8.4 or newer; doctor reports the detected version.")
            except subprocess.TimeoutExpired:
                proc = subprocess.CompletedProcess(command, 28, b"000", b"the request exceeded FINVIZ_TIMEOUT")
            raw = body.read_bytes() if body.exists() else b""
            headers = parse_headers(header_file.read_text(errors="replace")) if header_file.exists() else {}
            status = int(proc.stdout[-3:]) if proc.stdout[-3:].isdigit() else 0
            obs = Observation(url, origin, status, headers, raw, list(redirects), proc.returncode == 0)
        if proc.returncode:
            raise obs.fail("transport", "curl exited " + str(proc.returncode) + ": " + proc.stderr.decode(errors="replace").strip()[:300], "Retry after checking connectivity. This request ran with " + limits_in_force(options) + "; raise the one that stopped it in the environment. A partial body, if any, is saved.")
        if status in (301, 302, 303, 307, 308):
            location = urljoin(url, headers.get("location", ""))
            try:
                validate_url(location)
            except Failure as exc:
                raise Failure(exc.code, "Redirect to " + location + " refused: " + exc.message, exc.fix, obs)
            redirects.append({"url": url, "http_status": status, "id": obs.id})
            if keep is not None:
                keep(obs)
            url = location
            continue
        if status in (401, 403, 429):
            raise obs.fail("access_restricted", "HTTP " + str(status) + "; Retry-After=" + headers.get("retry-after", "unspecified"), "Wait for Retry-After when present and do not bypass access controls; this data may need a Finviz account.")
        if status < 200 or status >= 300:
            raise obs.fail("http_error", "HTTP " + str(status), "Check the ticker or identifier; a 404 usually means the security or page does not exist. The raw response is saved.")
        return obs
    raise Failure("redirect_limit", "More than five redirects.", "Inspect the URL; the chain is not followed further.", obs)
