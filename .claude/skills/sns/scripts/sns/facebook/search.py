"""search: posts, people, pages, groups and videos in the server's order for this account."""
from sns import reading
from sns.facebook import web
from sns.facebook.listing import ended, surface, window_of
from sns.facebook.screens import first_page


def search(platform, invocation):
    options = invocation.options
    text, vertical = options['target'], options['type']
    if vertical == 'videos':  # read from the videos search screen, its first page (screens)
        return first_page(platform, invocation, command='search', target=text,
                          identity={'type': vertical, 'recent': None, 'in': None}, words=['--type', vertical],
                          fetch=lambda client: client.video_search(text))
    recent = bool(options.get('recent'))
    group = web.normalize_group(options['within']) if options.get('within') else None
    identity = {'type': vertical, 'recent': True if recent else None, 'in': group}
    words = ['--type', vertical] + (['--recent'] if recent else []) + (['--in', group] if group else [])

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
