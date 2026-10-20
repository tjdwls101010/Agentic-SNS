"""The protection bridge between the five old skills and sns (contrast/sns/legacy_state.py)."""
import importlib
import json
import os
import sys
import time
from pathlib import Path

import pytest

from contrast.sns import legacy_state
from sns.clock import Deadline


@pytest.fixture
def world(tmp_path, data_dir):
    """A repository with the old skills' data/ folders and a HOME with the old caches; the active account is u3."""
    repo, home = tmp_path / 'repo', tmp_path / 'home'
    for name in ('threads', 'twitter', 'reddit/u0'):
        (repo / '.claude/skills' / name.split('/')[0] / 'data/protection' / '/'.join(name.split('/')[1:])).mkdir(
            parents=True, exist_ok=True)
    for name in ('facebook-skill', 'naver-blog-skill'):
        (home / '.cache' / name).mkdir(parents=True)
    return legacy_state.Sources(repo=repo, home=home, active='u3', environ={})


def old(world, platform, name='blocked.json'):
    return {'threads': world.skill('threads'), 'x': world.skill('twitter'), 'reddit': world.skill('reddit') / 'u0',
            'facebook': world.home / '.cache/facebook-skill', 'naver_blog': world.home / '.cache/naver-blog-skill'
            }[platform] / name


def write(path, value):
    path.write_text(json.dumps(value) if not isinstance(value, str) else value)


def snap(platform, account):
    return legacy_state.guard_for(platform, account).snapshot()


def test_every_old_format_is_imported_to_its_owners_account(world):
    now = time.time()
    write(old(world, 'threads'), {'reason': 'checkpoint', 'blocked_at': now - 5, 'expires_at': None})
    write(old(world, 'x'), {'reason': 'challenge', 'blocked_at': now - 5, 'account_id': '42'})
    write(old(world, 'x', 'buckets.json'), {'SearchTimeline': {'limit': 50, 'remaining': 0, 'reset': now + 600},
                                            'Gone': {'limit': 50, 'remaining': 0, 'reset': now - 1}})
    write(old(world, 'reddit'), {'reason': 'challenge', 'blocked_at': now - 5, 'expires_at': None})
    write(old(world, 'reddit', 'buckets.json'), {
        'general': {'status': 'known', 'used': 90, 'remaining': 10, 'reset_at': now + 300, 'observed_at': now},
        'wiki': {'status': 'unmetered', 'until': now + 500, 'blocked_until': now + 400}})
    write(old(world, 'facebook'), {'reason': 'rate_limit', 'blocked_at': now - 5, 'expires_at': now + 900})
    write(old(world, 'naver_blog'), {'reason': 'rate_limit', 'blocked_at': now - 5, 'expires_at': now + 60})
    report = legacy_state.import_all(world)
    assert all('UNREADABLE' not in row['done'] for row in report)
    assert snap('threads', 'u3')['person']['reason'] == 'checkpoint'
    x = snap('x', 'u3')
    assert x['person'] == {**x['person'], 'reason': 'challenge', 'viewer': '42'}
    assert x['scopes']['SearchTimeline']['remaining'] == 0 and 'Gone' not in x['scopes']
    reddit = snap('reddit', 'u0')
    assert reddit['person']['reason'] == 'challenge'
    assert reddit['scopes']['general']['limit'] == 100 and reddit['scopes']['wiki']['blocked_until'] == now + 400
    assert snap('facebook', 'u0')['hold']['until'] == now + 900
    assert snap('naver_blog', 'u0')['hold']['until'] == now + 60


def test_an_account_variable_names_the_owner_of_threads_and_twitter_state(world):
    world.environ = {'THREADS_ASIDE_ACCOUNT': 'u7'}
    write(old(world, 'threads'), {'reason': 'checkpoint', 'blocked_at': time.time(), 'expires_at': None})
    legacy_state.import_all(world)
    assert snap('threads', 'u7')['person'] and not snap('threads', 'u3')['person']


def test_a_source_is_imported_once_so_a_verified_unblock_does_not_come_back(world):
    write(old(world, 'threads'), {'reason': 'checkpoint', 'blocked_at': time.time(), 'expires_at': None})
    legacy_state.import_all(world)
    guard = legacy_state.guard_for('threads', 'u3')
    with guard.verify_unblock() as check:
        check.clear()
    report = legacy_state.import_all(world)
    assert report[0]['done'] == 'already seen' and snap('threads', 'u3')['person'] is None


