"""Shared query context and output completion at the CLI boundary."""
import shlex
from pathlib import Path

from ._errors import ThreadsError


def context(args):
    result = {'command': args.command, 'account': 'u0'}
    for key in ('target', 'feed', 'tab', 'sort', 'query', 'type', 'tag', 'relation', 'collection', 'since', 'until'):
        if hasattr(args, key):
            value = getattr(args, key)
            result[key] = value.path if key == 'target' else value
    for key, value in {'feed': 'foryou', 'tab': 'threads', 'sort': 'top', 'type': 'posts'}.items():
        if key in result and result[key] is None:
            result[key] = value
    if result['command'] == 'search' and result.get('type') == 'users':
        result.pop('sort', None)
    return result


def more_command(ctx, handle, output=None, json_mode=False):
    parts = ['python3', str(Path(__file__).with_name('threads.py').resolve()), ctx['command']]
    for key in ('target', 'query', 'relation', 'collection'):
        if key in ctx:
            parts.append(ctx[key])
    for key in ('feed', 'tab', 'sort', 'type', 'since', 'until'):
        if ctx.get(key) is not None:
            parts.extend(['--' + key, str(ctx[key])])
    if ctx.get('tag'):
        parts.append('--tag')
    parts.extend(['--after', str(handle)])
    if output is not None:
        parts.extend(['--out', str(Path(output).resolve())])
    if json_mode:
        parts.append('--json')
    return shlex.join(parts)


def check_actor(state, transport):
    if state.get('actor') and state['actor'] != transport.session.actor:
        raise ThreadsError(2, 'The continuation belongs to a different logged-in Threads account.', 'Restart this query.')
    state['actor'] = transport.session.actor


def profile_from_route(ssr, transport, user_id):
    name = 'BarcelonaProfilePageDirectQuery'
    profile = ssr.select(name, user_id)['user']
    if profile is None:
        profile = transport.query(name, {'userID': user_id})['data']['user']
    return profile


def check_access(page, transport, state):
    if page.records:
        return
    if state.get('private_unfollowed') is None:
        profile = transport.query('BarcelonaProfilePageDirectQuery', {'userID': state['user_id']})['data']['user']
        state['private_unfollowed'] = bool(profile.get('text_post_app_is_private') and
                                          (profile.get('friendship_status') or {}).get('following') is False)
    if state['private_unfollowed']:
        raise ThreadsError(9, 'This profile is private and not followed by the viewer.')


def finish(result, transport):
    result.setdefault('next', None)
    result['budget'] = transport.budget.snapshot()
    result['fetched_bytes'] = transport.fetched_bytes
    if result.get('code') == 7:
        result.update(ok=False, error='empty', message='No matching records in the returned surface.',
                      fix='Try another target or date window; stop_reason describes the coverage.')
    return result
