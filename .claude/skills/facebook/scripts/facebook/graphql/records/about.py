"""About fields of a profile or page: flat records keyed by Facebook's locale-independent section.

A fixed name/work/education model would drop whatever Facebook adds or renames, so each field keeps its section.
The overview lists the About tabs (collections), each one more request. Fields are read from every piece of a response
wherever it arrives, so a deferred piece is either used or irrelevant; an error may have dropped fields and is an issue.
"""
from facebook.graphql.records.parse import pieces
from facebook.graphql.records.time import iso

FIELDS = {
    'profile_id': 'string — numeric id of the profile or page; matches a post record\'s author_id',
    'section': 'string — locale-independent section such as directory_work; what --section takes',
    'collection': 'string | null — the About tab it was read from, in the viewer\'s language; null for the overview',
    'field_type': 'string | null — Facebook\'s own type of the field, when sent',
    'text': 'string — the value as shown; never cut',
    'url': 'string | null — a Facebook link the value points to, when there is one',
    'captured_at': 'string — ISO-8601 UTC time this tool received it; changes every run',
}


def _walk(obj):
    if isinstance(obj, dict):
        yield obj
        for value in obj.values():
            yield from _walk(value)
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk(item)


def collections(chunks):
    """[{name, id}] of the About tabs, in response order, each once."""
    found, seen = [], set()
    for chunk in chunks:
        for obj in _walk(chunk):
            nodes = (obj.get('all_collections') or {}).get('nodes') if isinstance(obj.get('all_collections'), dict) else None
            for node in nodes if isinstance(nodes, list) else []:
                if isinstance(node, dict) and isinstance(node.get('name'), str) and isinstance(node.get('id'), str):
                    if node['id'] not in seen:
                        seen.add(node['id'])
                        found.append({'name': node['name'], 'id': node['id']})
    return found


def fields(bodies, *, profile_id, collection_names, captured_at):
    """(fields from the overview and each collection response, deduped on (section, text); response issues)."""
    records, seen, issues = [], set(), []
    for chunks, collection in zip(bodies, collection_names, strict=True):
        for _, _, errors, _ in pieces(chunks):
            if errors:
                issues.append('graphql_errors')
        for chunk in chunks:
            for obj in _walk(chunk):
                section = obj.get('field_section_type')
                nodes = (obj.get('profile_fields') or {}).get('nodes') if isinstance(obj.get('profile_fields'), dict) else None
                if not isinstance(section, str) or not isinstance(nodes, list):
                    continue
                for node in nodes:
                    title = node.get('title') if isinstance(node, dict) else None
                    text = title.get('text') if isinstance(title, dict) else None
                    if not isinstance(text, str) or (section, text) in seen:
                        continue
                    seen.add((section, text))
                    records.append({'profile_id': profile_id, 'section': section, 'collection': collection,
                                    'field_type': node['field_type'] if isinstance(node.get('field_type'), str) else None,
                                    'text': text, 'url': node['link_url'] if isinstance(node.get('link_url'), str) else None,
                                    'captured_at': iso(captured_at)})
    return records, list(dict.fromkeys(issues))
