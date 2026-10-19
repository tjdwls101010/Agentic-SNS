"""feed, sub, profile, me and related: listings read page by page in Reddit's order (connect.read_pages)."""
from reddit import connect
from reddit.errors import RedditError
from reddit.reddit_web import (FEED_SORTS, ME_COLLECTIONS, PROFILE_SORTS, PROFILE_TYPES, SUB_SORTS, TIMES, parse_target,
                               require, routes)



def feed(options):
    sort = options.get('sort') or 'best'
    identity = {'sort': sort, 'time': options.get('time'), 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        return connect.read_pages(connection, options, identity, state, out, command='feed', target=None,
                     request=lambda after: routes.feed(sort, options.get('time'), after))

    return connect.run(options, command='feed', target=None, identity=identity, reader=read)


def sub(options):
    target = require(parse_target(options['target']), ('subreddit', 'subreddits'), 'sub')
    sort = options.get('sort') or 'hot'
    identity = {'sort': sort, 'time': options.get('time'), 'since': options.get('since'), 'until': options.get('until')}

    def read(connection, state, out):
        return connect.read_pages(connection, options, identity, state, out, command='sub', target=target.name,
                     request=lambda after: routes.listing(target.sub, sort, options.get('time'), after))

    return connect.run(options, command='sub', target=target.name, identity=identity, reader=read)


def related(options):
    """Other posts of the same link (crossposts and duplicates), in other communities or the same one."""
    target = require(parse_target(options['target']), ('post', 'comment'), 'related')

    def read(connection, state, out):
        return connect.read_pages(connection, options, {}, state, out, command='related', target=target.name,
                     request=lambda after: routes.related(target.post_id, after))

    return connect.run(options, command='related', target=target.name, identity={}, reader=read)


def me(options):
    """The user's own subscriptions, saved or upvoted items, read under the logged-in name."""
    collection = options['collection']
    identity = {'collection': collection}

    def read(connection, state, out):
        connection.network()  # the account check names whose lists these are
        return connect.read_pages(connection, options, identity, state, out, command='me', target=None, words=[collection],
                     request=lambda after: routes.mine(collection, connection.reddit_account, after))

    return connect.run(options, command='me', target=None, identity=identity, reader=read)


_KARMA = {'overview': ('activity', 'karma', ('post_karma', 'comment_karma')),
          'posts': ('posts', 'post karma', ('post_karma',)),
          'comments': ('comments', 'comment karma', ('comment_karma',))}


def profile(options):
    """A redditor's public activity. A first unfiltered page that comes back empty is judged against the account's
    karma for that kind (one more request): karma means the history is hidden from other accounts or was deleted
    (exit 9), no karma is only what was observed (exit 7)."""
    target = require(parse_target(options['target']), ('user',), 'profile')
    kind = options.get('type') or 'overview'
    sort = options.get('sort') or 'new'
    identity = {'type': kind, 'sort': sort, 'time': options.get('time'), 'since': options.get('since'),
                'until': options.get('until')}
    unfiltered = not (options.get('after') or options.get('since') or options.get('until') or options.get('time'))

    def read(connection, state, out):
        reading = connect.read_pages(connection, options, identity, state, out, command='profile', target=target.name,
                        request=lambda after: routes.profile(target.user, kind, sort, options.get('time'), after))
        failure = reading.get('failure')
        if unfiltered and out is None and failure is not None and failure.code == 7:
            reading['failure'] = _history(connection, target.user, kind)
        return reading

    return connect.run(options, command='profile', target=target.name, identity=identity, reader=read)


def _history(connection, name, kind):
    """The error an empty first page means, from the karma of that kind."""
    noun, karma_name, fields = _KARMA[kind]
    try:
        card = connection.network().user(name)
    except RedditError as error:
        if error.code == 8:
            return RedditError(8, 'The list was empty and karma could not be checked within the budget.',
                               'Rerun the same command (with a larger --max-requests if needed) to tell a hidden '
                               'history from an empty one.', reason='karma_unchecked')
        return error
    karma = sum(card.get(field) or 0 for field in fields)
    if karma > 0:
        return RedditError(9, f'no visible {noun} although {karma_name} is {karma:g}: the history is hidden from other '
                              'accounts or was deleted', f'Tell the user; about u/{name} still reads the account\'s '
                                                         'card (karma, age).', reason='history_not_visible')
    return RedditError(7, f'no visible {noun}; {karma_name} is 0', 'An empty history here is what was observed, not '
                                                                  'proof the account never posted.')


__all__ = ['FEED_SORTS', 'ME_COLLECTIONS', 'PROFILE_SORTS', 'PROFILE_TYPES', 'SUB_SORTS', 'TIMES', 'feed', 'me',
           'profile', 'related', 'sub']
