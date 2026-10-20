"""about: cards — who an account is, as X shows it, one handle or several in one request; or what a space is."""
from sns import reading
from sns.errors import SnsError
from sns.x import web


def _is_space(value):
    return '/i/spaces/' in value


def about(platform, invocation):
    values = invocation.options['target']
    if any(_is_space(value) for value in values):
        if len(values) > 1:
            raise SnsError('argument', 'A space is read on its own.', 'Pass the space link alone, then the accounts.')
        return _space(platform, invocation, web.parse_space(values[0]))
    targets = [web.parse_account(value) for value in values]
    handles = list(dict.fromkeys(t.handle for t in targets))

    def read(connection, state, out):
        client = connection.client
        if len(handles) == 1:
            return {'results': [client.user(handles[0])], 'stop_reason': 'not_paginable'}
        records = client.users(handles)
        found = {r['username'].lower() for r in records}
        missing = [h for h in handles if h.lower() not in found]
        result = {'results': records, 'stop_reason': 'not_paginable'}
        if missing:
            result['coverage'] = ['no card for: ' + ', '.join('@' + h for h in missing)]
            result['details'] = {'unresolved': missing}
        if not records:
            result['failure'] = SnsError('empty', 'X returned none of these accounts.', 'Check the handles.')
        return result

    return reading.run(platform, invocation, command='about', target=' '.join(handles), identity={}, reader=read,
                       bound=False)


def _space(platform, invocation, target):
    def read(connection, state, out):
        return {'results': [connection.client.space(target.space_id)], 'stop_reason': 'not_paginable'}

    return reading.run(platform, invocation, command='about', target=target.url, identity={}, reader=read, bound=False)
