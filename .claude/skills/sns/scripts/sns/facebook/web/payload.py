"""Facebook's server-rendered page payload: the query results a facebook.com page preloads into its own HTML.

A screen's HTML carries script blobs (`<script type="application/json" …>{"require": …}</script>`); the results of the
queries the page preloads arrive in them as RelayPrefetchedStreamCache "next" calls, each wrapping one result
({data}, or a deferred {label, path, data}) in a __bbox. Those results are the chunks a GraphQL answer would be, so the
records code reads them the same way (observed in the recon captures, 2026-11-16).
"""
import json
import re

_SCRIPT = re.compile(r'<script\b[^>]*\btype="application/json"[^>]*>')


def _blobs(html):
    decoder = json.JSONDecoder()
    for match in _SCRIPT.finditer(html):
        try:
            blob, _ = decoder.raw_decode(html, match.end())
        except (ValueError, RecursionError):
            continue  # a blob this reader cannot decode carries nothing it reads
        yield blob


def _results(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, list):
            if (len(item) >= 4 and item[0] == 'RelayPrefetchedStreamCache' and item[1] == 'next'
                    and isinstance(item[3], list) and len(item[3]) >= 2 and isinstance(item[3][1], dict)):
                result = (item[3][1].get('__bbox') or {}).get('result')
                if isinstance(result, dict):
                    yield result
                continue
            stack.extend(reversed(item))
        elif isinstance(item, dict):
            stack.extend(reversed(list(item.values())))


def chunks(html):
    """The preloaded query results of a page's HTML, in page order, as GraphQL chunks."""
    return [result for blob in _blobs(html) for result in _results(blob)]
