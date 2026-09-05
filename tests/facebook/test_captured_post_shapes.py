"""Projected live attachment shapes with all values replaced by derive_fixture."""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from _parse import parse_story_nodes
from _post import build_post


@pytest.mark.parametrize('kind', ['photo', 'shared'])
def test_projected_live_post_keeps_attachment_type(kind):
    path = Path(__file__).with_name('fixtures') / f'live_shape_{kind}.ndjson'
    parsed = parse_story_nodes([path.read_bytes()])
    posts = [build_post(parsed.stories[key], captured_at=datetime.now(timezone.utc), source='group')
             for key in parsed.top_level_ids()]
    assert [p.type for p in posts] == [kind]
    assert posts[0].media if kind == 'photo' else posts[0].shared_post is not None
