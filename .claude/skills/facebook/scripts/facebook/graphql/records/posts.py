"""Post records: every field decided here and described once in FIELDS."""
from facebook.graphql.records.parse import SHARE_EXCLUDE, Stories, find_attached_story, is_story, iter_story_dicts
from facebook.graphql.records.time import iso, timestamp

FIELDS = {
    'id': 'string — stable identity of the post (its feedback id); dedupe on this',
    'url': 'string | null — permalink; the post command\'s argument',
    'type': 'string — status | photo | video | shared | link | reel | life_event | unknown',
    'pinned': 'boolean — pinned to the top of its timeline or group, so it can be old; passes any date window',
    'sponsored': 'boolean — an advertisement; feed leaves these out unless --include-sponsored',
    'undated': 'boolean — Facebook sent no usable creation time; passes any date window',
    'incomplete': 'boolean — part of this post arrived in a piece that could not be merged; fields may be missing',
    'author_name': 'string | null — display name of the author (for a share: of the person who shared)',
    'author_url': 'string | null — the author\'s profile or page URL; the profile and about commands\' argument',
    'author_id': 'string | null — numeric id of the author',
    'created_at': 'string | null — ISO-8601 UTC time the post was created',
    'edited_at': 'string | null — ISO-8601 UTC time of the last edit; null when Facebook sent none',
    'text': 'string — the body as received; empty when the post has none',
    'text_truncated': 'boolean — Facebook marked the received body as cut; open the post for the rest',
    'media': 'array<object> — photos and videos of the post itself, in order',
    'media[].kind': 'string — image | video',
    'media[].url': 'string — signed, expiring, viewer-scoped; share only when the user needs the media',
    'media[].width': 'integer | null — pixels',
    'media[].height': 'integer | null — pixels',
    'media[].alt': 'string | null — Facebook\'s automatic description of the photo, in the viewer\'s language; '
                   'machine-generated and can be wrong; null when not sent',
    'links': 'array<object> — external links the post shares',
    'links[].url': 'string — the link target',
    'links[].title': 'string | null — the link preview\'s title',
    'links[].description': 'string | null — the link preview\'s description',
    'reaction_count': 'integer | null — reactions; null when not sent',
    'comment_count': 'integer | null — comments; null when not sent',
    'share_count': 'integer | null — shares; null when not sent',
    'shared_post': 'object | null — the post this one shares, itself a post record (its author is the original '
                   'author); shares can nest',
    'source': 'string — where it was read: newsfeed | timeline | group | search | permalink',
    'captured_at': 'string — ISO-8601 UTC time this tool received it; changes every run',
}


def _text(story):
    """The first non-empty message.text reachable from the story's own root."""
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        message = node.get('message')
        if isinstance(message, dict) and isinstance(message.get('text'), str) and message['text']:
            return message['text']
    return ''


def _permalink(story):
    for key in ('permalink_url', 'wwwURL'):
        if isinstance(story.get(key), str):
            return story[key]
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        if node is not story and isinstance(node.get('wwwURL'), str):
            return node['wwwURL']
    return None


def _actors(story):
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        actors = node.get('actors')
        if isinstance(actors, list) and actors and all(isinstance(a, dict) for a in actors):
            return actors
    return []


def _media(story, exclude_links=False):
    """Photos and videos: one image per media node (image, else photo_image), a video per playable URL."""
    media, seen = [], set()
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE, exclude_links=exclude_links):
        image = node.get('image') if isinstance(node.get('image'), dict) and isinstance(node['image'].get('uri'), str) \
            else node.get('photo_image') if isinstance(node.get('photo_image'), dict) \
            and isinstance(node['photo_image'].get('uri'), str) else None
        if image is not None and image['uri'] not in seen:
            seen.add(image['uri'])
            alt = node.get('accessibility_caption')
            media.append({'kind': 'image', 'url': image['uri'], 'width': _dimension(image.get('width')),
                          'height': _dimension(image.get('height')), 'alt': alt if isinstance(alt, str) and alt else None})
        playable = node.get('playable_url') or node.get('playable_url_quality_hd')
        if isinstance(playable, str) and playable not in seen:
            seen.add(playable)
            media.append({'kind': 'video', 'url': playable, 'width': None, 'height': None, 'alt': None})
    return media


def _dimension(value):
    return value if type(value) is int and value > 0 else None


