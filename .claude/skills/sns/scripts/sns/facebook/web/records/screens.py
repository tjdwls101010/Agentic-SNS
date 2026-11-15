"""The lists a screen preloads into its own page (web.payload): saved items, joined groups, a profile's app collections
(photos, followers), the account's own friends and a group's new members, in the skill's terms.

Each list is found by what holds it in the recon captures (2026-11-16), not by a key the captures did not show: the
saved items sit beside saves_from_notification, the joined groups beside total_joined_groups, an app collection's items
beneath the object whose id is an app_collection id. Other connections of the same screen (the profile switcher, the
saved collections, the groups left rail) are never read. Each function returns (records, page_info or None when the
list is absent, whether it had items, response issues).
"""
import base64
import binascii

from sns.facebook.web.records.moment import iso
from sns.facebook.web.records.parse import pieces

SAVED_FIELDS = {
    'kind': 'string — saved',
    'id': 'string — Facebook\'s id of the save',
    'title': 'string | null — the saved item\'s title as Facebook shows it',
    'item_type': 'string | null — what was saved, in Facebook\'s type name (e.g. ExternalUrl, Page)',
    'item_id': 'string | null — Facebook\'s id of the saved item',
    'category': 'string | null — Facebook\'s category of the save (e.g. LINK)',
    'details': 'array<string> — the lines Facebook shows under the title (e.g. its kind and the site), in the viewer\'s '
               'language',
    'url': 'string | null — where the item is: a link\'s own address, else its Facebook URL',
    'created_at': 'null — the save time is not shown',
    'captured_at': 'string — ISO-8601 UTC time this tool received it; changes every run',
}
PHOTO_FIELDS = {
    'kind': 'string — photo',
    'id': 'string — the photo\'s numeric id',
    'url': 'string | null — the photo\'s Facebook URL; post <url> opens it',
    'alt': 'string | null — the description Facebook gives the picture (its own or the owner\'s)',
    'image': 'string | null — the picture\'s address; signed and short-lived',
    'width': 'integer | null', 'height': 'integer | null',
    'created_at': 'null — the photo\'s date is not in this list',
    'captured_at': 'string — ISO-8601 UTC time this tool received it; changes every run',
}


def _text(value):
    return value if isinstance(value, str) and value.strip() else None


def _text_of(value):
    return _text(value.get('text')) if isinstance(value, dict) else None


def _walk(value):
    stack = [value]
    while stack:
        item = stack.pop()
        if isinstance(item, dict):
            yield item
            stack.extend(reversed(list(item.values())))
        elif isinstance(item, list):
            stack.extend(reversed(item))


def _is_connection(value):
    return isinstance(value, dict) and isinstance(value.get('edges'), list) and isinstance(value.get('page_info'), dict)


def _find(chunks, holds):
    """(the connection `holds(dict)` picks out, response issues): the first dict for which holds() gives one."""
    found, issues = None, []
    for _, data, errors, _ in pieces(chunks):
        if errors:
            issues.append('graphql_errors')
        for obj in _walk(data):
            if found is None:
                candidate = holds(obj)
                if _is_connection(candidate):
                    found = candidate
    return found, list(dict.fromkeys(issues))


def _nodes(found):
    return [edge['node'] for edge in found['edges'] if isinstance(edge, dict) and isinstance(edge.get('node'), dict)]


def _list(chunks, holds, record):
    found, issues = _find(chunks, holds)
    if found is None:
        return [], None, False, issues
    nodes = _nodes(found)
    return [r for r in map(record, nodes) if r is not None], found['page_info'], bool(nodes), issues


def _entity(kind, identity, name, url, verified, captured_at):
    return {'kind': kind, 'id': str(identity), 'name': name, 'url': url, 'created_at': None,
            'verified': verified if isinstance(verified, bool) else None, 'captured_at': iso(captured_at)}


# --- saved -------------------------------------------------------------------------------------------------------------

def _beside(key):
    """The connection that is a sibling of `key` in the same object."""
    def holds(obj):
        if key not in obj:
            return None
        return next((value for name, value in obj.items() if name != key and _is_connection(value)), None)
    return holds


