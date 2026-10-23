"""Pictures saved from posts under data/images/, removed 24 hours after they were saved, for every platform.

The skill chooses every file name (platform, post, picture number, a digest, the type's extension), never the URL, so
a picture address cannot write anywhere else. Old files are removed whenever a picture is saved: nobody needs to delete
them by hand. A picture is other people's content.
"""
import hashlib
import os
import time

from sns.errors import SnsError
from sns.paths import shared

TTL_SECONDS = 24 * 3600
MAX_BYTES = 10 * 1024 * 1024
EXTENSIONS = {'image/jpeg': '.jpg', 'image/png': '.png', 'image/gif': '.gif', 'image/webp': '.webp',
              'image/avif': '.avif', 'image/bmp': '.bmp', 'image/heic': '.heic'}


def prune(directory=None):
    """Remove saved pictures older than TTL_SECONDS."""
    directory = directory or shared('images')
    cutoff = time.time() - TTL_SECONDS
    for path in directory.iterdir():
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            pass


def save(data, content_type, *, platform, key, number):
    """Write one picture; returns its path. key names the post on its platform, number its picture number."""
    if len(data) > MAX_BYTES:
        raise SnsError('partial', f'The picture is larger than {MAX_BYTES // (1024 * 1024)} MB and was not saved.',
                       'Open it in the browser instead.', reason='too_large')
    if content_type not in EXTENSIONS:
        raise SnsError('partial', f'The answer was not a picture ({content_type or "no type"}).',
                       'Open it in the browser instead.', reason='not_image')
    directory = shared('images')
    prune(directory)
    digest = hashlib.sha256(f'{platform}:{key}#{number}'.encode()).hexdigest()[:12]
    safe = ''.join(c if c.isalnum() or c in '-_' else '-' for c in str(key))[:80].strip('-') or 'post'
    word = ''.join(c if c.isalnum() else '-' for c in platform)
    path = directory / f'{word}-{safe}-{int(number)}-{digest}{EXTENSIONS[content_type]}'
    temporary = path.with_name('.' + path.name + '.tmp')
    try:
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.replace(temporary, path)
    except OSError:
        raise SnsError('partial', 'A picture could not be saved.', 'Make the skill\'s data/ directory writable.') \
            from None
    return path
