"""Recording transport for scenarios/invest/record_yahoo.py: every Yahoo request passes through and is appended to $INVEST_RECORD."""
import json
import os
from urllib.parse import parse_qs, urlsplit

from curl_cffi import requests
import yfinance as yf

LOG = os.environ["INVEST_RECORD"]
yf.set_tz_cache_location(os.environ["YF_TEST_CACHE"])  # a cold cache, as each test run has, so every request a replay makes is recorded
original = requests.Session.request


def request(self, method, url, **kwargs):
    response = original(self, method, url, **kwargs)
    parsed = urlsplit(url)
    if parsed.netloc != "fc.yahoo.com" and not parsed.path.endswith("/getcrumb"):
        params = {key: values[-1] for key, values in parse_qs(parsed.query).items()}
        params.update({k: v for k, v in (kwargs.get("params") or {}).items()})
        body = kwargs.get("json") or (json.loads(kwargs["data"]) if isinstance(kwargs.get("data"), str) else None)
        entry = {"method": method, "host": parsed.netloc, "path": parsed.path, "params": {k: str(v) for k, v in params.items()}, "body": body,
                 "status": response.status_code, "content_type": response.headers.get("content-type", ""), "text": response.text}
        with open(LOG, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return response


requests.Session.request = request
