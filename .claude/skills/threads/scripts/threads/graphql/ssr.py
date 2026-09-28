"""Read only Relay bbox results from JSON scripts, with operation/identity checks."""
import re

from ..errors import ThreadsError
from .session import Scripts, preloaders

POST_PAGE_CHANGED = ('Threads changed the post page; refresh cannot repair it. '
                     'Tell the user the post reader needs an update.')


def media_identity(media):
    """A post payload's own id: pk, or the numeric head of the `<pk>_<author pk>` media id some payloads carry alone."""
    if media.get('pk') is not None:
        return str(media['pk'])
    match = re.fullmatch(r'(\d+)_\d+', str(media.get('id') or ''))
    return match[1] if match else None


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

    def select(self, operation, shape, identity=None):
        """The one rendered result of `operation` (its current name) marked by its declared `shape` key, and about
        `identity` when given."""
        candidates = []
        for name, variables, data in self.results:
            if name and name != operation or shape is None or shape not in data:
                continue
            ids = set()
            if isinstance(variables, dict):
                ids.update(str(variables[k]) for k in ('postID', 'userID') if k in variables)
            entity = data.get('user')
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

    def post_page(self, code):
        """The post a post route names, with its parent chain and first reply batch.

        The route's preloaders all carry one postID. Each payload proves it is about that post by its own identity and
        says what it is by its shape: the post itself has the requested shortcode, the parent chain has
        containing_thread, the reply batch has direct_replies. Query names are never consulted, because Threads renames
        them; a second payload claiming the same role is refused rather than guessed between.
        """
        ids = {str(p['variables']['postID']) for p in self.preloaders if 'postID' in p['variables']}
        if len(ids) != 1 or not next(iter(ids)).isdigit():
            raise ThreadsError(6, 'The post route does not name exactly one post.', POST_PAGE_CHANGED,
                               error='envelope_drift')
        post_id = ids.pop()
        roles = {'post': [], 'parents': [], 'replies': []}
        for _, _, data in self.results:
            media = data.get('media')
            if not isinstance(media, dict) or media_identity(media) != post_id:
                continue
            info = media.get('text_post_app_info')
            info = info if isinstance(info, dict) else {}
            for role, fits in (('post', media.get('code') == code), ('parents', 'containing_thread' in info),
                               ('replies', 'direct_replies' in info)):
                if fits and data not in roles[role]:
                    roles[role].append(data)
        for role, found in roles.items():
            if len(found) != 1:
                raise ThreadsError(6, f'The post page has no unambiguous {role} payload for this post.',
                                   POST_PAGE_CHANGED, error='envelope_drift')
        return post_id, roles['post'][0], roles['parents'][0], roles['replies'][0]
