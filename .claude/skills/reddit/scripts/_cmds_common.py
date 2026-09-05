"""Shared result display and continuation commands."""
import json
from pathlib import Path
import shlex
import time
from ._render import render_item
from ._models import timestamp


def continuation(args, number, command=None):
    words = ['python3', str(Path(__file__).resolve().with_name('reddit.py')), command or args.command]
    if getattr(args, 'target', None):
        words.append(args.target)
    if args.command == 'me':
        words.append(args.surface)
    if args.command == 'search':
        words.append(args.query)
    for attribute, flag in [('sort', '--sort'), ('time', '--time'), ('type', '--type'), ('within', '--in'),
                            ('since', '--since'), ('until', '--until'), ('depth', '--depth'), ('context', '--context')]:
        value = getattr(args, attribute, None)
        if value is not None:
            words.extend([flag, str(value)])
    if getattr(args, 'nsfw', False):
        words.append('--nsfw')
    words.extend(['--after', str(number)])
    return shlex.join(words)


def emit(result, args):
    result = dict(result)
    code = result.pop('code', 0)
    result.setdefault('ok', code == 0)
    result.setdefault('results', [])
    result.setdefault('stop_reason', 'exhausted')
    result.setdefault('next', None)
    result.setdefault('sort', getattr(args, 'sort', None))
    if args.json or not result['ok'] or args.command == 'schema':
        print(json.dumps(result, ensure_ascii=False))
        return code
    budget = result.get('budget') or {}
    remaining = budget.get('remaining')
    expires = budget.get('expires_at')
    info = result.get('thread')
    shown = f"{info['shown']} comments shown" if info else f"{len(result['results'])} shown"
    summary = f'{args.command} · {shown} · stopped={result["stop_reason"]} · budget {remaining if remaining is not None else "unknown"} left'
    if result['sort']:
        summary += f' · sort={result["sort"]}'
    if expires:
        summary += f', resets in {max(0, int(expires - time.time()))}s'
    summary += f' · requests={result.get("requests", 0)}'
    if result.get('account'):
        summary += f' · captured account=u/{result["account"]}'
    captured = result.get('captured_at')
    if captured is not None:
        summary += f' · fetched={timestamp(captured) if isinstance(captured, (int, float)) else captured}'
    if info:
        summary += ' · ' + ' · '.join(f'{key}={info[key]}' for key in ('parents', 'parsed', 'unshown', 'pending_ids', 'missing', 'orphans') if key in info)
        context_rows = sum(bool(row.get('context')) for row in result['results'])
        summary += f' · context rows={context_rows} · at least {info.get("min_requests", 0)} expansion requests'
        if info.get('expanded_at'):
            summary += ' · expanded=' + ','.join(timestamp(stamp) for stamp in info['expanded_at'])
    if result.get('out'):
        summary += f' · {result.get("count", 0)} saved to {json.dumps(result["out"])}'
        if result.get('already_complete'):
            summary += ' · already complete'
    print(summary)
    if args.command == 'doctor':
        print(json.dumps(result.get('doctor', {}), ensure_ascii=False))
    for index, item in enumerate(result['results'], 1):
        print(render_item(item, index, getattr(args, 'chars', 180), full=args.command == 'post' and item['kind'] == 'post'))
    if result.get('note'):
        print(result['note'])
    if result.get('next'):
        print('more: ' + result['next'])
    return code


def transport(args):
    from ._transport import Transport
    explicit = any(getattr(args, name, None) is not None for name in ('limit', 'since', 'out'))
    return Transport(max_requests=60 if explicit else 8)


def identity(client=None):
    """The captured username labels caches; only a fresh response verifies login."""
    import os
    import tempfile
    from ._budget import Budget
    from ._errors import RedditError
    path = Budget().home / 'identity.json'
    if client is None:
        try:
            return json.loads(path.read_text()).get('name')
        except (OSError, ValueError, AttributeError):
            return None
    data = client.get('/api/me.json', 'me')['data']
    name = data['name']
    try:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with tempfile.NamedTemporaryFile(mode='w', dir=path.parent, delete=False) as stream:
            json.dump({'name': name, 'captured_at': time.time()}, stream)
            temporary = stream.name
        os.replace(temporary, path)
    except OSError:
        raise RedditError(6, 'Cannot persist the captured account identity.') from None
    return name


def empty_listing():
    return {'kind': 'Listing', 'data': {'children': [], 'after': None}}