def _links(story):
    links, seen = [], set()
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        url = node.get('url')
        if isinstance(url, str) and url not in seen and ('title' in node or 'description' in node) and 'uri' not in node:
            seen.add(url)
            links.append({'url': url, 'title': node['title'] if isinstance(node.get('title'), str) else None,
                          'description': node['description'] if isinstance(node.get('description'), str) else None})
    return links


def _any_key(story, test):
    return any(test(key.lower(), value) for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE)
               for key, value in node.items())


def _edited(story):
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        for key, value in node.items():
            if type(value) is int and 'edit' in key.lower() and 'time' in key.lower():
                return value
    return None


def _count(story, key):
    feedback = story.get('feedback')
    value = feedback.get(key) if isinstance(feedback, dict) else None
    value = value.get('count') if isinstance(value, dict) else value
    return value if type(value) is int and value >= 0 else None


def _comment_count(story):
    feedback = story.get('feedback') if isinstance(story.get('feedback'), dict) else {}
    instance = feedback.get('comment_rendering_instance')
    comments = instance.get('comments') if isinstance(instance, dict) else None
    total = comments.get('total_count') if isinstance(comments, dict) else None
    return total if type(total) is int and total >= 0 else None


def _type(story, media, links, shared):
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        for key in node:
            lower = key.lower()
            if 'reel' in lower:
                return 'reel'
            if 'life_event' in lower or 'lifeevent' in lower:
                return 'life_event'
    if shared:
        return 'shared'
    if any(m['kind'] == 'video' for m in media):
        return 'video'
    if any(m['kind'] == 'image' for m in _media(story, exclude_links=True)):
        return 'photo'
    if links:
        return 'link'
    return 'status' if _text(story) else 'unknown'


def build(story, *, source, captured_at):
    """One post record from a merged story."""
    actors = _actors(story)
    author = actors[0] if actors else {}
    attached = find_attached_story(story)
    shared = build(attached, source=source, captured_at=captured_at) if is_story(attached) else None
    media, links = _media(story), _links(story)
    created = story.get('creation_time')
    return {
        'id': str(story['feedback']['id']),
        'url': _permalink(story),
        'type': _type(story, media, links, isinstance(attached, dict)),
        'pinned': _any_key(story, lambda key, value: value is True and key in ('is_pinned', 'is_pinned_story', 'is_featured')),
        'sponsored': _any_key(story, lambda key, value: (key == 'is_sponsored' and value is True)
                              or (key == 'sponsored_data' and isinstance(value, dict)) or (key == 'ad_id' and bool(value))),
        'undated': timestamp(created) is None,
        'incomplete': bool(story.get('incomplete')) or (isinstance(attached, dict) and shared is None)
                      or bool(shared and shared['incomplete']),
        'author_name': author.get('name') if isinstance(author.get('name'), str) else None,
        'author_url': author.get('url') if isinstance(author.get('url'), str) else None,
        'author_id': str(author['id']) if author.get('id') is not None else None,
        'created_at': iso(timestamp(created)),
        'edited_at': iso(timestamp(_edited(story))),
        'text': _text(story),
        'text_truncated': _any_key(story, lambda key, value: bool(value) and key != 'message_truncation_line_limit'
                                   and any(m in key for m in ('truncat', 'preferred_body', 'see_more'))),
        'media': media,
        'links': links,
        'reaction_count': _count(story, 'reaction_count'),
        'comment_count': _comment_count(story),
        'share_count': _count(story, 'share_count'),
        'shared_post': shared,
        'source': source,
        'captured_at': iso(captured_at),
    }


def top_level(chunks, *, source, captured_at):
    """(records of the stories seen outside any share, in server order; response issues)."""
    stories = Stories(chunks)
    return [build(stories.by_id[key], source=source, captured_at=captured_at) for key in stories.top_level], stories.issues


def permalink(chunks, *, captured_at):
    """(the permalink's own post, or None; response issues): the root of a chunk without a path; others are decoys."""
    stories = Stories(chunks)
    for path, data in ((c.get('path'), c.get('data')) for c in chunks):
        if path or not isinstance(data, dict):
            continue
        root = data.get('node_v2') or data.get('node') or data.get('story')
        if is_story(root) and str(root['feedback']['id']) in stories.by_id:
            story = stories.by_id[str(root['feedback']['id'])]
            return build(story, source='permalink', captured_at=captured_at), stories.issues
    return None, stories.issues
