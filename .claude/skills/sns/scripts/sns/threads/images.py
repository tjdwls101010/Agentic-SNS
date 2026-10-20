"""images: the pictures of one post, saved to look at (S12) — the post read again, then each picture."""
from sns import reading
from sns.errors import SnsError
from sns.threads import web

HOSTS = ('cdninstagram.com', 'fbcdn.net')  # Threads' image hosts (measured 2026-10-21: signed links, no cookies needed)


def images(platform, invocation):
    options = invocation.options
    target = web.parse_post(options['target'])
    numbers = options.get('numbers') or None
    if numbers is None and not options.get('all'):
        raise SnsError('argument', 'Name the pictures to save by number, or take them all.',
                       'Add the numbers ([image N] in the post), or --all.')

    def read(connection, state, out):
        page = connection.client.post_page(target, sort='top', limit=0)
        record = next((r for r in page.records if r.get('role') == 'post'), None)
        if record is None:
            raise SnsError('unavailable', 'This post is unavailable: deleted, or not visible to this account.',
                           'Tell the user; retrying will not change it.', reason='unavailable')
        return reading.pictures(connection, key=target.post_id, media=record.get('media') or [],
                                numbers=None if options.get('all') else numbers, hosts=HOSTS)

    return reading.run(platform, invocation, command='images', target=target.url, identity={}, reader=read,
                       bound=False)
