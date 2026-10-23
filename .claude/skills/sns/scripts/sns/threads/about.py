"""about: one profile's card — who someone is, as Threads shows it."""
from sns import reading
from sns.threads import web


def about(platform, invocation):
    target = web.parse_user(invocation.options['target'])

    def read(connection, state, out):
        client = connection.client
        user_id, user = client.profile_id(target.username)
        card = client.profile_card(user_id, target.username, fallback=user)
        return {'results': [card], 'stop_reason': 'exhausted'}

    return reading.run(platform, invocation, command='about', target=target.url, identity={}, reader=read, bound=False)
