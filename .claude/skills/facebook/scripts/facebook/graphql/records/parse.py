"""Decoded GraphQL chunks → merged stories, and which parts of a response no record could use.

Facebook sends a story in @defer pieces; pieces with the same feedback id merge (non-null wins, dicts recurse, lists of
id-bearing dicts union by id, other lists concatenate without exact duplicates). A path-only patch (data at a path
that is not itself a record) is not applied: when it carries a field the records read, the story it points into is
marked incomplete, and when it points into no story it is a response issue. A piece that a record builder consumes
(a comment by id, a search result by its index path) is not a patch.
"""
import json

# 성진: 경로 전용 패치는 적용하지 않고 incomplete/issue로 표시한다. 캡처에서 실제 레코드 필드를 담은 패치가 자주 보이면 적용을 구현할 것
READ_FIELDS = frozenset({
    'message', 'text', 'body', 'creation_time', 'created_time', 'actors', 'author', 'name', 'url', 'permalink_url',
    'wwwURL', 'attachments', 'media', 'image', 'photo_image', 'uri', 'width', 'height', 'playable_url',
    'playable_url_quality_hd', 'accessibility_caption', 'title', 'description', 'attached_story', 'feedback',
    'reaction_count', 'share_count', 'count', 'comment_rendering_instance', 'comments', 'total_count', 'reactors',
    'count_reduced', 'replies_fields', 'expansion_info', 'expansion_token', 'comment_action_links',
    'comment_direct_parent', 'depth', 'is_sponsored', 'sponsored_data', 'ad_id', 'is_pinned', 'is_pinned_story',
    'is_featured', 'preferred_body', 'style_list',
})
ID_READERS = frozenset({'actors', 'author', 'feedback', 'attached_story', 'comment_direct_parent'})
# A post's inline top-comment preview is feedback-shaped but is a comment: never a post, never merged.
NON_POST_CONTAINERS = frozenset({'interesting_top_level_comments'})
SHARE_EXCLUDE = frozenset({'attached_story', *NON_POST_CONTAINERS})


def deep_merge(a, b):
    result = dict(a)
    for key, b_value in b.items():
        if b_value is None:
            continue
        a_value = result.get(key)
        if a_value is None:
            result[key] = b_value
        elif isinstance(a_value, dict) and isinstance(b_value, dict):
            result[key] = deep_merge(a_value, b_value)
        elif isinstance(a_value, list) and isinstance(b_value, list):
            result[key] = _merge_lists(a_value, b_value)
    return result


def _merge_lists(a, b):
    if a and isinstance(a[0], dict) and 'id' in a[0]:
        by_id, order = {}, []
        for item in [*a, *b]:
            if isinstance(item, dict) and 'id' in item:
                if item['id'] in by_id:
                    by_id[item['id']] = deep_merge(by_id[item['id']], item)
                else:
                    by_id[item['id']] = item
                    order.append(item['id'])
        return [by_id[i] for i in order]
    combined, seen = [], set()
    for item in (*a, *b):
        try:
            key = json.dumps(item, sort_keys=True, default=str)
        except TypeError:
            key = repr(item)
        if key not in seen:
            seen.add(key)
            combined.append(item)
    return combined


def is_comment(obj):
    """The post walk never descends into a comment: typed Comment, or depth together with author."""
    return isinstance(obj, dict) and (obj.get('__typename') == 'Comment' or ('depth' in obj and 'author' in obj))


def is_story(obj):
    return isinstance(obj, dict) and isinstance(obj.get('feedback'), dict) and obj['feedback'].get('id') is not None


def _read_field(name):
    if not isinstance(name, str):
        return False
    lower = name.lower()
    return (name in READ_FIELDS or ('edit' in lower and 'time' in lower)
            or any(marker in lower for marker in ('truncat', 'see_more', 'reel', 'life_event', 'lifeevent')))


def _carries_read_field(value):
    if isinstance(value, dict):
        return any(_read_field(key) or _carries_read_field(child) for key, child in value.items())
    if isinstance(value, list):
        return any(_carries_read_field(child) for child in value)
    return False


def _patch_is_read(path, data):
    if _carries_read_field(data):
        return True
    names = [key for key in path if isinstance(key, str)]
    return isinstance(data, dict) and 'id' in data and bool(names) and names[-1] in ID_READERS


def _story_at(anchors, path):
    """The innermost story a response path points into, from the chunk that delivered that part of the tree."""
    for prefix, data in sorted(anchors, key=lambda anchor: -len(anchor[0])):
        if path[:len(prefix)] != prefix:
            continue
        owner, current = None, data
        for key in path[len(prefix):]:
            if is_story(current):
                owner = str(current['feedback']['id'])
            if isinstance(current, dict) and isinstance(key, str):
                current = current.get(key)
            elif isinstance(current, list) and type(key) is int and 0 <= key < len(current):
                current = current[key]
            else:
                break
        if is_story(current):
            owner = str(current['feedback']['id'])
        if owner:
            return owner
    return None


def pieces(chunks):
    """Every delivered piece: each chunk and its incremental items, as (path or None, data, errors)."""
    for chunk in chunks:
        for piece in [chunk, *(chunk.get('incremental') or [])]:
            if isinstance(piece, dict):
                path = piece.get('path') if isinstance(piece.get('path'), list) else None
                yield path, piece.get('data'), piece.get('errors') or [], piece


