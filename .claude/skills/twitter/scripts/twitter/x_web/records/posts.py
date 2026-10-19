"""X's user and tweet objects as the skill's records: accounts and posts, in the skill's own field names.

X sends newer grouped user fields (core, avatar, location, privacy, verification, relationship_counts, tweet_counts,
action_counts, website, banner, pinned_items, relationship_perspectives) and, on older payloads, legacy ones: the
grouped field wins and legacy fills what it lacks. A count X did not send is None (not reported), never 0.
"""
import re
from datetime import timezone
from email.utils import parsedate_to_datetime

ORIGIN = 'https://x.com'
# 성진: 인용·리포스트 중첩은 깊이 5에서 끊는다(현행 지식) — 적대적·순환 응답의 작업량 상한. 실제로 더 깊은 사슬이 보이면 올린다
MAX_DEPTH = 5


def _time(value):
    """X's 'Thu Oct 15 10:00:00 +0000 2026' as UTC ISO, or None."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _int(value):
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


def _dict(value):
    return value if isinstance(value, dict) else {}


def _str(value):
    return value if isinstance(value, str) and value else None


def expand(text, links, media_links=()):
    """Text with t.co links replaced by their destinations and the links X appends for attached media removed."""
    text = text or ''
    media = {item.get('url') for item in media_links if isinstance(item, dict) and item.get('url')}
    for url in media:
        text = re.sub(r'\s*' + re.escape(url), '', text)
    for link in links:
        if isinstance(link, dict) and link.get('url') and link['url'] not in media:
            text = text.replace(link['url'], link.get('expanded_url') or link['url'])
    return text


def account_record(node):
    """One user result as an account record; a UserUnavailable is a record marked unavailable."""
    node = _dict(node)
    if node.get('__typename') == 'UserUnavailable':
        return {'id': None, 'unavailable': True, 'unavailable_reason': _str(node.get('reason')), 'kind': 'account'}
    core, legacy = _dict(node.get('core')), _dict(node.get('legacy'))
    counts, tweets = _dict(node.get('relationship_counts')), _dict(node.get('tweet_counts'))
    perspectives = _dict(node.get('relationship_perspectives'))
    verification = _dict(node.get('verification'))
    handle = _str(core.get('screen_name')) or _str(legacy.get('screen_name')) or ''
    bio_node = _dict(node.get('profile_bio'))
    bio_text = bio_node.get('description') if 'description' in bio_node else legacy.get('description')
    bio_links = (_dict(_dict(bio_node.get('entities')).get('description')).get('urls')
                 or _dict(_dict(legacy.get('entities')).get('description')).get('urls') or [])
    label = _dict(_dict(node.get('affiliates_highlighted_label')).get('label'))
    declared = _str(node.get('parody_commentary_fan_label'))

    def first(*values):
        return next((value for value in values if value is not None), None)
    return {
        'id': _str(node.get('rest_id')), 'username': handle,
        'full_name': _str(core.get('name')) or _str(legacy.get('name')),
        'created_at': _time(core.get('created_at') or legacy.get('created_at')),
        'follower_count': first(_int(counts.get('followers')), _int(legacy.get('followers_count'))),
        'following_count': first(_int(counts.get('following')), _int(legacy.get('friends_count'))),
        'post_count': first(_int(tweets.get('tweets')), _int(legacy.get('statuses_count'))),
        'media_count': first(_int(tweets.get('media_tweets')), _int(legacy.get('media_count'))),
        'like_count': first(_int(_dict(node.get('action_counts')).get('favorites_count')),
                            _int(legacy.get('favourites_count'))),
        'is_blue_verified': bool(node.get('is_blue_verified')),
        'is_verified': bool(verification.get('verified')),
        'verified_type': _str(verification.get('verified_type')),
        'private': bool(_dict(node.get('privacy')).get('protected', legacy.get('protected', False))),
        'bio': expand(bio_text, bio_links) if isinstance(bio_text, str) and bio_text else None,
        'location': _str(_dict(node.get('location')).get('location')) or _str(legacy.get('location')),
        'website': _str(_dict(node.get('website')).get('url')),
        'url': f'{ORIGIN}/{handle}' if handle else None,
        'avatar_url': _str(_dict(node.get('avatar')).get('image_url')),
        'banner_url': _str(_dict(node.get('banner')).get('image_url')) or _str(legacy.get('profile_banner_url')),
        'relationship': {'following': perspectives.get('following'), 'followed_by': perspectives.get('followed_by'),
                         'blocking': perspectives.get('blocking'), 'muting': perspectives.get('muting'),
                         'follow_request_sent': bool(node.get('follow_request_sent'))},
        'affiliation': ({'label': _str(label.get('description')), 'url': _str(_dict(label.get('url')).get('url'))}
                        if label else None),
        'declared_label': declared if declared and declared != 'None' else None,
        'pinned_post_ids': list(_dict(node.get('pinned_items')).get('tweet_ids_str')
                                or legacy.get('pinned_tweet_ids_str') or []),
        'unavailable': False, 'kind': 'account',
    }


def mentions(entities):
    """Mentioned handles without @, in the order they appear, each once whatever its case."""
    seen, handles = set(), []
    for mention in sorted((m for m in entities.get('user_mentions') or [] if isinstance(m, dict)),
                          key=lambda m: (m.get('indices') or [0])[0]):
        handle = mention.get('screen_name')
        if handle and handle.lower() not in seen:
            seen.add(handle.lower())
            handles.append(handle)
    return handles


def _media(legacy):
    found = []
    for item in _dict(legacy.get('extended_entities')).get('media') or []:
        if not isinstance(item, dict):
            continue
        variants = [v for v in _dict(item.get('video_info')).get('variants') or []
                    if isinstance(v, dict) and v.get('content_type') == 'video/mp4' and v.get('url')]
        url = max(variants, key=lambda v: _int(v.get('bitrate')) or 0)['url'] if variants else item.get('media_url_https')
        size = _dict(item.get('original_info'))
        found.append({'kind': item.get('type') or 'photo', 'url': url or '', 'width': _int(size.get('width')),
                      'height': _int(size.get('height')), 'alt_text': _str(item.get('ext_alt_text'))})
    return found


def _note(node):
    """A community note shown under the post: other users' context, not the author's words."""
    pivot = _dict(node.get('birdwatch_pivot'))
    if not pivot:
        return None
    subtitle = _dict(pivot.get('subtitle'))
    text = subtitle.get('text') if isinstance(subtitle.get('text'), str) else ''
    for entity in subtitle.get('entities') or []:
        ref = _dict(_dict(entity).get('ref'))
        if ref.get('url') and ref.get('expandedUrl'):
            text = text.replace(ref['url'], ref['expandedUrl'])
    note_id = _str(_dict(pivot.get('note')).get('rest_id'))
    url = _str(pivot.get('destinationUrl'))
    if url:
        url = re.sub(r'^https://(www\.)?twitter\.com/', ORIGIN + '/', url)
    return {'id': note_id, 'title': _str(pivot.get('title')), 'text': text or None, 'url': url}


def _card(node, links):
    """A card: a link preview's title, description and destination, a poll's choices (X15: poll keys known, not
    seen live), or just its kind for other cards (a space, a player)."""
    legacy = _dict(_dict(node.get('card')).get('legacy'))
    if not legacy:
        return None
    values = {}
    for binding in legacy.get('binding_values') or []:
        binding = _dict(binding)
        value = _dict(binding.get('value'))
        values[binding.get('key')] = value.get('string_value') if 'string_value' in value else value.get('boolean_value')
    name = _str(legacy.get('name')) or ''
    kind = name.split(':')[-1]
    card = {'kind': kind}
    if kind.startswith('poll') and kind.endswith('choice_text_only'):
        choices = []
        for number in range(1, 5):
            label = values.get(f'choice{number}_label')
            if label is not None:
                choices.append({'label': label, 'count': _int(values.get(f'choice{number}_count'))})
        card['poll'] = {'choices': choices, 'final': values.get('counts_are_final') is True,
                        'ends_at': _str(values.get('end_datetime_utc'))}
        return card
    short = values.get('card_url') or legacy.get('url')
    destination = next((link.get('expanded_url') for link in links if isinstance(link, dict)
                        and link.get('url') == short and link.get('expanded_url')), None)
    for key in ('title', 'description', 'domain'):
        if isinstance(values.get(key), str):
            card[key] = values[key]
    if destination or values.get('vanity_url'):
        card['url'] = destination or values.get('vanity_url')
    if kind == 'audiospace' and values.get('id'):
        card['space_url'] = f'{ORIGIN}/i/spaces/{values["id"]}'
    return card


def _article(node):
    result = _dict(_dict(_dict(node.get('article')).get('article_results')).get('result'))
    if not result:
        return None
    blocks = _dict(result.get('content_state')).get('blocks')
    text = None
    if isinstance(blocks, list):
        text = '\n\n'.join(b['text'] for b in blocks if isinstance(b, dict) and isinstance(b.get('text'), str)
                           and b['text'].strip())
    return {'id': _str(result.get('rest_id')), 'title': _str(result.get('title')),
            'preview': _str(result.get('preview_text')), 'text': text}


def _edit(node, own_id):
    control = _dict(node.get('edit_control'))
    initial = _dict(control.get('edit_control_initial'))
    versions = initial.get('edit_tweet_ids') or control.get('edit_tweet_ids') or []
    versions = [v for v in versions if isinstance(v, str)]
    if len(versions) < 2:
        return None
    return {'versions': versions, 'latest': versions[-1] == own_id}


def _tombstone(node, entry_id):
    identity = None
    if isinstance(entry_id, str):
        match = re.search(r'tweet-(\d+)$', entry_id)
        identity = match[1] if match else None
    text = _dict(_dict(node.get('tombstone')).get('text')).get('text')
    return {'id': identity, 'unavailable': True, 'unavailable_reason': text if isinstance(text, str) else None,
            'kind': 'post'}


def post_record(node, entry_id=None, _depth=0):
    """One tweet result as a post record; a tombstone is a record marked unavailable; a result without an id is
    None (the caller counts it)."""
    if not isinstance(node, dict) or _depth > MAX_DEPTH:
        return None
    if node.get('__typename') == 'TweetTombstone':
        return _tombstone(node, entry_id)
    limited = [a.get('action') for a in _dict(node.get('limitedActionResults')).get('limited_actions') or []
               if isinstance(a, dict)]
    restricted = node.get('__typename') == 'TweetWithVisibilityResults'
    if restricted:
        node = _dict(node.get('tweet'))
    identity = _str(node.get('rest_id'))
    if not identity:
        return None
    legacy = _dict(node.get('legacy'))
    author_node = _dict(_dict(node.get('core')).get('user_results')).get('result')
    author = account_record(author_node) if isinstance(author_node, dict) else None
    note = _dict(_dict(node.get('note_tweet')).get('note_tweet_results')).get('result') or {}
    long_text = isinstance(note, dict) and isinstance(note.get('text'), str)
    entities = _dict(note.get('entity_set')) if long_text and isinstance(note.get('entity_set'), dict) else \
        _dict(legacy.get('entities'))
    media_links = (_dict(legacy.get('extended_entities')).get('media') or []) + \
        (_dict(legacy.get('entities')).get('media') or [])
    links = entities.get('urls') or []
    text = expand(note['text'] if long_text else legacy.get('full_text', ''), links, media_links)
    handle = author['username'] if author and author.get('username') else None
    views = _dict(node.get('views')).get('count')
    reposted = post_record(_dict(legacy.get('retweeted_status_result')).get('result'), _depth=_depth + 1)
    quoted_raw = _dict(node.get('quoted_status_result')).get('result')
    quoted = post_record(quoted_raw, _depth=_depth + 1)
    quoted_id = _str(legacy.get('quoted_status_id_str'))
    if quoted is not None and quoted.get('unavailable') and not quoted.get('id'):
        quoted['id'] = quoted_id
    community = _dict(_dict(node.get('community_results')).get('result'))
    record = {
        'id': identity, 'url': f'{ORIGIN}/{handle or "i/web"}/status/{identity}',
        'created_at': _time(legacy.get('created_at')), 'text': text, 'lang': _str(legacy.get('lang')),
        'author': author, 'is_reply': bool(legacy.get('in_reply_to_status_id_str')),
        'reply_to_id': _str(legacy.get('in_reply_to_status_id_str')),
        'reply_to_author': _str(legacy.get('in_reply_to_screen_name')),
        'root_post_id': _str(legacy.get('conversation_id_str')),
        'reply_count': _int(legacy.get('reply_count')), 'repost_count': _int(legacy.get('retweet_count')),
        'quote_count': _int(legacy.get('quote_count')), 'like_count': _int(legacy.get('favorite_count')),
        'bookmark_count': _int(legacy.get('bookmark_count')), 'view_count': _int(views),
        'media': _media(legacy), 'links': [u.get('expanded_url') or u.get('url') for u in links if isinstance(u, dict)],
        'mentions': mentions(entities),
        'hashtags': [h.get('text') for h in entities.get('hashtags') or [] if isinstance(h, dict)],
        'is_long_post': bool(long_text), 'is_pinned': False,
        'quoted_post': quoted, 'quoted_post_id': quoted_id, 'reposted_post': reposted,
        'community_note': _note(node), 'card': _card(node, links), 'article': _article(node),
        'edit': _edit(node, identity), 'limited_actions': limited, 'restricted': restricted,
        'community': ({'id': _str(community.get('id_str') or community.get('rest_id')),
                       'name': _str(community.get('name'))} if community else None),
        'unavailable': False, 'kind': 'post',
    }
    if reposted is not None:
        # a repost row is the reposter's act: its own id, time and author; the words, media and counts are the
        # original's (reposted_post), never repeated as if the reposter wrote them
        record.update(url=reposted.get('url') or record['url'], text='', media=[], links=[], mentions=[], hashtags=[],
                      is_long_post=False, card=None, article=None, community_note=None,
                      reply_count=None, repost_count=None, quote_count=None, like_count=None, bookmark_count=None,
                      view_count=None)
    return record
