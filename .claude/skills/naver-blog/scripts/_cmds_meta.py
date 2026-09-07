"""Diagnostics hold no credentials; doctor's one request is also the unblock probe."""
from . import _session
from ._budget import account_lock, cache_dir, clear_blocked, history
from ._transport import Transport


def run(args):
    if args.command == 'schema':
        from ._schema import schema
        return schema()
    transport = Transport(2)
    # --unblock bypasses the block file for one probe; only a real 200 clears it, and the
    # 10-minute window is never reset, because a block is about Naver and the window is ours.
    html = transport.get('feed_html', unblock=args.unblock)
    viewer = _session.store(_session.read_viewer(html, source='feed'))
    if args.unblock:
        with account_lock():
            clear_blocked()
    with account_lock():
        window_used = len(history())
    return {'ok': True, 'viewer': viewer, 'account': 'u0', 'blocked': False,
            'cache': str(cache_dir()), 'window_used': window_used,
            'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes}
