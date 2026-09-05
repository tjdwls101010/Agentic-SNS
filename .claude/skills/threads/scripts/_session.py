"""Fresh route credentials and balanced JSON preloaders; credentials stay in memory."""
import json
import re
from dataclasses import dataclass
from html.parser import HTMLParser

from ._errors import ThreadsError


class Scripts(HTMLParser):
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
    found = {}
    def walk(value):
        if isinstance(value, dict):
            name = re.fullmatch(r'adp_(.+?)RelayPreloader_.*', str(value.get('preloaderID', '')))
            if name and str(value.get('queryID', '')).isdigit() and isinstance(value.get('variables'), dict):
                entry = dict(name=value.get('queryName') or name[1], doc_id=str(value['queryID']), variables=value['variables'])
                found[(entry['name'], json.dumps(value['variables'], sort_keys=True))] = entry
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    for document in Scripts(html).documents:
        walk(document)
    return list(found.values())


@dataclass
class Session:
    csrf: str
    actor: str
    viewer: str
    preloaders: list

    @classmethod
    def from_html(cls, html):
        def field(name):
            match = re.search(r'"' + name + r'"\s*:\s*("(?:\\.|[^"\\])*")', html)
            return json.loads(match[1]) if match else ''
        csrf, actor, viewer = (field(key) for key in ('csrf_token', 'NON_FACEBOOK_USER_ID', 'username'))
        if not (csrf and actor and actor != '0' and viewer):
            if 'DTSGInitialData' in html and not any((csrf, actor, viewer)):
                raise ThreadsError(4, 'Threads login is required.')
            raise ThreadsError(6, 'Route HTML does not establish a logged-in session.',
                               'Run doctor to check Aside and the route headers; a shell alone does not prove logout.')
        loaders = preloaders(html)
        if not loaders and '"__bbox"' not in html:
            raise ThreadsError(6, 'Authenticated HTML has no Relay payload structure.', 'Run refresh.', error='envelope_drift')
        return cls(csrf, actor, viewer, loaders)

    def identity(self, operation, field):
        values = {str(p['variables'][field]) for p in self.preloaders
                  if p['name'] == operation and field in p['variables']}
        if len(values) != 1 or not next(iter(values)).isdigit():
            raise ThreadsError(6, 'Route identity is missing or ambiguous.', 'Run refresh.', error='envelope_drift')
        return values.pop()