def saved(chunks, *, captured_at):
    def record(node):
        savable = node.get('savable') if isinstance(node.get('savable'), dict) else None
        if node.get('__typename') != 'Save' or savable is None or node.get('id') is None:
            return None
        details = [_text_of(item) for item in savable.get('savable_attributes') or []]
        url = _text(savable.get('external_url')) or _text(savable.get('url')) or _text(savable.get('savable_permalink'))
        return {'kind': 'saved', 'id': str(node['id']), 'title': _text_of(savable.get('savable_title')),
                'item_type': _text(savable.get('__typename')),
                'item_id': str(savable['id']) if savable.get('id') is not None else None,
                'category': _text(savable.get('savable_default_category')), 'details': [d for d in details if d],
                'url': url, 'created_at': None, 'captured_at': iso(captured_at)}
    return _list(chunks, _beside('saves_from_notification'), record)


# --- joined groups -----------------------------------------------------------------------------------------------------

def joined_groups(chunks, *, captured_at):
    def record(node):
        if node.get('__typename') != 'Group' or node.get('id') is None:
            return None
        return _entity('group', node['id'], _text(node.get('name')), _text(node.get('url')), None, captured_at)
    return _list(chunks, _beside('total_joined_groups'), record)


# --- a profile's app collections: photos, followers --------------------------------------------------------------------

def _app_collection(obj):
    """The items of the app collection `obj` is (its id is base64 of app_collection:…): the connection beneath it,
    beside the id on the photos tab, one wrapper further in on the followers tab."""
    try:
        decoded = base64.b64decode(obj.get('id') or '', validate=True) if isinstance(obj.get('id'), str) else b''
    except (binascii.Error, ValueError):
        return None
    if not decoded.startswith(b'app_collection:'):
        return None
    return next((inner for inner in _walk(list(obj.values())) if _is_connection(inner)), None)


def app_collection(chunks, *, captured_at):
    """A profile tab's items: a Photo is a photo record, a person or page an entity."""
    def record(item):
        inner = item.get('node') if isinstance(item.get('node'), dict) else {}
        if item.get('__typename') != 'TimelineAppCollectionItem' or inner.get('id') is None:
            return None
        if inner.get('__typename') == 'Photo':
            viewer = inner.get('viewer_image') if isinstance(inner.get('viewer_image'), dict) else {}
            image = _text(viewer.get('uri')) or _text((item.get('image') or {}).get('uri'))
            size = {key: viewer[key] if type(viewer.get(key)) is int else None for key in ('width', 'height')}
            return {'kind': 'photo', 'id': str(inner['id']), 'url': _text(item.get('url')),
                    'alt': _text(inner.get('accessibility_caption')), 'image': image, **size, 'created_at': None,
                    'captured_at': iso(captured_at)}
        if inner.get('__typename') in ('User', 'Page'):
            kind = 'page' if inner['__typename'] == 'Page' else 'person'
            name = _text_of(item.get('title'))
            return _entity(kind, inner['id'], name.strip() if name else None,
                           _text(inner.get('url')) or _text(item.get('url')), inner.get('is_verified'), captured_at)
        return None
    return _list(chunks, _app_collection, record)


# --- the account's own friends ------------------------------------------------------------------------------------------

def friends(chunks, *, captured_at):
    def record(node):
        if node.get('__typename') != 'User' or node.get('id') is None:
            return None
        return _entity('person', node['id'], _text(node.get('name')), _text(node.get('url')), node.get('is_verified'),
                       captured_at)
    return _list(chunks, lambda obj: obj.get('all_friends'), record)


# --- a group's new members ----------------------------------------------------------------------------------------------

def new_members(chunks, *, captured_at):
    """The members tab's new members section only; its rows only (the other buckets are not read, and their rows name
    other people in their context lines)."""
    def record(node):
        if node.get('__typename') != 'User' or node.get('id') is None:
            return None
        return _entity('person', node['id'], _text(node.get('name')), _text(node.get('url')), node.get('is_verified'),
                       captured_at)
    return _list(chunks, lambda obj: obj.get('new_members'), record)
