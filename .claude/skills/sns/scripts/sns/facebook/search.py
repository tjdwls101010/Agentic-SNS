"""search: posts, people, pages and groups in the server's order for this account."""
from sns import reading
from sns.facebook import web
from sns.facebook.listing import ended, surface, window_of


def search(platform, invocation):
    options = invocation.options
    text, vertical = options['target'], options['type']
    recent = bool(options.get('recent'))
    group = web.normalize_group(options['in_group']) if options.get('in_group') else None
    identity = {'type': vertical, 'recent': True if recent else None, 'in_group': group}
    words = ['--type', vertical] + (['--recent'] if recent else []) + (['--in-group', group] if group else [])

    def read(connection, state, out):
        client = connection.client
        saved = (state or {}) if out is None else (out.state or {})
        group_id = saved.get('group_id') or (client.resolve('group', group) if group and not ended(out) else None)
        # Facebook applies the dates itself (the result is a server-filtered window) and answers in its own order
        return surface(connection, state, out, order='server', command='search', target=text, identity=identity,
                       words=words, extra={'group_id': group_id},
                       fetch=lambda cursor: client.search(text, vertical, cursor, recent=recent,
                                                          since=options.get('since'), until=options.get('until'),
                                                          group_id=group_id, group_url=group))

    return reading.run(platform, invocation, command='search', target=text, identity=identity, reader=read,
                       window=window_of(platform, options, 'server'))
