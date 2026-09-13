"""Curl transport and durable observations; no provider interpretation here."""
import json
import os
from pathlib import Path
import re
import sqlite3
import subprocess
import tempfile
from datetime import datetime, timezone
from urllib.parse import urlsplit, urljoin
from uuid import uuid4


class Failure(Exception):
    def __init__(self, code, message, fix):
        self.detail = dict(code=code, message=message, fix=fix)
        super().__init__(message)


def now():
    return datetime.now(timezone.utc).isoformat()


def validate_url(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.netloc not in ('finviz.com', 'www.finviz.com') or parts.fragment:
        raise Failure('unsupported_url', 'Only HTTPS Finviz read URLs are supported.', 'Use a Finviz data URL without credentials, port or fragment.')
    path = parts.path
    pages = ('/', '/screener', '/screener.ashx', '/stock', '/quote.ashx', '/groups.ashx', '/map.ashx', '/bubbles.ashx', '/news', '/news.ashx', '/insidertrading', '/insidertrading.ashx', '/futures.ashx', '/forex.ashx', '/crypto.ashx')
    apis = ('suggestions', 'statement', 'quote', 'groups_perf', 'map_perf', 'map_perf_screener', 'map_perf_groups', 'map_sparklines', 'maps/counts', 'bubbles', 'futures_all', 'futures_perf', 'forex_all', 'forex_perf', 'crypto_all', 'crypto_perf')
    allowed = path in pages or path in tuple('/api/'+x for x in apis)
    allowed |= bool(re.fullmatch(r'/news/\d+/[\w-]+', path))
    allowed |= bool(re.fullmatch(r'/(?:api/)?calendar/(?:earnings(?:/season-preview)?|dividends|economic(?:/detail/[\w.-]+)?)', path))
    allowed |= bool(re.fullmatch(r'/api/stocks-why-moving/by-id/\d+', path))
    allowed |= bool(re.fullmatch(r'/assets/dist/[\w.-]+\.js', path))
    if not allowed:
        raise Failure('unsupported_route', 'This route is outside the read interface.', 'Use --help for supported queries; external articles and filings remain links.')
    return url


class Store:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path)
        self.db.execute('CREATE TABLE IF NOT EXISTS observations (id TEXT PRIMARY KEY, envelope TEXT NOT NULL, raw BLOB NOT NULL)')
        self.db.execute('CREATE TABLE IF NOT EXISTS collections (id TEXT PRIMARY KEY, state TEXT NOT NULL)')

    def save(self, result, raw):
        with self.db:
            self.db.execute('INSERT INTO observations VALUES (?,?,?)', (result['id'], json.dumps(result, ensure_ascii=False), raw))

    def get(self, key, raw=False):
        row = self.db.execute('SELECT envelope,raw FROM observations WHERE id=?', (key,)).fetchone()
        if not row:
            raise Failure('unknown_result', 'No saved observation with this ID.', 'Use the same --store used for the original query.')
        return row[1] if raw else json.loads(row[0])

    def collection(self, key, state=None):
        if state is not None:
            with self.db:
                self.db.execute('INSERT OR REPLACE INTO collections VALUES (?,?)', (key, json.dumps(state)))
            return state
        row = self.db.execute('SELECT state FROM collections WHERE id=?', (key,)).fetchone()
        if not row:
            raise Failure('unknown_collection', 'Collection not found.', 'Start collect with a saved result ID.')
        return json.loads(row[0])


def fetch(url, args, store, extract):
    validate_url(url)
    origin = url
    chain = []
    for _ in range(6):
        with tempfile.TemporaryDirectory(prefix='finviz-') as tmp:
            body, headers = Path(tmp)/'body', Path(tmp)/'headers'
            try:
                proc = subprocess.run(['curl', '-q', '--silent', '--show-error', '--proto', '=https', '--connect-timeout', str(args.connect_timeout), '--max-time', str(args.timeout), '--max-filesize', str(args.max_bytes), '--dump-header', str(headers), '--output', str(body), '--write-out', '%{http_code}', url], capture_output=True, timeout=args.timeout+5)
            except FileNotFoundError:
                raise Failure('missing_curl', 'curl is not installed.', 'Install curl 8.4 or newer.')
            except subprocess.TimeoutExpired:
                proc = subprocess.CompletedProcess([], 28, b'000', b'Process exceeded request timeout')
            raw = body.read_bytes() if body.exists() else b''
            header_text = headers.read_text(errors='replace') if headers.exists() else ''
            fields = {}
            for line in header_text.splitlines():
                if line.lower().startswith('http/'):
                    fields = {}
                elif ':' in line:
                    k, v = line.split(':', 1)
                    fields[k.lower()] = v.strip()
            status = int(proc.stdout[-3:]) if proc.stdout[-3:].isdigit() else 0
            result = dict(id=uuid4().hex, status='ok', source=dict(url=url, requested_url=origin, observed_at=now(), http_status=status, received_complete=proc.returncode == 0, headers=fields, redirects=chain.copy()), data=None, conditions={}, coverage=dict(received=None, shown=None, source_total=None, exhaustive=False), continuation=None, errors=[])
            try:
                if proc.returncode:
                    raise Failure('transport', f'curl exited {proc.returncode}: {proc.stderr.decode(errors="replace")[:400]}', 'Inspect saved raw bytes; retry as a new observation after resolving connectivity or limits.')
                if status in (301, 302, 303, 307, 308):
                    validate_url(urljoin(url, fields.get('location', '')))
                elif status in (401, 403, 429):
                    raise Failure('access_restricted', f'HTTP {status}; Retry-After={fields.get("retry-after", "unspecified")}', 'Respect Retry-After when present. Do not bypass access controls.')
                elif status < 200 or status >= 300:
                    raise Failure('http_error', f'HTTP {status}', 'Check the source URL and supported query; the raw response is saved.')
                else:
                    extract(result, raw)
            except (Failure, ValueError, TypeError, KeyError) as exc:
                result['status'] = 'partial' if result['data'] is not None else 'error'
                result['errors'].append(exc.detail if isinstance(exc, Failure) else dict(code='parse_error', message=str(exc), fix='Inspect the saved raw response; the provider structure may have changed.'))
            result['store'] = str(store.path)
            store.save(result, raw)
            if status not in (301, 302, 303, 307, 308) or result['errors']:
                return result
            chain.append(dict(id=result['id'], url=url, status=status))
            location = fields.get('location')
            if not location:
                return result
            url = urljoin(url, location)
    raise Failure('redirect_limit', 'More than five redirects; responses were saved.', 'Inspect the redirect source; do not follow an unbounded chain.')
