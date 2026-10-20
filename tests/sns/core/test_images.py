"""Saved pictures (sns.images): names the skill chooses, private files, a size cap, a 24-hour life."""
import os
import time

import pytest

from sns import images
from sns.errors import SnsError


def test_a_picture_is_saved_under_a_name_the_skill_chooses(data_dir):
    path = images.save(b'\xff\xd8jpeg', 'image/jpeg', platform='naver_blog', key='../../etc/passwd', number=3)
    assert path.parent == data_dir / 'images' and path.suffix == '.jpg'
    assert path.name.startswith('naver-blog-') and '/' not in path.name and '..' not in path.name.replace('...', '')
    assert path.read_bytes() == b'\xff\xd8jpeg' and path.stat().st_mode & 0o077 == 0


def test_too_large_or_not_a_picture_is_refused(data_dir):
    with pytest.raises(SnsError) as caught:
        images.save(b'0' * (images.MAX_BYTES + 1), 'image/png', platform='x', key='1', number=1)
    assert caught.value.reason == 'too_large'
    with pytest.raises(SnsError) as caught:
        images.save(b'<html>', 'text/html', platform='x', key='1', number=1)
    assert caught.value.reason == 'not_image'


def test_pictures_older_than_a_day_go_when_another_is_saved(data_dir):
    old = images.save(b'a', 'image/png', platform='x', key='1', number=1)
    past = time.time() - images.TTL_SECONDS - 5
    os.utime(old, (past, past))
    images.save(b'b', 'image/png', platform='x', key='2', number=1)
    assert not old.exists()
