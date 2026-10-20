"""Carry account protection between the five old skills and sns while both exist (maintenance code; the skill never
imports it, and the last commit of the sns PR deletes it with the old skills).

import (old → sns), at the start of every live job, before the first sns request: every old block, hold and scope stop
still in force is merged into sns's protection (the stricter side wins; nothing sns holds is weakened). A source
already imported, or written by export, is recognised by its content hash and not imported again, so a block sns has
verified away does not come back and sns never re-imports its own export.

export (sns → old), at the end of every live job and right after a block signal: sns's person block and hold go to the
old skill's blocked.json in the form its reader accepts, and live scope stops (X operations, Reddit buckets) to its
buckets.json, so an old skill used between sns jobs stops where sns stopped. A blocked.json export wrote is deleted
once sns's slot is empty, but only while it is unchanged (a block the old CLI recorded since stays for the next import).
Old Naver has no person reason: its network block is written in a form its reader refuses, which stops it closed
(exit 5) on purpose.

Where the old state lives and whose it is (verified in the old code):
- threads, twitter: the skill's data/protection/ (state key 'default' = the Aside default account, unless
  THREADS_ASIDE_ACCOUNT / TWITTER_ASIDE_ACCOUNT is set) → that variable's account, else the active Aside account;
- reddit: the skill's data/protection/<account>/ → that account;
- facebook, naver-blog (main's old versions): ~/.cache/facebook-skill (FACEBOOK_HOME) and ~/.cache/naver-blog-skill
  (NAVER_BLOG_HOME), which hard-code `aside --account u0` → u0.

Run: uv run contrast/sns/legacy_state.py import|export (prints what it did as JSON).
"""
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
SCRIPTS = REPO / '.claude/skills/sns/scripts'
if __name__ == '__main__' and str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))  # run as a script; tests import it with the skill on their path

from sns import protection  # noqa: E402
from sns.aside import active_account  # noqa: E402
from sns.clock import Deadline  # noqa: E402

TITLES = {'x': ('X', 'x.com'), 'threads': ('Threads', 'threads.com'), 'reddit': ('Reddit', 'reddit.com'),
          'facebook': ('Facebook', 'facebook.com'), 'naver_blog': ('Naver Blog', 'blog.naver.com')}
# The sns policies, as each platform adapter declares them (the plan's table); kept here so this converter works
# before every platform package exists.
from sns.limits import LimitPolicy  # noqa: E402

POLICIES = {
    'x': LimitPolicy(scope='operation', slow='fraction', hold_seconds=900, person=('challenge', 'account_locked'),
                     pace=(1.0, 2.0)),
    'reddit': LimitPolicy(scope='bucket', slow='used', hold_seconds=600, person=('challenge',), pace=(1.0, 2.0)),
    'threads': LimitPolicy(scope='account', hold_seconds=1800, person=('checkpoint',), pace=(1.0, 2.0)),
    'facebook': LimitPolicy(scope='account', hold_seconds=1800, person=('checkpoint',), pace=(1.0, 2.0)),
    'naver_blog': LimitPolicy(scope='account', hold_seconds=1800, person=('network_blocked',), pace=(0.5, 0.8)),
}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _active(binary=None):
    """The active Aside account, as the old threads/twitter skills used it when no account variable was set."""
    binary = binary or os.environ.get('SNS_ASIDE_BIN') or 'aside'
    done = subprocess.run([binary, 'account', 'status'], capture_output=True, text=True, timeout=15)
    account = active_account(done.stdout) if done.returncode == 0 else None
    if account is None:
        raise SystemExit('legacy_state: cannot tell the active Aside account; set SNS_ASIDE_ACCOUNT')
    return account


class Sources:
    """Where each old skill keeps its state, and which Aside account it belongs to."""

    def __init__(self, repo=REPO, home=None, active=None, environ=None):
        self.repo = Path(repo)
        self.environ = os.environ if environ is None else environ
        self.home = Path(home) if home else Path.home()
        self._active = active
        self._resolved = None

    def active(self):
        if self._resolved is None:
            self._resolved = self._active() if callable(self._active) else (self._active or _active())
        return self._resolved

    def skill(self, name):
        return self.repo / '.claude/skills' / name / 'data' / 'protection'

    def cache(self, variable, name):
        return Path(self.environ.get(variable) or self.home / '.cache' / name)

    def entries(self):
        """(platform, account, directory) for every old state location that applies now."""
        found = [('threads', self.environ.get('THREADS_ASIDE_ACCOUNT') or self.active(), self.skill('threads')),
                 ('x', self.environ.get('TWITTER_ASIDE_ACCOUNT') or self.active(), self.skill('twitter')),
                 ('facebook', 'u0', self.cache('FACEBOOK_HOME', 'facebook-skill')),
                 ('naver_blog', 'u0', self.cache('NAVER_BLOG_HOME', 'naver-blog-skill'))]
        reddit = self.skill('reddit')
        if reddit.is_dir():
            found += [('reddit', path.name, path) for path in sorted(reddit.iterdir()) if path.is_dir()]
        return found