def test_an_unreadable_old_file_stands_a_person_block_and_says_so(world):
    write(old(world, 'facebook'), '{broken')
    report = legacy_state.import_all(world)
    assert any('UNREADABLE' in row['done'] for row in report)
    assert snap('facebook', 'u0')['person']['reason'] == 'unreadable'


def test_export_writes_what_the_old_reader_accepts_and_is_never_imported_back(world):
    guard = legacy_state.guard_for('threads', 'u3')
    with guard.request() as slot:
        slot.block('checkpoint')
    legacy_state.export_all(world)
    record = json.loads(old(world, 'threads').read_text())
    assert record['reason'] == 'checkpoint' and record['expires_at'] is None
    report = legacy_state.import_all(world)
    assert [r['done'] for r in report if r['platform'] == 'threads'] == ['already seen']


def test_export_removes_its_own_file_once_sns_is_clear_but_never_the_old_skills_own(world):
    guard = legacy_state.guard_for('facebook', 'u0')
    with guard.request() as slot:
        slot.hold(until=time.time() + 100)
    legacy_state.export_all(world)
    assert json.loads(old(world, 'facebook').read_text())['reason'] == 'rate_limit'
    legacy_state.guard_for('facebook', 'u0')  # the hold is still on; nothing changes yet
    path = old(world, 'facebook')
    # sns becomes clear (the hold passes): the export it wrote goes
    future = time.time() + 200
    legacy_state.export_all(world, now=future)
    assert path.exists()  # the hold has not passed in the store's own clock yet
    # the old CLI writes its own block meanwhile: export leaves it for the next import
    write(path, {'reason': 'checkpoint', 'blocked_at': time.time(), 'expires_at': None})
    report = legacy_state.export_all(world)
    assert any('left the old skill' in r['done'] for r in report if r['platform'] == 'facebook')


def test_a_cleared_sns_slot_deletes_the_unchanged_export(world, monkeypatch):
    guard = legacy_state.guard_for('threads', 'u3')
    with guard.request() as slot:
        slot.block('checkpoint')
    legacy_state.export_all(world)
    with legacy_state.guard_for('threads', 'u3').verify_unblock() as check:
        check.clear()
    report = legacy_state.export_all(world)
    assert any(r['done'] == 'removed our block' for r in report) and not old(world, 'threads').exists()
    assert not [e for e in snap('threads', 'u3')['provenance'] if e['kind'] == 'exported']


def test_live_scope_stops_are_exported_to_the_old_buckets(world):
    now = time.time()
    x = legacy_state.guard_for('x', 'u3')
    with x.request(scope='SearchTimeline') as slot:
        slot.hold(scope='SearchTimeline', until=now + 600)
    reddit = legacy_state.guard_for('reddit', 'u0')
    with reddit.request(scope='wiki') as slot:
        slot.hold(scope='wiki', until=now + 300)
    legacy_state.export_all(world)
    buckets = json.loads(old(world, 'x', 'buckets.json').read_text())
    assert buckets['SearchTimeline']['remaining'] == 0 and buckets['SearchTimeline']['reset'] >= now + 599
    assert json.loads(old(world, 'reddit', 'buckets.json').read_text())['wiki']['blocked_until'] >= now + 299


def test_naver_network_block_is_exported_in_a_form_the_old_reader_refuses(world):
    guard = legacy_state.guard_for('naver_blog', 'u0')
    with guard.request() as slot:
        slot.block('network_blocked')
    legacy_state.export_all(world)
    assert json.loads(old(world, 'naver_blog').read_text())['reason'] == 'network_blocked'


def _old_module(root, package, module):
    """Import one old skill's module from its own scripts folder, then forget it (several old skills share names)."""
    sys.path.insert(0, str(root))
    try:
        return importlib.import_module(f'{package}.{module}' if package else module)
    finally:
        sys.path.remove(str(root))
        for name in [m for m in sys.modules if package and (m == package or m.startswith(package + '.'))
                     or m == module]:
            del sys.modules[name]


