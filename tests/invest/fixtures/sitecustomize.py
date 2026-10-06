"""Test-process-only transport: every Yahoo request is answered from $YF_HTTP_FIXTURE, and anything it does not hold exits 97.

Routes match on path and on the parameters and body fields they name, first match wins, so a fixture recorded by scenarios/invest/record_yahoo.py replays without its volatile parameters. Each request is appended to $YF_HTTP_LOG when set, so a test can count what the CLI actually asked for. $YF_FIXTURE_NOW fixes the process clock (time.time), so a test can move the observation time while the session data stays the same.
"""
import datetime as dt
import json
import os
import sys
import time
from urllib.parse import parse_qs, urlsplit

import yfinance as yf
from curl_cffi import requests

routes = json.loads(open(os.environ["YF_HTTP_FIXTURE"]).read())
yf.set_tz_cache_location(os.environ["YF_TEST_CACHE"])
LOG = os.environ.get("YF_HTTP_LOG")


def request(self, method, url, **kwargs):
    parsed = urlsplit(url)
    if parsed.netloc == "fc.yahoo.com":
        self.cookies.set("A3", "fixture-cookie", domain=".yahoo.com")
        for cookie in self.cookies.jar:
            cookie.expires = 2000000000
        payload = {"text": ""}
    elif parsed.path.endswith("/getcrumb"):
        payload = {"text": "fixture-crumb"}
    else:
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        params.update(kwargs.get("params") or {})
        body = kwargs.get("json") or (json.loads(kwargs["data"]) if isinstance(kwargs.get("data"), str) else {})
        if LOG:
            with open(LOG, "a") as handle:
                handle.write(json.dumps({"method": method, "path": parsed.path, "params": {k: str(v) for k, v in params.items()}, "body": body or None}) + "\n")
        payload = next((r for r in routes if r["path"] in parsed.path and all(str(params.get(k)) == str(v) for k, v in r.get("params", {}).items())
                        and all(body.get(k) == v for k, v in (r.get("body") or {}).items())), None)
        if payload is None:
            sys.stderr.write(f"UNEXPECTED NETWORK {method} {url} params={params} body={kwargs.get('json')}\n")
            raise SystemExit(97)
    if payload.get("delay"):
        time.sleep(payload["delay"])
    if payload.get("touch"):  # something else creates this file while the request is in flight
        with open(payload["touch"], "w") as handle:
            handle.write("arrived first\n")
    response = requests.Response()
    response.status_code = payload.get("status", 200)
    response.ok = 200 <= response.status_code < 400  # a real Response sets these; raise_for_status reads ok
    response.reason = "OK" if response.ok else "Error"
    response.url = url
    response.headers = {"content-type": "text/html" if "text" in payload else "application/json"}
    response.content = payload.get("text", json.dumps(payload.get("json", {}))).encode()
    return response


requests.Session.request = request

FROZEN = os.environ.get("YF_FIXTURE_NOW")
if FROZEN:
    # The process clock, the one time source the skill's observation times and timing verdicts read; nothing inside the skill is replaced.
    _frozen = dt.datetime.fromisoformat(FROZEN).timestamp()
    time.time = lambda: _frozen