def guard_for(platform, account):
    title, site = TITLES[platform]
    return protection.open(platform, account, POLICIES[platform], Deadline(30), title=title, site=site)


def _known(snapshot):
    return {(entry.get('path'), entry.get('sha256')) for entry in snapshot['provenance']}


def _read_old(path):
    """(bytes, parsed object or None when unreadable), or (None, None) when absent."""
    try:
        data = path.read_bytes()
    except FileNotFoundError:
        return None, None
    except OSError:
        return b'', None
    try:
        value = json.loads(data)
    except ValueError:
        return data, None
    return data, value if isinstance(value, dict) else None


def _old_block(platform, record, now):
    """(person, hold) from an old blocked.json, or raise ValueError when its reader would not accept it."""
    reason, at = record.get('reason'), record.get('blocked_at')
    if type(at) not in (int, float):
        raise ValueError
    if reason == 'rate_limit' and platform in ('threads', 'facebook', 'naver_blog'):
        until = record.get('expires_at')
        if type(until) not in (int, float):
            raise ValueError
        return None, ({'until': until, 'at': at} if until > now else None)
    if reason in POLICIES[platform].person:
        viewer = record.get('account_id') if platform == 'x' else None
        return {'reason': reason, 'at': at, 'viewer': viewer if isinstance(viewer, str) else None}, None
    raise ValueError


def _old_scopes(platform, record, now):
    """sns scope facts from an old buckets.json (what still limits a request)."""
    scopes = {}
    for name, entry in record.items():
        if not isinstance(entry, dict):
            raise ValueError
        if platform == 'x':
            if not all(type(entry.get(k)) in (int, float) for k in ('limit', 'remaining', 'reset')):
                raise ValueError
            if entry['reset'] > now:
                scopes[name] = {'limit': entry['limit'], 'remaining': entry['remaining'], 'reset_at': entry['reset']}
                if type(entry.get('next_at')) in (int, float):
                    scopes[name]['slow_until'] = entry['next_at']
        else:
            found = {}
            if type(entry.get('blocked_until')) in (int, float) and entry['blocked_until'] > now:
                found['blocked_until'] = entry['blocked_until']
            if entry.get('status') == 'known' and all(type(entry.get(k)) in (int, float)
                                                      for k in ('used', 'remaining', 'reset_at')) \
                    and entry['reset_at'] > now:
                found.update(limit=entry['used'] + entry['remaining'], remaining=entry['remaining'],
                             reset_at=entry['reset_at'])
                if type(entry.get('slow_until')) in (int, float):
                    found['slow_until'] = entry['slow_until']
            if found:
                scopes[name] = found  # an old probe or unmetered interval is dropped (sns removed unmetered)
    return scopes


def import_all(sources, now=None):
    """Merge every old state still in force into sns; returns what was done, one row per source file."""
    now = now or time.time()
    report = []
    for platform, account, directory in sources.entries():
        guard = guard_for(platform, account)
        known = _known(guard.snapshot())
        for name in ('blocked.json', 'buckets.json'):
            path = directory / name
            data, record = _read_old(path)
            if data is None or (name == 'buckets.json' and platform not in ('x', 'reddit')):
                continue
            source = {'path': str(path), 'sha256': _sha(data)}
            if (source['path'], source['sha256']) in known:
                report.append({'platform': platform, 'account': account, 'file': str(path), 'done': 'already seen'})
                continue
            try:
                if record is None:
                    raise ValueError
                if name == 'blocked.json':
                    person, hold = _old_block(platform, record, now)
                    guard.merge(person=person, hold=hold, source={**source, 'at': record.get('blocked_at')})
                    done = 'person block' if person else ('hold' if hold else 'expired hold (nothing to carry)')
                else:
                    scopes = _old_scopes(platform, record, now)
                    guard.merge(scopes=scopes, source=source)
                    done = f'{len(scopes)} scope(s) in force'
            except ValueError:
                guard.merge(person={'reason': 'unreadable', 'at': now}, source=source)
                done = 'UNREADABLE: a person block stands until doctor --unblock (tell 성진)'
            report.append({'platform': platform, 'account': account, 'file': str(path), 'done': done})
    return report


