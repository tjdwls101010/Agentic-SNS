"""Diagnostics and registry refresh; neither persists session credentials."""
from datetime import date

from ..graphql import refresh as registry_refresh
from ..graphql.transport import Transport
from ..guard.state import cache_dir
from .common import finish


def doctor(unblock=False):
    transport = Transport(10)
    transport.page('/', unblock=unblock)
    dates = [s['captured_at'] for s in transport.registry.operations.values()]
    return {'ok': True, 'viewer': transport.session.viewer, 'blocked': False,
            'capture_cleanup_uncertain': (cache_dir() / 'capture-active.json').exists(),
            'registry_age_days': (date.today() - date.fromisoformat(min(dates)[:10])).days,
            'budget': transport.budget.snapshot(), 'fetched_bytes': transport.fetched_bytes}


def refresh(capture=False, post=None):
    transport = Transport(60 if capture else 40)
    return finish(registry_refresh.refresh(transport, capture, post), transport)
