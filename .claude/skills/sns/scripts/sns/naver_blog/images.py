"""images: read a post again and save the pictures it numbers, so the model can look at them (Read the path).

Pictures carry what text does not: a menu's prices, a disclosure banner drawn into a photo or sticker. The post is read
again (its picture addresses are not kept); saving is the shared reading.pictures, each picture fetched through
Naver's own guarded and classified request (one each). A stop (the time limit, a hold) names the numbers left.
"""
from sns import reading
from sns.errors import SnsError

from sns.naver_blog import account, web

HOSTS = ('pstatic.net',)
# A failure that belongs to one picture (gone, hosted elsewhere, not a picture) is noted and the others are still saved.
PHOTO_FAILURES = ('photo_unavailable', 'photo_offsite', 'drift')


def images(platform, invocation):
    options = invocation.options
    typed = web.parse_target(options['target'], 'post')
    name = typed.handle or options['target']
    if not options.get('all') and not options.get('numbers'):
        raise SnsError('argument', 'Say which pictures: their numbers as post shows them ([image N]), or --all.',
                       'Run images <post> N [N ...], or images <post> --all.')

    def read(connection, state, out):
        client = connection.client
        target = client.target(options['target'], 'post')
        doc = web.parse_post(client.get('post_html', blogId=target.blog_id, logNo=target.log_no),
                             blog_id=client.canonical.get(target.blog_id, target.blog_id), log_no=target.log_no)
        account.note_viewer(connection, doc)
        reasons = []

        def fetch(url):
            try:
                return client.image(url)
            except SnsError as error:
                if error.kind != 'partial' and error.reason not in PHOTO_FAILURES:
                    raise
                reasons.append(error.reason)
                raise SnsError('partial', error.message, error.fix, reason=error.reason) from None

        media = [{'n': p['n'], 'kind': p['kind'], 'image_url': p['url'], 'video_url': None, 'width': None,
                  'height': None, 'alt': p['caption'], 'media_id': None} for p in doc.images]
        result = reading.pictures(connection, key=f'{doc.blog_id or target.blog_id}/{doc.log_no}', media=media,
                                  numbers=None if options.get('all') else options.get('numbers'), hosts=HOSTS,
                                  fetch=fetch)
        if not result['results'] and reasons and all(reason == 'drift' for reason in reasons):
            raise SnsError('failed', 'No picture could be read: every photo address answered with something other '
                                     'than a picture.', 'Run doctor; the photo hosts\' contract may have changed.',
                           reason='drift')
        return result

    return reading.run(platform, invocation, command='images', target=name, identity={'target': name}, reader=read,
                       bound=False)
