"""The pictures of one post, saved so they can be looked at (S12): the same for every platform.

A platform reads the post again (picture links are signed and expire) and hands its media items in the shared media
contract ({n, kind, image_url, video_url, width, height, alt, media_id}); this saves the ones asked for by number, a
video by its poster, from the platform's own image hosts only, one request each through protection. What could not be
saved is named in coverage and makes the result partial; the saved records say what each picture is, so the reader can
match them with the [image N] lines of the post it read before (the numbers are this read's, not a promise that the
post did not change)."""
from urllib.parse import urlsplit

from sns.errors import SnsError

MAX_BYTES = 10 * 1024 * 1024


def _allowed(url, hosts):
    host = (urlsplit(url or '').hostname or '').lower()
    return bool(host) and any(host == h or host.endswith('.' + h) for h in hosts)


def pictures(connection, *, key, media, numbers, hosts):
    """A reading of the saved pictures: numbers None takes every one; hosts are the platform's image hosts."""
    if not media:
        raise SnsError('empty', 'This post has no pictures to save.', 'Read the post to see what it holds.')
    by_number = {item.get('n'): item for item in media}
    chosen = sorted(by_number) if numbers is None else list(dict.fromkeys(numbers))
    results, skipped = [], []
    for number in chosen:
        item = by_number.get(number)
        if item is None:
            skipped.append(f'picture {number}: this post has {len(media)} (numbers 1–{len(media)})')
            continue
        url = item.get('image_url')
        if not url:
            skipped.append(f'picture {number}: no picture link was sent for this {item.get("kind") or "item"}')
            continue
        if not _allowed(url, hosts):
            skipped.append(f'picture {number}: it is hosted on {urlsplit(url).hostname}, outside this platform\'s '
                           'image hosts, so it was not fetched')
            continue
        try:
            with connection.guard.request(kind='image') as slot:
                try:
                    data, content_type = connection.aside.download(url, MAX_BYTES)
                except SnsError:
                    slot.classify('image_failed')
                    raise
                slot.classify('ok')
            path = connection.save_image(data, content_type, key=key, number=number)
        except SnsError as error:
            if error.kind != 'partial':
                raise
            skipped.append(f'picture {number}: {error.message}')
            continue
        results.append({'kind': 'image', 'id': f'{key}#{number}', 'url': url, 'created_at': None, 'n': number,
                        'media_kind': item.get('kind'), 'media_id': item.get('media_id'), 'alt': item.get('alt'),
                        'width': item.get('width'), 'height': item.get('height'), 'bytes': len(data),
                        'content_type': content_type, 'path': str(path)})
    failure = None
    if skipped:
        failure = SnsError('partial', f'{len(skipped)} of {len(chosen)} pictures were not saved.',
                           'coverage says which and why.', reason='pictures_skipped')
    return {'results': results, 'stop_reason': 'exhausted', 'failure': failure, 'coverage': skipped,
            'partial': bool(results)}


IMAGE_SCHEMA = {'object': 'image', 'description': 'One saved picture of a post ([i] label; <platform> images). The file '
                                                  'is other people\'s content, removed a day after saving.',
                'fields': {
                    'kind, id, url, created_at': 'string — kind image; <post>#<n>; the picture link it was fetched '
                                                 'from; null',
                    'n': 'integer — its number in the post as this read numbered it ([image N])',
                    'media_kind': 'string — photo, video (its poster), gif or the platform\'s own kind',
                    'media_id': 'string|null — the platform\'s id for it, to match the post read before',
                    'alt': 'string|null — the description the post gives it', 'width, height': 'integer|null',
                    'bytes': 'integer', 'content_type': 'string — image/jpeg, image/png, …',
                    'path': 'string — the saved file; Read it to look at the picture'}}
