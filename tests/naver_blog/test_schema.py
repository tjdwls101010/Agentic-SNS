"""schema is derived from the objects; a hand-kept field list would drift silently."""
import json
import subprocess
import sys
from pathlib import Path

import pytest

from naver_blog_skill._entities import Blog, Buddy, Category, Topic
from naver_blog_skill._models import Comment, Post
from naver_blog_skill._schema import STOP_REASONS, schema

ENTRY = Path(__file__).resolve().parents[2] / '.claude/skills/naver-blog/scripts/naver_blog.py'
CLASSES = {'Post': Post, 'Comment': Comment, 'Blog': Blog, 'Category': Category,
           'Buddy': Buddy, 'Topic': Topic}


@pytest.mark.parametrize('name,cls', CLASSES.items())
def test_every_documented_field_comes_from_the_object_itself(name, cls):
    """Adding a field to a dataclass must show up here without anyone remembering to add it."""
    described = set(schema()['$defs'][name]['properties'])
    assert described == set(cls().to_dict())


def test_every_field_carries_a_description_rather_than_its_own_name_repeated():
    for name in CLASSES:
        for key, field in schema()['$defs'][name]['properties'].items():
            assert field['description'].strip(), f'{name}.{key}'
            assert field['description'] != key


def test_every_documented_stop_reason_is_one_the_walker_actually_produces():
    from naver_blog_skill import _listing
    source = Path(_listing.__file__).read_text()
    undocumented = [reason for reason in STOP_REASONS if f"'{reason}'" not in source]
    assert undocumented == [], undocumented
    assert set(schema()['$defs']['ReadResult']['properties']['stop_reason']['enum']) == set(STOP_REASONS)


def test_schema_makes_no_request_at_all(cli_env):
    log = Path(cli_env['NAVER_BLOG_FAKE_LOG'])
    result = subprocess.run([sys.executable, str(ENTRY), 'schema'], capture_output=True, text=True, env=cli_env)
    assert result.returncode == 0
    assert not log.exists()
    assert json.loads(result.stdout)['ok'] is True


def test_schema_says_what_unknown_means_because_a_summary_depends_on_it():
    described = schema()['unknown']
    assert 'null' in described and 'unknown' in described
