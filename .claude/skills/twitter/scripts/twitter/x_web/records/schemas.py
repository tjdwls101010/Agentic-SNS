"""What each record field means, for `schema post`, `schema account` and `schema trend`."""

NULL = 'null when X did not report it, which is not 0'

POST = {
    'object': 'post',
    'description': 'A post, reply, parent, quoted or reposted post. A tombstone keeps only id (when known), unavailable '
                   'and unavailable_reason.',
    'fields': {
        'id': 'string — X\'s post id; post <id> opens it',
        'url': 'string — the post\'s own URL (a repost row: the original\'s); post <url> opens exactly that post',
        'created_at': 'string|null — when it was written, UTC ISO; a repost row\'s is when it was reposted',
        'text': 'string — the whole text X sent, t.co links expanded and media links removed; a long post\'s full text; '
                'a repost row\'s is empty (the words are the original\'s, in reposted_post)',
        'lang': 'string|null — X\'s guess of the text\'s language',
        'author': 'object|null — who acted, as an account record: for a repost row the reposter, not the writer',
        'reply_count, repost_count, quote_count, like_count, bookmark_count, view_count':
            'integer|null — as X reports them, ' + NULL + '; a repost row has none of its own (see reposted_post)',
        'media': 'array<{kind, url, width, height, alt_text}> — kind photo, video or animated_gif; url the largest '
                 'MP4 for a video; alt_text the description the author (or X) wrote',
        'links': 'array<string> — link destinations in the text',
        'mentions': 'array<string> — handles mentioned, without @, in order, each once',
        'hashtags': 'array<string>',
        'is_long_post': 'boolean — X sent the full text of a long post (not a clipped preview)',
        'is_reply': 'boolean — it answers another post',
        'reply_to_id': 'string|null — the post it answers',
        'reply_to_author': 'string|null — the handle of that post\'s author, as X names it',
        'root_post_id': 'string|null — the first post of the conversation it belongs to',
        'quoted_post': 'object|null — the post it quotes, a record of its own: two voices, the quoter\'s words and '
                       'the quoted author\'s; unavailable when that post is gone',
        'quoted_post_id': 'string|null — the quoted post\'s id even when X left out its body (post <id> opens it)',
        'reposted_post': 'object|null — the post a repost row shares: its words, media, counts and original time',
        'community_note': 'object|null — a community note shown under the post {id, title, text, url}: context other '
                          'users added and rated helpful, not the author\'s words; no note does not mean the post '
                          'was checked',
        'card': 'object|null — a card: {kind, title, description, domain, url} for a link preview (url the '
                'destination), {kind, poll: {choices: [{label, count}], final, ends_at}} for a poll (poll fields '
                'follow X\'s known card keys and were not seen live when this skill was built), {kind, space_url} '
                'for a space',
        'article': 'object|null — an X article: {id, title, preview, text}; text is the whole article in a post read '
                   '(null in lists, where X sends the title and preview only)',
        'edit': 'object|null — the post was edited: {versions (ids, oldest first), latest (whether this is the newest)}; '
                'post <id> opens any version',
        'limited_actions': 'array<string> — actions X restricts on this post (Reply, Retweet, …)',
        'restricted': 'boolean — X shows the post with limited visibility',
        'community': 'object|null — {id, name} of the community it was posted in',
        'is_pinned': 'boolean — pinned to the author\'s profile, so it sits first whatever its date',
        'unavailable': 'boolean — a tombstone: deleted, withheld or not visible to this account',
        'role': 'string — in a post read: parent (above the post), post, or reply',
        'depth': 'integer — a reply\'s place in its conversation thread: 0 answers the post, later ones sit under it',
        'parent_shown': 'boolean — replies: whether the post it answers was shown (X can skip posts in a thread)',
        'replies_handle': 'integer — replies <handle> reads what hangs under this reply',
        'unit': 'string — lists: the timeline entry or module it came in (a self-thread shares one)',
    },
}

