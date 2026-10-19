"""doctor and schema."""
from reddit import guard as protection
from reddit.collection import describe as describe_out
from reddit.connect import Connection
from reddit.errors import RedditError
from reddit.paths import data_dir
from reddit.results import describe as describe_result
from reddit.results import finish

SCHEMA_OBJECTS = ['result', 'out', 'post', 'comment', 'subreddit', 'user']


def doctor(options):
    """Check Aside, login and account protection; with --unblock, the one check that may lift a challenge."""
    connection, reading = None, None
    try:
        connection = Connection(protection.MAX_BUDGET, options.get('verbose'))
        if options.get('unblock'):
            with connection.guard.verify_unblock() as check:
                connection.reddit_account = connection.client.account()  # runs inside the check's critical section
                check.clear()
        else:
            connection.start()
        state, recent = connection.guard.state(), connection.guard.recent()
        check = {
            'aside': 'available', 'aside_account': connection.account, 'login': 'ready',
            'reddit_account': connection.reddit_account, 'blocked': state['blocked'],
            'block_reason': state['block_reason'], 'unblocked': bool(options.get('unblock')),
            'buckets': state['buckets'], 'requests_last_hour': recent['last_hour'],
            'requests_last_day': recent['last_day'], 'data_dir': str(data_dir()),
            'snapshot_bytes': _size(data_dir() / 'snapshots'),
            'protection_state': 'data/protection/ — blocks, Reddit\'s bucket states, pacing and the request log shared '
                                'by every invocation of an Aside account; never delete it',
            'holds_personal_data': 'data/handles/ and data/snapshots/ — continuation handles and comment threads with '
                                   'other people\'s words; they expire after a day on their own',
        }
        reading = {'results': [check], 'stop_reason': 'ready'}
    except RedditError as error:
        reading = {'results': [], 'failure': error}
    report = {'requests': connection.guard.used, 'reddit': connection.guard.window()} if connection else \
        {'requests': 0, 'reddit': {}}
    return finish(reading, command='doctor', budget=protection.MAX_BUDGET, **report)


def _size(path):
    try:
        return sum(p.stat().st_size for p in path.rglob('*.json') if p.is_file())
    except OSError:
        return None


def schema(options):
    """One object's schema, or the list of objects; no request. options['exit_codes'] is cli.py's declaration."""
    documents = {'result': describe_result(options.get('exit_codes') or []), 'out': describe_out(), **RECORDS}
    name = options.get('object')
    results = [documents[name]] if name else [{'object': key, 'description': doc['description']}
                                               for key, doc in documents.items()]
    return finish({'results': results, 'stop_reason': 'complete'}, command='schema', requests=0, budget=0)


RECORDS = {
    'post': {'object': 'post', 'description': 'A post ([p] label).', 'fields': {
        'id': 'string — the Reddit fullname t3_<id>; a comment with the same base id (t1_) is a different thing',
        'url': 'string — the post\'s permalink: post <url> opens it in full with its comments',
        'title, text': 'string — as received (text is the body of a text post; [removed] or [deleted] when gone)',
        'subreddit, author': 'string — the community and the account that posted it ([deleted] when unknown)',
        'created_at, edited_at': 'string|null — UTC ISO-8601',
        'score, upvote_ratio': 'number|null — as Reddit shows them; null when not sent',
        'num_comments': 'number|null — Reddit\'s total, deleted and removed comments included; not the number read',
        'post_type': 'string — self, link, image, gallery, video, poll, crosspost (or another post_hint)',
        'link_url, domain': 'string — where a link post points; a crosspost\'s is the original\'s permalink',
        'flair': 'string|null — the post\'s flair in that community',
        'nsfw, spoiler, locked, archived, pinned': 'boolean — markers; NSFW posts are shown, never filtered',
        'distinguished': 'string|null — moderator or admin when posted in that role',
        'removed': 'string|null — why a post is gone (moderator, deleted, automod_filtered, reddit ...)',
        'contest_mode': 'boolean — comments come in random order with scores hidden',
        'suggested_sort': 'string|null — the comment order the moderators chose for this thread',
        'num_crossposts, num_duplicates': 'number|null — other discussions of the same link (related reads them)',
        'media': 'array — [{url, caption}]; nothing is downloaded',
        'poll': 'object|null — {options [{text, vote_count|null}], total_vote_count, voting_ends_at}',
        'crosspost': 'object|null — the original post (its own author and community)'}},
    'comment': {'object': 'comment', 'description': 'A comment ([c] label).', 'fields': {
        'id': 'string — the Reddit fullname t1_<id>',
        'url': 'string — the comment\'s permalink: comments <url> opens it in full with what hangs under it',
        'parent_id': 'string — the fullname it answers (t1_ a comment, t3_ the post)', 'post_id': 'string — t3_<id>',
        'text': 'string — as received; > lines quote someone else ([removed] or [deleted] when gone)',
        'author, subreddit': 'string', 'created_at, edited_at': 'string|null — UTC ISO-8601',
        'score': 'number|null', 'score_hidden': 'boolean — the community hides new comments\' scores for a while',
        'depth': 'integer — 0 for a comment on the post',
        'is_op': 'boolean — written by the post\'s author', 'distinguished': 'string|null — moderator or admin',
        'author_flair': 'string|null — what the author says about themselves in that community',
        'pinned, locked': 'boolean', 'collapsed': 'boolean — Reddit folds it by default',
        'collapsed_reason': 'string|null — Reddit\'s reason code (LOW_SCORE, DELETED ...), sent even when not folded',
        'controversial': 'boolean — many votes both ways', 'removed': 'string|null — removed (by moderators or Reddit) '
        'or deleted (by its author)', 'media': 'array — images posted in the comment'}},
    'subreddit': {'object': 'subreddit', 'description': 'A community ([s] label).', 'fields': {
        'id': 'string — t5_<id>', 'name, url, title': 'string', 'text': 'string — the short description',
        'description': 'string — the sidebar', 'subscribers, active': 'number|null',
        'created_at': 'string|null', 'nsfw': 'boolean', 'visibility': 'string — public, restricted, private ...',
        'rules': 'array — about only: [{name, text, applies_to}]'}},
    'user': {'object': 'user', 'description': 'A redditor ([u] label). A public history is that account\'s observed '
                                              'activity; a profile may hide it, or hide some communities from it.',
             'fields': {'id': 'string — t2_<id>', 'name, url': 'string',
                        'post_karma, comment_karma': 'number|null — karma earned by posts and by comments',
                        'created_at': 'string|null', 'text': 'string — the profile description',
                        'moderator, admin, verified': 'boolean'}},
}
