"""Fresh route credentials and balanced JSON preloaders; credentials stay in memory."""
import json
import re
from dataclasses import dataclass

from ._errors import ThreadsError


def preloaders(html):
    found = {}
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{\s*"preloaderID"\s*:', html):
        try:
            value, _ = decoder.raw_decode(html[match.start():])
            name = re.fullmatch(r'adp_(.+?)RelayPreloader_.*', value['preloaderID'])
            if name and str(value.get('queryID', '')).isdigit() and isinstance(value.get('variables'), dict):
                entry = dict(name=name[1], doc_id=str(value['queryID']), variables=value['variables'])
                found[(name[1], json.dumps(value['variables'], sort_keys=True))] = entry
        except (ValueError, KeyError, TypeError):
            continue
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
