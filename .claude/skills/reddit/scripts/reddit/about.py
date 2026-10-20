"""about: a community's card, rules, moderators and pinned posts, or a user's card — one record, read live, tied to no account state (no
handle, no file), so the Reddit account is not checked first."""
from reddit import connect
from reddit.errors import RedditError
from reddit.reddit_web import parse_target, require


def about(options):
    raw = options['target']
    if '/' not in raw:
        raise RedditError(2, 'about needs r/<name> or u/<name> (a bare word reads as a post id).',
                          'Prefix the name, for example about r/python or about u/someone.')
    target = require(parse_target(raw), ('subreddit', 'user'), 'about')

    def read(connection, state, out):
        client = connection.network()
        if target.kind == 'user':
            return {'results': [client.user(target.user)], 'stop_reason': 'exhausted'}
        card = client.community(target.sub)
        card['rules'] = client.rules(target.sub)
        card['moderators'] = client.moderators(target.sub)
        card['pinned'] = client.pinned(target.sub)
        return {'results': [card], 'stop_reason': 'exhausted'}

    return connect.run(options, command='about', target=target.name, identity={}, reader=read, bound=False)
