"""about: one profile's card — who someone is, as Threads shows it."""
from threads import connect
from threads.threads_web import parse_user


def about(options):
    target = parse_user(options['target'])

    def read(connection, state, out):
        client = connection.client
        user_id, user = client.profile_id(target.username)
        card = client.profile_card(user_id, target.username, fallback=user)
        return {'results': [card], 'stop_reason': 'exhausted'}

    return connect.run(options, command='about', target=target.url, identity={}, reader=read)