ACCOUNT = {
    'object': 'account',
    'description': 'An account, as an author, a search result, a follower or a profile card.',
    'fields': {
        'id': 'string — X\'s account id; the handle can change, this does not',
        'username': 'string — the handle, without @',
        'full_name': 'string|null — the display name the account chose',
        'created_at': 'string|null — when the account was made, UTC ISO',
        'follower_count, following_count, post_count, media_count, like_count': 'integer|null — ' + NULL,
        'is_blue_verified': 'boolean — the blue check: a paid X subscription, not an identity check',
        'verified_type': 'string|null — Business or Government: an organisation badge X grants, unlike the paid check',
        'is_verified': 'boolean — X\'s separate verified flag',
        'declared_label': 'string|null — a label the account declared about itself: Parody, Commentary or Fan',
        'affiliation': 'object|null — {label, url}: the organisation X shows next to the name',
        'private': 'boolean — protected: only approved followers see its posts',
        'bio': 'string|null — what the account wrote about itself, links expanded',
        'location, website': 'string|null — as the account wrote them',
        'url': 'string — the profile URL',
        'avatar_url, banner_url': 'string|null',
        'relationship': 'object — the logged-in account\'s relation to this one: {following, followed_by, blocking, '
                        'muting, follow_request_sent}; null when X did not say',
        'pinned_post_ids': 'array<string> — the pinned post',
        'unavailable': 'boolean — suspended, deactivated or not visible (unavailable_reason says which, when X does)',
        'role': 'string — on a community\'s about tab: moderator or member',
    },
}

TREND = {
    'object': 'trend',
    'description': 'A trend or an event on X\'s Explore tabs: what X shows this account as popular now, not a measure.',
    'fields': {
        'kind': 'string — trend or event',
        'name': 'string — the trend\'s words, or the event\'s title',
        'context': 'string|null — X\'s label (topic, place, "Trending")',
        'description': 'string|null — X\'s line under it (often a post count, rounded)',
        'rank': 'integer|null — its place on the tab',
        'query': 'string|null — trends: the words search takes to read it (search "<query>")',
        'url': 'string|null — an event\'s x.com page',
    },
}

LIST = {
    'object': 'list',
    'description': 'An X list: a set of accounts someone curated, with its own feed of their posts.',
    'fields': {
        'kind': 'string — list',
        'id': 'string — the list id (list <id> reads it)',
        'name': 'string|null',
        'description': 'string|null',
        'private': 'boolean|null — a private list is seen only by its owner',
        'member_count': 'integer|null — ' + NULL,
        'follower_count': 'integer|null — accounts following the list; ' + NULL,
        'created_at': 'string|null — UTC ISO',
        'owner': 'object|null — {id, username, name} of the account that made it',
        'you_follow': 'boolean|null — this account follows the list',
        'you_are_member': 'boolean|null — this account is one of its members',
        'url': 'string — x.com/i/lists/<id>',
    },
}

COMMUNITY = {
    'object': 'community',
    'description': 'An X community: a group with its own feed, members, moderators and rules.',
    'fields': {
        'kind': 'string — community',
        'id': 'string — the community id (community <id> reads it)',
        'name': 'string|null',
        'description': 'string|null',
        'member_count': 'integer|null — ' + NULL,
        'moderator_count': 'integer|null — ' + NULL,
        'created_at': 'string|null — UTC ISO',
        'open_to_join': 'boolean|null — false: joining needs a moderator\'s approval',
        'join_policy': 'string|null — X\'s own value',
        'nsfw': 'boolean|null',
        'your_role': 'string|null — this account\'s place: not a member, member, moderator or admin',
        'topic': 'string|null — the topic X files it under',
        'rules': 'array — the rules\' titles',
        'creator': 'object|null — {id, username, name}',
        'url': 'string — x.com/i/communities/<id>',
    },
}

SCHEMAS = {'post': POST, 'account': ACCOUNT, 'trend': TREND, 'list': LIST, 'community': COMMUNITY}
