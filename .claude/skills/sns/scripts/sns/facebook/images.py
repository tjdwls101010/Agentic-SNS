"""images: the pictures of one post, saved to look at (S12) — the post read again, then each picture."""
from sns import reading
from sns.errors import SnsError
from sns.facebook import web

HOSTS = ('fbcdn.net',)  # Facebook's image hosts (measured 2026-10-21: signed links, no cookies needed)


def images(platform, invocation):
    options = invocation.options
    target = web.normalize_post(options['target'])
    numbers = options.get('numbers') or None
    if numbers is None and not options.get('all'):
        raise SnsError('argument', 'Name the pictures to save by number, or take them all.',
                       'Add the numbers ([image N] in the post), or --all.')

    def read(connection, state, out):
        client = connection.client
        record, _ = client.permalink(client.resolve('post', target), target)
        return reading.pictures(connection, key=record['id'], media=record.get('media') or [],
                                numbers=None if options.get('all') else numbers, hosts=HOSTS)

    return reading.run(platform, invocation, command='images', target=target, identity={}, reader=read, bound=False)
