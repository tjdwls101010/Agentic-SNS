"""Read only Relay bbox results from JSON scripts, with operation/identity checks."""

from ._errors import ThreadsError
from ._session import Scripts, preloaders



def matches(data, operation):
    if operation == 'BarcelonaFeedDirectQuery':
        return 'feedData' in data
    if operation == 'BarcelonaProfilePageDirectQuery':
        return 'user' in data
    if operation.startswith('BarcelonaProfile') and 'Tab' in operation:
        return 'mediaData' in data
    if operation == 'BarcelonaSearchResultsQuery':
        return 'searchResults' in data
    media = data.get('media')
    if not isinstance(media, dict):
        return False
    info = media.get('text_post_app_info') or {}
    if 'StrongIdTarget' in operation:
        return 'code' in media
    if 'StrongIdDownward' in operation:
        return 'direct_replies' in info
    if 'StrongIdUpward' in operation:
        return 'containing_thread' in info
    return False


class SSR:
    def __init__(self, html):
        self.results, self.preloaders = [], preloaders(html)
        def walk(value, name=None, variables=None):
            if isinstance(value, dict):
                name = value.get('queryName', value.get('operationName', name))
                variables = value.get('variables', variables)
                bbox = value.get('__bbox')
                result = bbox.get('result') if isinstance(bbox, dict) else None
                if isinstance(result, dict) and isinstance(result.get('data'), dict):
                    self.results.append((name, variables, result['data']))
                for key, child in value.items():
                    if key != '__bbox' or result is None:
                        walk(child, name, variables)
            elif isinstance(value, list):
                for child in value:
                    walk(child, name, variables)
        for document in Scripts(html).documents:
            walk(document)

    def select(self, operation, identity=None):
        candidates = []
        for name, variables, data in self.results:
            if name and name != operation or not matches(data, operation):
                continue
            ids = set()
            if isinstance(variables, dict):
                ids.update(str(variables[k]) for k in ('postID', 'userID') if k in variables)
            entity = data.get('media') if 'StrongId' in operation else data.get('user')
            if isinstance(entity, dict) and entity.get('pk') is not None:
                ids.add(str(entity['pk']))
            if identity is not None:
                loaders = [p for p in self.preloaders if p['name'] == operation]
                loader_ids = {str(p['variables'][key]) for p in loaders for key in ('userID', 'postID') if key in p['variables']}
                if ids and ids != {str(identity)} or loader_ids and loader_ids != {str(identity)}:
                    continue
                if not ids and not loader_ids:
                    continue
            if data not in candidates:
                candidates.append(data)
        if len(candidates) != 1:
            raise ThreadsError(6, f'The route has no unambiguous {operation} payload for this target.',
                               'Run refresh; do not treat a missing payload as an empty result.', error='envelope_drift')
        return candidates[0]
