"""doctor, schema and the idle blanker."""
from threads import connect
from threads import guard as protection
from threads.collection import describe as describe_out
from threads.connect import Connection
from threads.errors import ThreadsError
from threads.paths import data_dir
from threads.results import describe as describe_result
from threads.results import finish
from threads.threads_web import SCHEMAS, classify_document

SCHEMA_OBJECTS = ['result', 'out', 'post', 'account']


def doctor(options):
    """Check Aside, the dedicated tab, login and protection; with --unblock, the one check that may lift a block."""
    connection = Connection(protection.MAX_BUDGET, options.get('verbose'))
    try:
        if options.get('unblock'):
            # the lock order everywhere: session, then account protection
            with connection.memory.opening(), connection.guard.verify_unblock() as check:
                client = connection.client
                connection.account_id = client.start()
                html = client.page('/search', budgeted=False, kind='unblock_check')  # what Threads answers now
                answer = classify_document(html)
                if answer.kind != 'ok' or answer.account_id != connection.account_id:
                    raise answer.error or ThreadsError(6, 'The check did not show this account logged in, so the '
                                                          'block stays.', 'Check Threads in the Aside browser, then '
                                                                          'run doctor --unblock again.')
                check.clear()
        else:
            connection.start()
        client = connection.client
        state, recent = connection.guard.state(), connection.guard.recent()
        live = client.live_queries()
        check = {
            'aside': 'available', 'tab': {'target_id': client.tab, 'opened_now': client.opened_now,
                                          'reopened': client.reopened},
            'login': 'ready', 'account_id': connection.account_id, 'blocked': state['blocked'],
            'block_reason': state['block_reason'], 'unblocked': bool(options.get('unblock')),
            'requests_last_hour': recent['last_hour'], 'requests_last_day': recent['last_day'],
            'queries': {name: ('live in the tab' if found else 'stored') for name, found in sorted(live.items())},
            'idle_blank_seconds': connect.IDLE_SECONDS, 'data_dir': str(data_dir()),
            'protection_state': 'data/protection/ — account block, pacing and the request log shared by every '
                                'invocation; never delete',
            'holds_personal_data': 'data/handles/ — continuation handles with other people\'s ids; cleaned after a day',
        }
        reading = {'results': [check], 'stop_reason': 'ready'}
    except ThreadsError as error:
        reading = {'results': [], 'failure': error}
    finally:
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
    """The idle blanker connect.release() leaves behind; not for direct use."""
    outcome = connect.idle(options['token'], options['after'])
    return 'maintenance', {'ok': True, 'command': 'idle', 'outcome': outcome, 'results': []}