@pytest.mark.skipif(not os.environ.get('SNS_WORK'), reason='needs the old skills in $SNS_WORK/oldskills')
def test_the_old_readers_stop_on_what_export_writes(world, monkeypatch):
    """With SNS_WORK pointing at the development record: each old skill's own guard reads export's files and stops."""
    skills = Path(os.environ['SNS_WORK']) / 'oldskills/main/.claude/skills'
    now = time.time()
    for platform, account, reason in (('threads', 'u3', 'checkpoint'), ('x', 'u3', 'challenge'),
                                      ('reddit', 'u0', 'challenge'), ('facebook', 'u0', 'checkpoint'),
                                      ('naver_blog', 'u0', 'network_blocked')):
        with legacy_state.guard_for(platform, account).request() as slot:
            slot.block(reason)
    legacy_state.export_all(world)
    monkeypatch.setenv('THREADS_DATA_DIR', str(world.skill('threads').parent))
    monkeypatch.setenv('TWITTER_DATA_DIR', str(world.skill('twitter').parent))
    monkeypatch.setenv('REDDIT_DATA_DIR', str(world.skill('reddit').parent))
    monkeypatch.setenv('FACEBOOK_HOME', str(world.home / '.cache/facebook-skill'))
    monkeypatch.setenv('NAVER_BLOG_HOME', str(world.home / '.cache/naver-blog-skill'))
    checks = [
        lambda: _old_module(skills / 'threads/scripts', 'threads', 'guard').Guard(25).check(),
        lambda: _old_module(skills / 'twitter/scripts', 'twitter', 'guard').Guard(25).check(),
        lambda: _old_module(skills / 'reddit/scripts', 'reddit', 'guard').Guard('u0', 25).check(),
        lambda: _old_module(skills / 'facebook/scripts', 'facebook', 'account').check_blocked(),
        lambda: _old_module(skills / 'naver-blog', 'scripts', '_budget').check_blocked(),
    ]
    for check in checks:
        with pytest.raises(Exception) as caught:
            check()
        assert getattr(caught.value, 'code', None) == 5, caught.value


# --- repairs from the core review (Codex, 2026-10-21) ---------------------------------------------------------------

def test_export_upgrades_an_old_hold_to_a_person_block(world):
    now = time.time()
    write(old(world, 'threads'), {'reason': 'rate_limit', 'blocked_at': now - 10, 'expires_at': now + 60})
    legacy_state.import_all(world)
    legacy_state.guard_for('threads', 'u3').merge(person={'reason': 'checkpoint', 'at': now})  # sns saw a checkpoint
    legacy_state.export_all(world)
    assert json.loads(old(world, 'threads').read_text())['reason'] == 'checkpoint'


def test_export_lengthens_an_old_shorter_hold_but_never_shortens_one(world):
    now = time.time()
    write(old(world, 'facebook'), {'reason': 'rate_limit', 'blocked_at': now - 10, 'expires_at': now + 60})
    legacy_state.import_all(world)
    legacy_state.guard_for('facebook', 'u0').merge(hold={'until': now + 900, 'at': now})
    legacy_state.export_all(world)
    assert json.loads(old(world, 'facebook').read_text())['expires_at'] >= now + 899
    write(old(world, 'naver_blog'), {'reason': 'rate_limit', 'blocked_at': now, 'expires_at': now + 5000})
    with legacy_state.guard_for('naver_blog', 'u0').request() as slot:
        slot.hold(until=now + 100)
    legacy_state.export_all(world)
    assert json.loads(old(world, 'naver_blog').read_text())['expires_at'] == now + 5000


def test_export_reaches_a_reddit_account_the_old_skill_never_used(world, data_dir):
    with legacy_state.guard_for('reddit', 'u8').request() as slot:
        slot.block('challenge')
    legacy_state.export_all(world)
    assert json.loads((world.skill('reddit') / 'u8/blocked.json').read_text())['reason'] == 'challenge'


def test_the_cli_attributes_old_state_to_the_active_account_not_sns_variables(world, monkeypatch):
    monkeypatch.setenv('SNS_ASIDE_ACCOUNT', 'u1')
    sources = legacy_state.Sources(repo=world.repo, home=world.home, active=lambda: 'u0', environ={})
    assert [account for platform, account, _ in sources.entries() if platform in ('threads', 'x')] == ['u0', 'u0']
