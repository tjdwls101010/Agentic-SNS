"""Learning a query's current id from Threads itself, when the stored one is refused or a query is unknown.

The cheapest path, measured: one GET of the screen that uses the query. Its document preloads the screen's first
queries (id and variables, provider values included) and names the JavaScript bundles of the screen; those come from
the static CDN (static.cdninstagram.com, cookie-less, not a Threads request) and define every query module the
screen can send: `<Name>_threadsRelayOperation` exports the id, `<Name>.threads.graphql` names the providers, the
argument names, the root field and whether it is a query, and a preloadable query may have only
`<Name>$Parameters.threads` (its id, kind and providers). A renamed query is found among those definitions by what
stays when Meta renames it (its argument names and root field), and only when exactly one candidate fits.
"""
import hashlib
import json
import os
import re
import urllib.request
from pathlib import Path
from html.parser import HTMLParser

CDN = re.compile(r'https://static\.cdninstagram\.com/rsrc\.php/[^"\'\s<>]+?\.js[^"\'\s<>]*')
MAX_BUNDLES = 600
_TIMEOUT = 20


class _Scripts(HTMLParser):
    def __init__(self, html):
        super().__init__(convert_charrefs=False)
        self.active, self.buffer, self.documents = False, [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        if tag == 'script':
            self.active = dict(attrs).get('type') == 'application/json'
            self.buffer = []

    def handle_data(self, data):
        if self.active:
            self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == 'script' and self.active:
            try:
                self.documents.append(json.loads(''.join(self.buffer)))
            except ValueError:
                pass
            self.active = False


def preloaders(html):
    """{query name: {doc_id, variables}} the document preloads (adp_<Name>RelayPreloader_* entries)."""
    found = {}

    def walk(value):
        if isinstance(value, dict):
            match = re.fullmatch(r'adp_(.+?)RelayPreloader_.*', str(value.get('preloaderID', '')))
            if match and str(value.get('queryID', '')).isdigit() and isinstance(value.get('variables'), dict):
                name = value.get('queryName') or match[1]
                found.setdefault(name, {'doc_id': str(value['queryID']), 'variables': value['variables']})
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for document in _Scripts(html).documents:
        walk(document)
    return found


def provider_values(variables):
    """The relay provider values among a preloader's variables; only booleans, integers and constant strings."""
    return {key: value for key, value in variables.items()
            if re.fullmatch(r'__relay_internal__pv__[A-Za-z0-9_]+relayprovider', key)
            and (type(value) in (bool, int) or (isinstance(value, str) and re.fullmatch(r'[A-Z_]{1,80}', value)))}


def provider_variable(module):
    """The variable name a provider module fills: X.relayprovider → __relay_internal__pv__Xrelayprovider."""
    return '__relay_internal__pv__' + module[:-len('.relayprovider')] + 'relayprovider'


def bundle_urls(html):
    return list(dict.fromkeys(CDN.findall(html.replace('\\/', '/'))))[:MAX_BUNDLES]


def fetch_bundle(url):
    """One static bundle from the CDN, without cookies. THREADS_CDN_DIR (tests) serves bundles from files named by the
    SHA-1 of their URL instead."""
    local = os.environ.get('THREADS_CDN_DIR')
    if local:
        return (Path(local) / (hashlib.sha1(url.encode()).hexdigest() + '.js')).read_text(errors='replace')
    request = urllib.request.Request(url, headers={'user-agent': 'Mozilla/5.0', 'accept': '*/*'})
    with urllib.request.urlopen(request, timeout=_TIMEOUT) as response:
        return response.read().decode('utf-8', errors='replace')


def definitions(text):
    """{query name: {doc_id?, providers, args, root, kind}} defined in one bundle's text."""
    found = {}
    for match in re.finditer(r'__d\("([A-Za-z0-9_]+)_threadsRelayOperation",\[\],\(function\([^)]*\)\{[^}]*?'
                             r'[a-z]\.exports="(\d+)"', text):
        found.setdefault(match[1], {})['doc_id'] = match[2]
    for match in re.finditer(r'__d\("([A-Za-z0-9_]+)\.threads\.graphql",', text):
        start = match.start()
        end = text.find('__d("', start + 10)
        segment = text[start:end if end > 0 else None]
        entry = found.setdefault(match[1], {})
        entry['providers'] = sorted(set(re.findall(r':n\("([A-Za-z0-9_]+\.relayprovider)"\)', segment)))
        operation = segment.find('operation:{argumentDefinitions:')
        head = segment[:operation] if operation > 0 else segment
        entry['args'] = sorted({a for a in re.findall(r'kind:"LocalArgument",name:"([A-Za-z0-9_]+)"', head)
                                if not a.startswith('__relay')})
        root = re.search(r'root_field_name:\["([A-Za-z0-9_]+)"', segment)
        entry['root'] = root[1] if root else None
        kind = re.search(r'operationKind:"([a-z]+)"', segment)
        entry['kind'] = kind[1] if kind else None
    # A preloadable query can be defined only by its parameters: id, kind and providers, no arguments or root field.
    for match in re.finditer(r'__d\("([A-Za-z0-9_]+)\$Parameters\.threads",', text):
        end = text.find('__d("', match.start() + 10)
        segment = text[match.start():end if end > 0 else None]
        doc_id = re.search(r'params:\{id:"(\d+)"', segment)
        kind = re.search(r'operationKind:"([a-z]+)"', segment)
        if not doc_id or not kind:
            continue
        providers = sorted(set(re.findall(r':n\("([A-Za-z0-9_]+\.relayprovider)"\)', segment)))
        if match[1] in found:  # this bundle also defines it in full or by its id: those win, this fills the gaps
            entry = found[match[1]]
            entry.setdefault('doc_id', doc_id[1])
            entry.setdefault('kind', kind[1])
            entry.setdefault('providers', providers)
        else:
            found[match[1]] = {'doc_id': doc_id[1], 'kind': kind[1], 'providers': providers, 'parameters_only': True}
    return found


def search(html, names, *, fetch=fetch_bundle, stop_when=None):
    """Definitions of `names` (and of every query, for finding a successor) across the document's bundles.

    Stops early once every name has its id and definition, unless stop_when says otherwise."""
    catalog = {}
    for url in bundle_urls(html):
        try:
            found = definitions(fetch(url))
        except OSError:
            continue
        for name, entry in found.items():
            known = catalog.get(name, {})
            if entry.get('parameters_only'):
                if not known or known.get('parameters_only'):
                    catalog[name] = entry  # a fallback until a full definition turns up in any bundle
            else:
                catalog[name] = {**({} if known.get('parameters_only') else known), **entry}
        # parameters alone do not end the search: a later bundle may define the query in full, with its current id
        done = all(catalog.get(name, {}).get('doc_id') and catalog.get(name, {}).get('kind')
                   and not catalog.get(name, {}).get('parameters_only') for name in names)
        if done and (stop_when is None or stop_when(catalog)):
            break
    return catalog


def successor(lost, catalog, claimed):
    """The one query in `catalog` that fits lost {args, root} and no claimed name does; None when not exactly one.

    Fits: a query (never a mutation), named …Query, same root field, and its argument names are the lost query's."""
    if not lost.get('root') or not lost.get('args'):
        return None  # without a root field and argument names to match, no candidate is certain
    fits = [name for name, entry in catalog.items()
            if name not in claimed and re.fullmatch(r'[A-Za-z0-9_]+Query', name) and 'Mutation' not in name
            and entry.get('kind') == 'query' and entry.get('doc_id') and entry.get('root') == lost.get('root')
            and set(entry.get('args') or []) == set(lost.get('args') or [])]
    return fits[0] if len(fits) == 1 else None
