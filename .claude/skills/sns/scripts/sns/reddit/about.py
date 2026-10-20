"""about: a community's card, rules, moderators and pinned posts, or a user's card — one record, read live, tied to no
handle or file, so the Reddit account is not checked first."""
from sns import reading
from sns.errors import SnsError

from sns.reddit import web


def about(platform, invocation):
    raw = invocation.options['target']
    if '/' not in raw:
        raise SnsError('argument', 'about needs r/<name> or u/<name> (a bare word reads as a post id).',
                       'Prefix the name, for example about r/python or about u/someone.')
    target = web.require(web.parse_target(raw), 'about')

    def read(connection, state, out):
        client = connection.client
        if target.kind == 'user':
            return {'results': [client.user(target.user)], 'stop_reason': 'exhausted'}
        card = client.community(target.sub)
        card['rules'] = client.rules(target.sub)
        card['moderators'] = client.moderators(target.sub)
        card['pinned'] = client.pinned(target.sub)
        return {'results': [card], 'stop_reason': 'exhausted'}

    return reading.run(platform, invocation, command='about', target=target.name, identity={}, reader=read, bound=False)
