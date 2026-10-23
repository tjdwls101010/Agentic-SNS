"""images: the pictures of one post, saved to look at (S12) — the post read again by id, then each picture."""
from sns import reading
from sns.errors import SnsError
from sns.x import web

HOSTS = ('pbs.twimg.com',)  # X's image host: photos and videos' posters (measured 2026-10-21)


def images(platform, invocation):
    options = invocation.options
    target = web.parse_post(options['target'])
    numbers = options.get('numbers') or None
    if numbers is None and not options.get('all'):
        raise SnsError('argument', 'Name the pictures to save by number, or take them all.',
                       'Add the numbers ([image N] in the post), or --all.')

    def read(connection, state, out):
        records, _ = connection.client.posts([target.post_id])
        if not records:
            raise SnsError('unavailable', 'X did not return this post to this account (deleted, protected or never '
                                          'existed).', 'Check the link.', reason='unavailable')
        return reading.pictures(connection, key=target.post_id, media=records[0].get('media') or [],
                                numbers=None if options.get('all') else numbers, hosts=HOSTS)

    return reading.run(platform, invocation, command='images', target=target.post_id, identity={}, reader=read,
                       bound=False)
