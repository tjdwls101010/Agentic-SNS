"""about: cards — who an account is, as X shows it, one handle or several in one request; or what a space is."""
from twitter import connect
from twitter.errors import TwitterError
from twitter.x_web import parse_account, parse_space


def _is_space(value):
    return '/i/spaces/' in value


def about(options):
    values = options['target']
    if any(_is_space(value) for value in values):
        if len(values) > 1:
            raise TwitterError(2, 'A space is read on its own.', 'Pass the space link alone, then the accounts.')
        return _space(options, parse_space(values[0]))
    targets = [parse_account(value) for value in values]
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


def _space(options, target):
    def read(connection, state, out):
        return {'results': [connection.client.space(target.space_id)], 'stop_reason': 'not_paginable'}

    return connect.run(options, command='about', target=target.url, identity={}, reader=read)