def unplaced(chunks, consumed=lambda path, data: False):
    """(story ids touched, response-level issues) for patches and errors no record builder used."""
    anchors, touched, issues = [], set(), []
    for path, data, errors, _ in pieces(chunks):
        anchors.append((list(path or []), data))
        if (path is not None and not is_story(data) and not (isinstance(data, dict) and is_story(data.get('node')))
                and not consumed(path, data) and _patch_is_read(path, data)):
            owner = _story_at(anchors, path)
            if owner:
                touched.add(owner)
            else:
                issues.append('unsupported_path_patch')
        for error in errors:
            where = error.get('path') if isinstance(error, dict) else None
            if isinstance(where, list) and where and not any(_read_field(key) for key in where):
                continue
            owner = _story_at(anchors, where) if isinstance(where, list) and where else None
            if owner:
                touched.add(owner)
            else:
                issues.append('graphql_errors')
    return touched, list(dict.fromkeys(issues))


def _walk(obj, stories, top_level, nested):
    if isinstance(obj, dict):
        if is_comment(obj):
            return
        if is_story(obj):
            key = str(obj['feedback']['id'])
            if not nested:
                top_level.setdefault(key, None)
            stories[key] = deep_merge(stories[key], obj) if key in stories else dict(obj)
        for key, value in obj.items():
            if key in NON_POST_CONTAINERS:
                continue
            _walk(value, stories, top_level, nested or key == 'attached_story')
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, stories, top_level, nested)


class Stories:
    """Every distinct story in a response, merged by feedback id, with share chains linked and cycles cut."""

    def __init__(self, chunks):
        stories, top_level = {}, {}
        for path, data, _, piece in pieces(chunks):
            _walk({k: v for k, v in piece.items() if k != 'incremental'}, stories, top_level,
                  'attached_story' in (path or []))
        touched, issues = unplaced(chunks)
        for key in touched:
            if key in stories:
                stories[key]['incomplete'] = True

        def linked(story, ancestors):
            result = dict(story)
            attached = find_attached_story(story)
            if is_story(attached):
                child = str(attached['feedback']['id'])
                if child in ancestors:
                    result.pop('attached_story', None)
                    _strip_attached(result, child)
                    issues.append('cyclic_shared_story')
                else:
                    result['attached_story'] = linked(stories.get(child, attached), ancestors | {child})
            return result

        self.by_id = {key: linked(story, frozenset({key})) for key, story in stories.items()}
        self.top_level = [key for key in top_level if key in self.by_id]
        self.issues = list(dict.fromkeys(issues))


def _strip_attached(story, child):
    """Remove a cyclic share wherever the story's own subtree carries it."""
    for node in iter_story_dicts(story, exclude_keys=frozenset(NON_POST_CONTAINERS)):
        attached = node.get('attached_story')
        if is_story(attached) and str(attached['feedback']['id']) == child:
            node.pop('attached_story', None)


def iter_story_dicts(obj, *, exclude_keys=frozenset(), exclude_links=False):
    """Depth-first dicts of a story, skipping named containers, embedded comments and optionally link subtrees."""
    if isinstance(obj, dict):
        if is_comment(obj):
            return
        if exclude_links and isinstance(obj.get('url'), str) and 'uri' not in obj and ('title' in obj or 'description' in obj):
            return
        yield obj
        for key, value in obj.items():
            if key not in exclude_keys:
                yield from iter_story_dicts(value, exclude_keys=exclude_keys, exclude_links=exclude_links)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_story_dicts(item, exclude_keys=exclude_keys, exclude_links=exclude_links)


def find_attached_story(story):
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        if isinstance(node.get('attached_story'), dict):
            return node['attached_story']
    return None


def find_page_info(chunks, key):
    """The page_info of the connection named `key`, inline or delivered later at a path."""
    found = None

    def walk(obj):
        if isinstance(obj, dict):
            connection = obj.get(key)
            if isinstance(connection, dict) and isinstance(connection.get('page_info'), dict):
                return connection['page_info']
            for value in obj.values():
                result = walk(value)
                if result is not None:
                    return result
        elif isinstance(obj, list):
            for value in obj:
                result = walk(value)
                if result is not None:
                    return result
        return None

    for path, data, _, _ in pieces(chunks):
        if path and path[-1] == key and isinstance(data, dict) and isinstance(data.get('page_info'), dict):
            found = data['page_info']
        found = walk(data) or found
    return found


def top_page_info(chunks, key):
    """The page_info of the outermost connection named `key` (a reply connection holds its replies' own)."""
    for path, data, _, _ in pieces(chunks):
        if path is None and isinstance(data, dict):
            stack = [data]
            while stack:
                obj = stack.pop(0)
                if isinstance(obj, dict):
                    connection = obj.get(key)
                    if isinstance(connection, dict) and isinstance(connection.get('page_info'), dict):
                        return connection['page_info']
                    stack.extend(v for v in obj.values() if isinstance(v, (dict, list)))
                elif isinstance(obj, list):
                    stack.extend(v for v in obj if isinstance(v, (dict, list)))
    return find_page_info(chunks, key)


def has_items(chunks, key):
    """Whether the connection `key` carried any item, so zero readable records means the shape changed."""
    for path, data, _, _ in pieces(chunks):
        path = path or []
        if path and path[-1] == key and isinstance(data, dict) and (data.get('edges') or data.get('nodes')):
            return True
        if key in path and any(part in ('edges', 'nodes') for part in path) and data:
            return True
        stack = [data]
        while stack:
            item = stack.pop()
            if isinstance(item, dict):
                connection = item.get(key)
                if isinstance(connection, dict) and (connection.get('edges') or connection.get('nodes')):
                    return True
                stack.extend(item.values())
            elif isinstance(item, list):
                stack.extend(item)
    return False
