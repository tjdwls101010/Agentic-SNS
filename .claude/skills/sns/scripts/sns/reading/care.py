"""doctor and the idle cleanup: the same for every platform, with the platform's own part behind its client."""
from sns.clock import Deadline
from sns.errors import SnsError
from sns.paths import data_dir
from sns.results import finish

from sns.reading.pipeline import Connection, idle_seconds

# 성진: 바쁜 탭은 유휴 간격으로 12번까지 다시 본다 — 그보다 오래 도는 명령은 끝날 때 자기 정리를 남긴다(X·threads에서 이어받음)
BUSY_CHECKS = 12
# One cleanup attempt's own deadline: a tab-state read, the close or blank call and a few looks at the tab list.
ATTEMPT_SECONDS = 60


def doctor(platform, invocation):
    """Check Aside, the browser (and the dedicated tab), login and protection; with --unblock, the one check that may
    lift a person block. A saved block is reported (exit 5) before the browser is touched."""
    connection = None
    try:
        connection = Connection(platform, invocation)
        unblocked = bool(invocation.options.get('unblock'))
        if unblocked:
            with connection.session.opening(), \
                    connection.guard.verify_unblock(scope=platform.unblock_scope) as check:
                connection.client.verify(check)  # raises unless the answer is clean, for the account the block named
                check.clear()
            connection.started = True
        else:
            connection.start()
        state, recent = connection.guard.state(), connection.guard.recent()
        result = {
            'aside': 'available', 'aside_account': connection.account, 'login': 'ready',
            'viewer': connection.known_viewer, 'blocked': state['blocked'], 'block_reason': state['block_reason'],
            'hold_until': state['hold']['until'] if state['hold'] else None, 'unblocked': unblocked,
            'limits': state['scopes'], 'requests_last_hour': recent['last_hour'],
            'requests_last_day': recent['last_day'], 'idle_seconds': idle_seconds(),
            'data_dir': str(data_dir()),
            'protection_state': f'data/{platform.key}/{connection.account}/protection/ — blocks, holds, limits, '
                                'pacing and the request log every invocation shares; never delete it by hand',
            'holds_personal_data': 'data/handles/ (continuation handles with other people\'s ids, removed after a '
                                   'day) and data/images/ (saved pictures, removed after a day)',
            **(connection.client.doctor() or {}),
        }
        reading = {'results': [result], 'stop_reason': 'ready'}
    except SnsError as error:
        reading = {'results': [], 'failure': error}
    finally:
        if connection is not None:
            try:
                connection.release()
            except SnsError:
                pass
    return finish(reading, platform=platform.key, command='doctor',
                  report=connection.report() if connection is not None else None)


def idle(platform, invocation, account, token, after):
    """Empty the dedicated tab after `after` seconds when no command is using it and the last one released was the
    one that left `token` ('any': whichever did), or when an earlier attempt to empty it failed. While a command still
    runs it waits and looks again, so a command that dies without releasing does not leave the tab polling. The waits
    are outside any deadline; each attempt gets its own short one."""
    sleep = invocation.deadline.clock.sleep
    for attempt in range(BUSY_CHECKS):
        sleep(after if attempt == 0 else max(after, 1))
        try:
            connection = Connection(platform, invocation, account=account, deadline=Deadline(ATTEMPT_SECONDS))
            session = connection.session
            with session.opening():
                session.reload()
                if session.active:
                    continue  # a command still running uses the tab
                if not session.tab or (token not in ('any', session.released) and not session.dirty):
                    return 'newer command'
                return 'emptied' if connection.client.release_tab() else 'not emptied'
        except SnsError as error:
            return error.reason or error.kind
    return 'busy'
