"""images: read a post again and save the pictures it numbers, so the model can look at them (Read the path).

Pictures carry what text does not: a menu's prices, a disclosure banner drawn into a photo or sticker. The post is read
again (its picture addresses are not kept), and each picture is one request. A stop (the time limit, a hold) names the
numbers left, and the printed command saves them.
"""
from sns import reading
from sns.cmdline import command_line, words
from sns.errors import SnsError

from sns.naver_blog import account, web

# A failure that belongs to one picture (gone, too large, not a picture, hosted elsewhere) is noted and the others are
# still saved.
PHOTO_FAILURES = ('photo_unavailable', 'photo_offsite', 'drift')   # and any partial: too large, not a picture, not saved
RESUMABLE = ('time_limit', 'rate_limited')


def images(platform, invocation):
    options = invocation.options
    typed = web.parse_target(options['target'], 'post')
    name = typed.handle or options['target']
    if not options.get('all') and not options.get('numbers'):
        raise SnsError('argument', 'Say which pictures: their numbers as post shows them ([image N]), or --all.',
                       'Run images <post> N [N ...], or images <post> --all.')

    def read(connection, state, out):
        client, results, skipped, kinds = connection.client, [], [], []
        target = client.target(options['target'], 'post')
        doc = web.parse_post(client.get('post_html', blogId=target.blog_id, logNo=target.log_no),
                             blog_id=client.canonical.get(target.blog_id, target.blog_id), log_no=target.log_no)
        account.note_viewer(connection, doc)
        post = f'{doc.blog_id or target.blog_id}/{doc.log_no}'
        pictures = {picture['n']: picture for picture in doc.images}
        if not pictures:
            raise SnsError('empty', 'This post has no pictures.', 'Nothing to save.')
        wanted = sorted(pictures) if options.get('all') else options.get('numbers') or []
        unknown = [n for n in wanted if n not in pictures]
        if unknown:
            raise SnsError('argument', f'This post has no picture {", ".join(map(str, unknown))}.',
                           f'Pass numbers from 1-{max(pictures)} (post shows them as [image N]), or --all.')
        remaining, failure = list(dict.fromkeys(wanted)), None
        while remaining:
            picture = pictures[remaining[0]]
            try:
                data, content_type = client.image(picture['url'])
                path = connection.save_image(data, content_type, key=post, number=picture['n'])
            except SnsError as error:
                if error.kind != 'partial' and error.reason not in PHOTO_FAILURES:
                    failure = error
                    break
                skipped.append(f'image {picture["n"]} not saved — {error.message}')
                kinds.append((error.kind, error.reason))
                remaining.pop(0)
                continue
            results.append(web.Saved(id=f'image:{post}#{picture["n"]}', url=f'https://blog.naver.com/{post}',
                                     n=picture['n'], picture_kind=picture['kind'], caption=picture['caption'],
                                     path=str(path), bytes=len(data), content_type=content_type).to_dict())
            remaining.pop(0)
        if skipped and failure is None and not results and all(kind == ('failed', 'drift') for kind in kinds):
            failure = SnsError('failed', 'No picture could be read: every photo address answered with something other '
                                         'than a picture.', 'Run doctor; the photo hosts\' contract may have changed.',
                               reason='drift')
        elif skipped and failure is None:
            failure = SnsError('partial', f'{len(skipped)} picture(s) could not be saved.',
                               'See the coverage lines; the rest were saved.', reason='photos')
        reading_ = {'results': results, 'stop_reason': 'exhausted', 'failure': failure, 'partial': bool(results),
                    'coverage': skipped + (['the files are other people\'s photos under data/images/, removed once 24 '
                                            'hours old; Read a path to look at it'] if results else [])}
        if remaining and failure is not None and failure.reason in RESUMABLE and results:
            # no handle: the post is read again anyway, so the command that saves the rest is enough
            reading_['continuable'] = True
            reading_['next'] = command_line(invocation.cli_path, words(
                platform.key, 'images', name, [str(n) for n in remaining], options, limit=None))
        return reading_

    return reading.run(platform, invocation, command='images', target=name, identity={'target': name}, reader=read,
                       bound=False)
