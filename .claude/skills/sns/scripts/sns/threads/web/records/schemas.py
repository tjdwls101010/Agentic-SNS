"""What each record field means, for `schema post`, `schema account` and `schema notification`."""
from sns.threads.web.records.notifications import SCHEMA as NOTIFICATION

POST = {
    'object': 'post',
    'description': 'A post, reply, parent, quoted or reposted post. A tombstone keeps only id, unavailable and '
                   'unavailable_reason.',
    'fields': {
        'kind': 'string — post',
        'id': 'string — Threads\' numeric id; the shortcode in url encodes it',
        'code': 'string — the shortcode in the post URL',
        'url': 'string|null — the post\'s own URL; post <url> opens exactly this post; null for a tombstone',
        'created_at': 'string|null — when the post was written (UTC ISO); a reposted post carries the original\'s time, '
                      'not when it was reposted; null when Threads sent no time (undated)',
        'text': 'string — the whole text Threads sent',
        'author': 'object|null — the author as an account record (see schema account)',
        'like_count': 'integer|null — null when the author hides counts or Threads sent none',
        'reply_count': 'integer|null — direct replies Threads reports',
        'repost_count, quote_count': 'integer|null — as Threads reports them',
        'media_type': 'string — text, image, video or carousel',
        'media': 'array<{n, kind, image_url, video_url, width, height, alt, media_id}> — n counts this post\'s '
                 'pictures and videos from 1 in Threads\' order (a carousel\'s order; a quoted or reposted post\'s '
                 'are numbered in its own record); kind photo or video; image_url the picture (a video\'s poster); '
                 'video_url the largest video file, null for a photo; alt Threads\' description of it, often '
                 'generated automatically; media_id Threads\' id for the item',
        'link_preview': 'object|null — {url, title} of a linked page; url is the destination, not Threads\' redirect',
        'is_reply': 'boolean — the post answers another post',
        'parent_id': 'string|null — the post this one answers, only when Threads says so',
        'root_post_id': 'string|null — the first post of the thread this one belongs to',
        'reply_level': 'integer|null — how deep Threads places this reply in its thread: 1 answers the thread\'s first post',
        'reply_to_author': 'string|null — the handle of the author this reply answers, as Threads names it',
        'quoted_post': 'object|null — the post this one quotes: two voices, the quoter\'s text and the quoted '
                       'author\'s own',
        'reposted_post': 'object|null — the post this one shares; a repost adds no words',
        'pinned': 'boolean — pinned to its author\'s profile, so it sits first whatever its date',
        'unavailable': 'boolean — a tombstone: deleted, hidden or not visible to this account',
        'unavailable_reason': 'string — a tombstone: why, in the skill\'s words (a cut-off share chain says so too)',
        'role': 'string — post; in a post read: parent (above the post), post, or reply; in quotes: quote (a post quoting the one asked about, its counts and media unknown until post <url>)',
        'depth': 'integer — nesting under the first post of its unit or reply branch; 0 at the top',
        'relation': 'object|null — what a later post of one unit is to an earlier one: {kind: reply | continuation, '
                    'to: id}; continuation is the author continuing their own post',
        'unit': 'string — lists: the id of the first post of the unit (one feed or profile entry) this post came in',
        'replies_handle': 'integer — replies: the handle that opens more replies under this reply',
    },
}

ACCOUNT = {
    'object': 'account',
    'description': 'An account, as an author, a search result, a follower or a profile card.',
    'fields': {
        'kind': 'string — account',
        'id': 'string — Threads\' numeric id; the handle can change, this does not',
        'created_at': 'null — Threads does not publish when an account was made',
        'username': 'string — the handle, without @',
        'full_name': 'string|null — the display name the account chose',
        'is_verified': 'boolean|null — the verified badge: a claim about who this is, not evidence of expertise',
        'private': 'boolean|null — a private profile shows its posts only to accepted followers',
        'follower_count': 'integer|null — as the profile reports it',
        'bio': 'string|null — what the account wrote about itself',
        'bio_links': 'array<string> — links in the bio',
        'friendship_status': 'object — the logged-in account\'s relation to this one, as Threads sends it',
        'profile_pic_url': 'string|null — the profile picture address Threads sent (signed, it expires)',
        'url': 'string|null — the profile URL',
        'reposted_at': 'string — in reposts only: when the account reposted the post, ISO 8601 UTC',
        'counts': 'object — about only: {followers, following, mutuals}; Threads publishes no following or mutual '
                  'count, so those are null (unknown); graph following lists the accounts',
    },
}

SCHEMAS = {'post': POST, 'account': ACCOUNT, 'notification': NOTIFICATION}
