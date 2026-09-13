"""Read-only Finviz CLI."""
import argparse
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlencode

from runtime import Failure, Store, fetch
from extract import parse


def parser():
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--json', action='store_true', help='Emit structured JSON instead of compact text.')
    common.add_argument('--store', default=os.environ.get('FINVIZ_STORE', str(Path.home()/'.cache/finviz-skill/observations.sqlite3')), help='SQLite observation store; reuse this location when reading saved IDs.')
    common.add_argument('--connect-timeout', type=float, default=10, help='Connection timeout in seconds.')
    common.add_argument('--timeout', type=float, default=60, help='Per-request timeout in seconds.')
    common.add_argument('--max-bytes', type=int, default=16*1024*1024, help='Maximum bytes per response; incomplete responses are marked.')
    p = argparse.ArgumentParser(description='Explore public Finviz data. Commands describe inputs; schema explains results.', formatter_class=argparse.RawTextHelpFormatter)
    sub = p.add_subparsers(dest='command', required=True)
    lookup = sub.add_parser('lookup', parents=[common], help='Find security candidates by name or ticker.')
    lookup.add_argument('query', help='Company name or ticker.')
    read = sub.add_parser('read', parents=[common], help='Read a saved observation without fetching the network.')
    read.add_argument('id', help='Saved observation ID.')
    read.add_argument('--pointer', default='', help='JSON Pointer inside the saved observation, e.g. /data/results/0.')
    read.add_argument('--raw', action='store_true', help='Read the original response text, including failed extraction.')
    screen = sub.add_parser('screen', parents=[common], help='Screen stocks using current Finviz conditions; catalog lists filter values.')
    screen.add_argument('--filter', default=None, help='Comma-separated native filters, e.g. sec_technology,cap_largeover; discover with catalog.')
    screen.add_argument('--view', default='111', help='Finviz view identifier; use catalog for current choices.')
    screen.add_argument('--columns', help='Comma-separated native column indices for the custom view.')
    screen.add_argument('--sort', help='Native sort key, prefix - for descending; use --sort=-marketcap.')
    screen.add_argument('--start', type=int, default=1, help='One-based row offset; follow returned continuation instead of guessing.')
    stock = sub.add_parser('stock', parents=[common], help='Read a company or ETF, preserving source metrics and initial data.')
    stock.add_argument('ticker', help='Resolved ticker from lookup.')
    stock.add_argument('--section', choices=['overview','earnings','dividends','revenue','forecast','short-interest','options','filings','income','balance','cashflow'], default='overview', help='Dataset to read; overview also includes available ETF and ownership data.')
    stock.add_argument('--expiry', help='Options expiration YYYY-MM-DD from returned expiries.')
    stock.add_argument('--page', type=int, help='Filings page, one-based.')
    stock.add_argument('--sort', help='Filings sort key from returned controls.')
    stock.add_argument('--period', choices=['annual','quarterly'], default='annual', help='Financial statement period; returned source periods remain authoritative.')
    prices = sub.add_parser('prices', parents=[common], help='Read source price bars; date and price array lengths are validated.')
    prices.add_argument('ticker', help='Ticker or market instrument identifier.')
    prices.add_argument('--instrument', default='stock', choices=['stock','futures','forex','crypto'], help='Instrument family.')
    prices.add_argument('--timeframe', default='d', help='Source timeframe identifier, e.g. d, w, m.')
    prices.add_argument('--bars', type=int, default=30, help='Requested number of bars; response coverage may differ.')
    calendar = sub.add_parser('calendar', parents=[common], help='Read earnings, dividend and economic events with source dates intact.')
    calendar.add_argument('kind', choices=['earnings','dividends','economic','season-preview'], help='Calendar dataset.')
    calendar.add_argument('--date', help='Starting date YYYY-MM-DD; application is confirmed only with response evidence.')
    calendar.add_argument('--page', type=int, default=1, help='One-based page.')
    calendar.add_argument('--sort', default='earningsDate', help='Source ordering key.')
    return p


def extract(result, raw):
    result['data'] = json.loads(raw)


def run(args):
    store = Store(args.store)
    if args.command == 'read':
        data = store.get(args.id, raw=args.raw)
        if args.raw:
            data = data.decode('utf-8', errors='replace')
        else:
            for token in args.pointer.split('/')[1:]:
                token = token.replace('~1', '/').replace('~0', '~')
                data = data[int(token)] if isinstance(data, list) else data[token]
        return dict(id=args.id, status='ok', data=data)
    if args.command == 'calendar':
        path = '/calendar/earnings/season-preview' if args.kind=='season-preview' else '/api/calendar/'+args.kind
        query = {'dateFrom':args.date,'page':args.page,'sort':args.sort}
        url = 'https://finviz.com'+path+'?'+urlencode({k:v for k,v in query.items() if v is not None})
    elif args.command == 'screen':
        query = {'ft': '4', 'v':args.view, 'f':args.filter, 'c':args.columns, 'o':args.sort, 'r':args.start}
        url = 'https://finviz.com/screener?'+urlencode({k:v for k,v in query.items() if v is not None})
    elif args.command == 'prices':
        url = 'https://finviz.com/api/quote?'+urlencode({'instrument':args.instrument,'ticker':args.ticker,'timeframe':args.timeframe,'barsCount':args.bars})
    elif args.command == 'stock' and args.section in ('income','balance','cashflow'):
        kind = {'income':'I','balance':'B','cashflow':'C'}[args.section]+('A' if args.period=='annual' else 'Q')
        url = 'https://finviz.com/api/statement?'+urlencode({'t':args.ticker,'so':'F','s':kind})
    elif args.command == 'stock':
        section = {'overview':'c','earnings':'ea','dividends':'dv','revenue':'rv','forecast':'fc','short-interest':'si','options':'oc','filings':'lf'}[args.section]
        query = {'t':args.ticker,'ty':section,'e':args.expiry,'page':args.page,'sort':args.sort}
        url = 'https://finviz.com/stock?'+urlencode({k:v for k,v in query.items() if v is not None})
    else:
        url = 'https://finviz.com/api/suggestions?'+urlencode({'input':args.query})
    return fetch(url, args, store, parse)


def main():
    args = parser().parse_args()
    try:
        if args.timeout <= 0 or args.connect_timeout <= 0 or args.max_bytes <= 0:
            raise Failure('invalid_argument', 'Limits must be positive.', 'Use positive timeout and byte limits.')
        result = run(args)
    except (Failure, ValueError, KeyError, IndexError, OSError) as exc:
        result = dict(status='error', errors=[exc.detail if isinstance(exc, Failure) else dict(code='invalid_input', message=str(exc), fix='Check the command help and returned IDs or pointers.')])
    print(json.dumps(result, ensure_ascii=False, indent=2 if not args.json else None))
    return 1 if result['status'] == 'error' else 0


if __name__ == '__main__':
    sys.exit(main())
