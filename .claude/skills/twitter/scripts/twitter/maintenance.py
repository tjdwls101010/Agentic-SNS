"""doctor, schema and the idle cleanup."""
from twitter import connect
from twitter import guard as protection
from twitter.collection import describe as describe_out
from twitter.connect import Connection
from twitter.errors import TwitterError
from twitter.paths import data_dir
from twitter.results import describe as describe_result
from twitter.results import finish
from twitter.x_web import SCHEMAS

SCHEMA_OBJECTS = ['result', 'out', 'post', 'account', 'trend', 'list']


def _verification(error):
    """Why the check that could lift a block failed, from what stopped it."""
    if error.reason == 'verification':
        return error.details.get('verification_reason') or 'aside'
    if error.reason in ('login',):
        return 'logged_out'
    if error.reason == 'account_changed':
        return 'account_mismatch'
    if error.reason in ('account_locked', 'challenge'):
        return 'moved'
    if error.reason == 'time_limit':
        return 'time_limit'
    if error.code == 10:
        return 'rate_limited'
    if error.code == 3:
        return 'aside'
    return 'failed'


def _keep_block(why, message, **details):
    return TwitterError(5, 'The block stays: ' + message, protection.UNBLOCK_FIX, reason='verification',
                        verification_reason=why, **details)


def _unblock(connection):
    """The one check that may lift a person-cleared block: the tab's own account, read with one Viewer query through
    the verification slot (the operation's limit, pacing and the deadline still hold). Lifted only when the answer is
    this tab's account and the block was recorded for it (or for no known account)."""
    with connection.memory.opening(), connection.guard.verify_unblock(operation='Viewer') as check:
        client = connection.client
        try:
            connection.account_id = client.start()
            blocked_for = (check.block_record or {}).get('account_id')
            if blocked_for and blocked_for != connection.account_id:
                raise _keep_block('account_mismatch', f'it was recorded for X account {blocked_for}, and the browser is '
                                                      f'logged in to {connection.account_id}. A person should check '
                                                      'which account was locked.')
            viewer = client.viewer()
        except TwitterError as error:
            if error.reason == 'verification':
                raise
            raise _keep_block(_verification(error), error.message.rstrip('.') + '.', **{
                k: v for k, v in error.details.items() if k in ('reset', 'next_allowed_at')}) from None
        answered = str((viewer or {}).get('rest_id', '')) if isinstance(viewer, dict) else ''
        if answered != connection.account_id:
            raise _keep_block('account_mismatch', 'X answered for another account than the tab is logged in to.')
        check.clear()


def doctor(options):
    """Check Aside, the dedicated tab, login and protection; with --unblock, the one check that may lift a block."""
    connection = Connection(protection.MAX_BUDGET, options.get('verbose'))
    try:
        if options.get('unblock'):
            _unblock(connection)
        else:
            connection.start()
        client = connection.client
        state, recent = connection.guard.state(), connection.guard.recent()
        live = client.live_operations()
        nonce = connection.memory.nonce
        matched = nonce['matched'] + client.nonce['matched']
        sent = nonce['sent'] + client.nonce['sent']
        check = {
            'aside': 'available',
            'tab': {'target_id': client.tab, 'opened_now': client.opened_now, 'reopened': client.reopened,
                    'opening_measured': client.measured_open},
            'login': 'ready', 'account_id': connection.account_id,
            'blocked': state['blocked'], 'block_reason': state['block_reason'],
            'unblocked': bool(options.get('unblock')),
            'limits': state['buckets'],
            'requests_last_hour': recent['last_hour'], 'requests_last_day': recent['last_day'],
            'operations': {name: (value['type'] if value else 'not in the tab (stored id used)')
                           for name, value in sorted((live.get('live') or {}).items())},
            'signature_generator': bool(live.get('generator')), 'bearer': bool(live.get('bearer')),
            'own_request_matching': ('confirmed' if matched else 'not seen yet (an own request may be counted twice)'
                                     if sent else 'not tried yet'),
            'idle_close_seconds': connect.IDLE_SECONDS, 'data_dir': str(data_dir()),
            'protection_state': 'data/protection/ — account block, per-operation limits, pacing and the request log '
                                'shared by every invocation; never delete',
            'holds_personal_data': 'data/handles/ — continuation handles with other people\'s ids; cleaned after a day',
        }
        reading = {'results': [check], 'stop_reason': 'ready'}
    except TwitterError as error:
        reading = {'results': [], 'failure': error}
    finally:
        connection.note_nonce()
        connection.release()
    return finish(reading, command='doctor', budget=protection.MAX_BUDGET, **connection.report())


def schema(options):
    """One object's schema, or the list of objects; no request. options['exit_codes'] is cli.py's declaration."""
    documents = {'result': describe_result(options.get('exit_codes') or []), 'out': describe_out(), **SCHEMAS}
    name = options.get('object')
    results = [documents[name]] if name else [{'object': key, 'description': doc['description']}
                                               for key, doc in documents.items()]
    return finish({'results': results, 'stop_reason': 'complete'}, command='schema', requests=0, budget=0)


def idle(options):
    """The idle cleanup connect.release() leaves behind; not for direct use."""
    outcome = connect.idle(options['token'], options['after'])
    return 'maintenance', {'ok': True, 'command': 'idle', 'outcome': outcome, 'results': []}
