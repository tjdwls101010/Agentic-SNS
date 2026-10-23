"""images: the pictures of one post, saved to look at (S12) — the post read again lightly, then each picture."""
from sns import reading
from sns.errors import SnsError
from sns.reddit import web

# Reddit's own image hosts (a gallery's pictures, a video's or link's preview): measured 2026-10-21, no cookies needed.
HOSTS = ('i.redd.it', 'preview.redd.it')


def images(platform, invocation):
    options = invocation.options
    target = web.require(web.parse_target(options['target']), 'images')
    numbers = options.get('numbers') or None
    if numbers is None and not options.get('all'):
        raise SnsError('argument', 'Name the pictures to save by number, or take them all.',
                       'Add the numbers ([image N] or "media N:" in the post), or --all.')

    def read(connection, state, out):
        found = connection.client.resolve(target)  # a share link costs its hops
        record = connection.client.post_alone(found.post_id)
        return reading.pictures(connection, key=found.post_id, media=record.get('media') or [],
                                numbers=None if options.get('all') else numbers, hosts=HOSTS)

    name = target.name if target.kind != 'share' else target.url
    return reading.run(platform, invocation, command='images', target=name, identity={}, reader=read, bound=False)
