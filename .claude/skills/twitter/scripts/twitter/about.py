"""about: cards — who an account is, as X shows it; one handle or several in one request."""
from twitter import connect
from twitter.errors import TwitterError
from twitter.x_web import parse_account


def about(options):
    targets = [parse_account(value) for value in options['target']]
    handles = list(dict.fromkeys(t.handle for t in targets))

    def read(connection, state, out):
        client = connection.client
        if len(handles) == 1:
            return {'results': [client.user(handles[0])], 'stop_reason': 'not_paginable'}
        records = client.users(handles)
        found = {r['username'].lower() for r in records}
        missing = [h for h in handles if h.lower() not in found]
        reading = {'results': records, 'stop_reason': 'not_paginable'}
        if missing:
            reading['coverage'] = ['no card for: ' + ', '.join('@' + h for h in missing)]
            reading['details'] = {'unresolved': missing}
        if not records:
            reading['failure'] = TwitterError(7, 'X returned none of these accounts.', 'Check the handles.')
        return reading

    return connect.run(options, command='about', target=' '.join(handles), identity={}, reader=read)
