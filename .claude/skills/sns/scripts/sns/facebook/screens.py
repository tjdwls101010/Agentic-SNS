"""Lists read from a screen's own page: the first page Facebook preloads into the screen's HTML, in Facebook's order.

No request for the page after was observed for any of them (recon 2026-11-16), so a list Facebook says goes on ends
with stopped=not_built and a coverage line instead of more:. The commands whose views include one of these (me KIND,
profile --tab, group --tab, graph RELATION) choose here between them and the views read elsewhere.
"""
from sns import reading
from sns.facebook import web
from sns.facebook.listing import NOTES, issue_notes, paged
from sns.facebook.listing import group as group_feed
from sns.facebook.listing import profile as timeline
from sns.facebook.notifications import notifications

# 성진: 다음 쪽 요청을 관찰하지 못해 첫 쪽만 읽는다. 화면을 스크롤할 때 나가는 쿼리(이름·변수)를 관찰하면 다음 쪽을 지을 것
MORE = ('Facebook says more follow; the request for the page after was not observed, so only the first page, as the '
        'screen loads it, is read')


def first_page(platform, invocation, *, command, target, identity, words, fetch):
    """Read one screen list (fetch(client) → a web.Batch) as reading.read_list does, its next page not built."""
    def read(connection, state, out):
        issues = []

        def page(cursor):
            batch = fetch(connection.client)
            issues.extend(batch.issues)
            found = paged(batch)
            if found.next is not None:
                found.next, found.stop = None, 'not_built'
            return found

        result = reading.read_list(connection, state, out, order='server', command=command, target=target,
                                   identity=identity, words=words, notes=NOTES, fetch=page)
        # the stop is kept with the rows a handle shows later, so the line goes with it, fetched or not
        capped = [MORE] if result.get('stop_reason') == 'not_built' else []
        result['coverage'] = [*result.get('coverage', []), *issue_notes(issues), *capped]
        return result

    return reading.run(platform, invocation, command=command, target=target, identity=identity, reader=read)


def me(platform, invocation):
    kind = invocation.options['collection']
    if kind == 'notifications':
        return notifications(platform, invocation)
    fetch = {'saved': lambda client: client.saved(), 'groups': lambda client: client.joined_groups()}[kind]
    return first_page(platform, invocation, command='me', target=None, identity={'collection': kind}, words=[kind],
                      fetch=fetch)


def profile(platform, invocation):
    tab = invocation.options['tab']
    if tab == 'posts':
        return timeline(platform, invocation)
    target = web.normalize_profile(invocation.options['target'])
    return first_page(platform, invocation, command='profile', target=target, identity={'tab': tab},
                      words=['--tab', tab], fetch=lambda client: client.collection(target, tab))


def graph(platform, invocation):
    options = invocation.options
    relation = options['relation']
    if relation == 'friends':
        return first_page(platform, invocation, command='graph', target=None, identity={'relation': relation},
                          words=[relation], fetch=lambda client: client.friends())
    target = web.normalize_profile(options['target'])
    return first_page(platform, invocation, command='graph', target=target, identity={'relation': relation},
                      words=[relation], fetch=lambda client: client.collection(target, relation))


def group(platform, invocation):
    if invocation.options['tab'] == 'posts':
        return group_feed(platform, invocation)
    target = web.normalize_group(invocation.options['target'])
    return first_page(platform, invocation, command='group', target=target, identity={'tab': 'members'},
                      words=['--tab', 'members'], fetch=lambda client: client.members(target))
