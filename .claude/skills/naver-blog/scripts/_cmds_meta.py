"""Diagnostics hold no credentials; doctor's one request is also the unblock probe."""
from . import _session
from ._budget import account_lock, blocked_since, cache_dir, clear_blocked, history
from ._transport import Transport


def run(args):
    if args.command == 'schema':
        from ._schema import schema
        return schema()
    transport = Transport(2)
    # --unblock bypasses the block file for one probe, but clearing waits until the probe has
    # actually identified the account: an HTTP 200 maintenance page proves nothing. The
    # 10-minute window is never reset either, because a block is Naver's and the window is ours.
    with account_lock():
        recorded_at = blocked_since() if args.unblock else None
    html = transport.get('feed_html', unblock=args.unblock)
    viewer = _session.store(_session.read_viewer(html, source='feed'))
    if args.unblock:
        with account_lock():
            # A 429 that landed after the probe belongs to a later request, so it stays.
            clear_blocked(only_if_recorded_at=recorded_at)
    with account_lock():
        window_used = len(history())
    return {'ok': True, 'viewer': viewer, 'account': 'u0', 'blocked': False,
            'cache': str(cache_dir()), 'window_used': window_used,
            'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes}