def _old_record(platform, person, hold):
    """What the old reader accepts for sns's person block or hold, or None when there is nothing to write."""
    if person:
        reason = person['reason']
        if platform == 'naver_blog':
            # old naver knows only rate_limit: its reader refuses this record and stops closed, which is the point
            return {'reason': reason, 'blocked_at': person['at'], 'expires_at': None}
        if reason == 'unreadable':
            reason = POLICIES[platform].person[0]  # a reason the old reader accepts: it stops until a person checks
        if platform == 'x':
            return {'reason': reason, 'blocked_at': person['at'], 'account_id': person.get('viewer')}
        return {'reason': reason, 'blocked_at': person['at'], 'expires_at': None}
    if hold and platform in ('threads', 'facebook', 'naver_blog'):
        return {'reason': 'rate_limit', 'blocked_at': hold['at'], 'expires_at': hold['until']}
    return None


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    data = json.dumps(value).encode()
    temporary = path.with_name('.' + path.name + '.legacy')
    temporary.write_bytes(data)
    os.chmod(temporary, 0o600)
    os.replace(temporary, path)
    return data


def export_all(sources, now=None):
    """Write sns's blocks, holds and live scope stops to where the old skills read them; returns what was done."""
    now = now or time.time()
    report = []
    for platform, account, directory in sources.entries():
        guard = guard_for(platform, account)
        snapshot = guard.snapshot()
        exported = {e['path']: e['sha256'] for e in snapshot['provenance'] if e['kind'] == 'exported'}
        path = directory / 'blocked.json'
        data, _ = _read_old(path)
        ours = data is not None and exported.get(str(path)) == _sha(data)
        wanted = _old_record(platform, snapshot['person'], snapshot['hold'])
        if wanted is not None and (data is None or ours):
            guard.note_export(path, _sha(_write(path, wanted)))
            report.append({'platform': platform, 'account': account, 'file': str(path), 'done': 'wrote block'})
        elif wanted is None and ours:
            path.unlink()
            guard.forget_export(path)
            report.append({'platform': platform, 'account': account, 'file': str(path), 'done': 'removed our block'})
        elif wanted is not None:
            report.append({'platform': platform, 'account': account, 'file': str(path),
                           'done': 'left the old skill\'s own block (the next import carries it)'})
        if platform in ('x', 'reddit'):
            report += _export_scopes(platform, account, directory, guard, snapshot, now)
    return report


def _export_scopes(platform, account, directory, guard, snapshot, now):
    stops = {}
    for name, entry in snapshot['scopes'].items():
        stop = max(entry.get('blocked_until', 0), entry['reset_at'] if entry.get('status') == 'known'
                   and entry.get('remaining', 1) <= 0 else 0)
        if stop > now:
            stops[name] = (stop, entry)
    if not stops:
        return []
    path = directory / 'buckets.json'
    _, record = _read_old(path)
    record = dict(record or {})
    for name, (stop, entry) in stops.items():
        current = record.get(name) if isinstance(record.get(name), dict) else None
        if platform == 'x':
            if current is None or current.get('reset', 0) < stop or current.get('remaining', 1) > 0:
                record[name] = {'limit': (current or {}).get('limit', entry.get('limit', 0)), 'remaining': 0,
                                'reset': stop}
        else:
            current = current or {'status': 'unknown'}
            record[name] = {**current, 'blocked_until': max(stop, current.get('blocked_until', 0))}
    guard.note_export(path, _sha(_write(path, record)))
    return [{'platform': platform, 'account': account, 'file': str(path), 'done': f'wrote {len(stops)} scope stop(s)'}]


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv not in (['import'], ['export']):
        print('usage: legacy_state.py import|export', file=sys.stderr)
        return 2
    sources = Sources(active=os.environ.get('SNS_ASIDE_ACCOUNT'))
    report = import_all(sources) if argv == ['import'] else export_all(sources)
    print(json.dumps({'action': argv[0], 'at': time.time(), 'report': report}, ensure_ascii=False, indent=1))
    return 0


if __name__ == '__main__':
    sys.exit(main())
