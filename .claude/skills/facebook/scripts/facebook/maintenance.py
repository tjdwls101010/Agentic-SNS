"""doctor and schema."""
from facebook import guard as protection
from facebook.collection import describe as describe_out
from facebook.connect import Connection
from facebook.errors import FacebookError
from facebook.graphql import SCHEMAS
from facebook.paths import data_dir
from facebook.results import describe as describe_result
from facebook.results import finish

SCHEMA_OBJECTS = ['result', 'out', 'post', 'comment', 'entity', 'about']


def doctor(options):
    """Check Aside, the dedicated tab, login and protection; returns (kind, envelope)."""
    connection = None
    try:
        if options.get('unblock'):
            protection.unblock()
        connection = Connection(protection.MAX_BUDGET, options.get('verbose'))
        client = connection.client
        state = connection.guard.state()
        live = client.live_queries()
        check = {
            'aside': 'available', 'tab': {'target_id': client.tab, 'opened_now': client.opened_now}, 'login': 'ready',
            'account_id': connection.account_id, 'blocked': state['blocked'], 'block_reason': state['block_reason'],
            'queries': {name: ('live in the tab' if doc else 'stored') for name, doc in sorted(live.items())},
            'data_dir': str(data_dir()),
            'protection_state': 'data/protection/ — account block and pacing shared by every invocation; never delete',
            'holds_personal_data': 'data/handles/ — continuation handles with other people\'s ids; cleaned after a day',
        }
        reading = {'results': [check], 'stop_reason': 'ready'}
    except FacebookError as error:
        reading = {'results': [], 'failure': error}
    return finish(reading, command='doctor', requests=connection.guard.count if connection else 0,
                  budget=protection.MAX_BUDGET, setup=connection.guard.setup if connection else 0)


def schema(options):
    """One object's schema, or the list of objects; no request. options['exit_codes'] is cli.py's declaration."""
    documents = {'result': describe_result(options.get('exit_codes') or []), 'out': describe_out(), **SCHEMAS}
    name = options.get('object')
    results = [documents[name]] if name else [{'object': key, 'description': doc['description']}
                                               for key, doc in documents.items()]
    return finish({'results': results, 'stop_reason': 'complete'}, command='schema', requests=0, budget=0)
