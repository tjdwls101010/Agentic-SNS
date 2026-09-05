"""Tweet normalization preserves the reposter identity and original content."""
from dataclasses import dataclass, field
from ._entities import Record, User, build_user, timestamp


@dataclass
class Media(Record):
    kind: str = 'photo'
    url: str = ''
    width: int | None = None
    height: int | None = None
    alt_text: str | None = None


@dataclass
class Tweet(Record):
    id: str = ''
    url: str | None = None
    created_at: str | None = None
    text: str = ''
    lang: str | None = None
    author: User | None = None
    is_reply: bool = False
    in_reply_to_id: str | None = None
    in_reply_to_screen_name: str | None = None
    conversation_id: str | None = None
    reply_count: int | None = None
    retweet_count: int | None = None
    quote_count: int | None = None
    like_count: int | None = None
    bookmark_count: int | None = None
    view_count: int | None = None
    media: list[Media] = field(default_factory=list)
    urls: list = field(default_factory=list)
    entities: dict = field(default_factory=dict)
    hashtags: list = field(default_factory=list)
    is_note_tweet: bool = False
    is_pinned: bool = False
    retweeted_tweet: 'Tweet | None' = None
    quoted_tweet: 'Tweet | None' = None
    quoted_tweet_id: str | None = None
    limited_actions: list = field(default_factory=list)
    is_restricted: bool = False
    community: dict | None = None
    kind: str = 'tweet'


def build_tweet(node, pinned=False, _depth=0):
    if not isinstance(node, dict) or _depth > 5 or node.get('__typename') == 'TweetTombstone':
        return None
    limited = node.get('limitedActionResults', {}).get('limited_actions', [])
    restricted = node.get('__typename') == 'TweetWithVisibilityResults'
    if restricted:
        node = node.get('tweet', {})
    if not node.get('rest_id'):
        return None
    legacy = node.get('legacy', {})
    author_node = node.get('core', {}).get('user_results', {}).get('result')
    author = build_user(author_node) if author_node else None
    original = build_tweet(legacy.get('retweeted_status_result', {}).get('result'), _depth=_depth + 1)
    quote = build_tweet(node.get('quoted_status_result', {}).get('result'), _depth=_depth + 1)
    note = node.get('note_tweet', {}).get('note_tweet_results', {}).get('result', {})
    entities = note.get('entity_set') or legacy.get('entities', {})
    media = []
    for item in legacy.get('extended_entities', {}).get('media', []):
        variants = [v for v in item.get('video_info', {}).get('variants', []) if v.get('content_type') == 'video/mp4']
        url = max(variants, key=lambda v: v.get('bitrate', 0))['url'] if variants else item.get('media_url_https', '')
        size = item.get('original_info', {})
        media.append(Media(item.get('type', 'photo'), url, size.get('width'), size.get('height'), item.get('ext_alt_text')))
    result = Tweet(id=node['rest_id'], url=f'https://x.com/{author.screen_name if author else "i/web"}/status/{node["rest_id"]}',
                   created_at=timestamp(legacy.get('created_at')), text=note.get('text', legacy.get('full_text', '')),
                   lang=legacy.get('lang'), author=author, is_reply=bool(legacy.get('in_reply_to_status_id_str')),
                   in_reply_to_id=legacy.get('in_reply_to_status_id_str'), in_reply_to_screen_name=legacy.get('in_reply_to_screen_name'),
                   conversation_id=legacy.get('conversation_id_str'),
                   **{key: legacy.get(source) for key, source in [('reply_count', 'reply_count'), ('retweet_count', 'retweet_count'), ('quote_count', 'quote_count'), ('like_count', 'favorite_count'), ('bookmark_count', 'bookmark_count')]},
                   view_count=int(node['views']['count']) if str(node.get('views', {}).get('count', '')).isdigit() else None,
                   media=media, entities=entities, urls=[u.get('expanded_url', u.get('url')) for u in entities.get('urls', [])],
                   hashtags=[h.get('text') for h in entities.get('hashtags', [])], is_note_tweet=bool(note.get('text')),
                   is_pinned=pinned, retweeted_tweet=original, quoted_tweet=quote, quoted_tweet_id=legacy.get('quoted_status_id_str'),
                   limited_actions=[a.get('action') for a in limited], is_restricted=restricted,
                   community=node.get('community_results', {}).get('result'))
    if original:
        for key in ('url', 'text', 'media', 'urls', 'entities', 'hashtags', 'lang', 'reply_count', 'retweet_count', 'quote_count', 'like_count', 'bookmark_count', 'view_count', 'is_note_tweet'):
            setattr(result, key, getattr(original, key))
    return result
