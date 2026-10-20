"""trends: the Explore tabs' trends and events, in X's order for this account.

The default tab (for you) comes with X's Explore answer; any other tab is read by the timeline id that answer names,
so it costs a second request. Posts and accounts X mixes into Explore are counted, not shown: trends reads trends.
"""
from sns import reading
from sns.errors import SnsError
from sns.x.listing import NOTES, flags, paged, surface

# the skill's tab name → X's Explore tab id (P2 R8)
TABS = {'trending': 'trending', 'foryou': 'for_you', 'news': 'news', 'sports': 'sports', 'entertainment': 'entertainment'}
KINDS = ('trend', 'event')


def trends(platform, invocation):
    tab = invocation.options['tab']
    identity = {'tab': tab}

    def read(connection, state, out):
        client = connection.client
        timeline_id = (state or {}).get('timeline_id')
        if not timeline_id:
            tabs, default, first = client.explore()
            if TABS[tab] == default:
                if first.unreadable and not first.records:
                    raise SnsError('failed', 'X\'s answer to ExplorePage is not where or what this skill expects.',
                                   'Tell the user the X reader needs an update.', reason='shape_changed')
                page = paged(first, KINDS)
                coverage = [f'{count} {NOTES[label]} left out' for label, count in page.left_out.items()]
                return {'results': page.records, 'stop_reason': 'not_paginable', 'coverage': coverage}
            timeline_id = tabs.get(TABS[tab])
            if not timeline_id:
                raise SnsError('failed', f'X\'s Explore no longer names a {tab} tab.', 'Use another --tab, or tell the '
                                                                                       'user the X reader needs an '
                                                                                       'update.', reason='shape_changed')
        return surface(connection, state, None, order='finite', command='trends', target=None, identity=identity,
                       kinds=KINDS, words=flags(identity), extra={'timeline_id': timeline_id},
                       fetch=lambda cursor: client.timeline('GenericTimelineById', {'timelineId': timeline_id}, cursor))

    return reading.run(platform, invocation, command='trends', target=None, identity=identity, reader=read)
