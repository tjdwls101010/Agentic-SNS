"""trends: the Explore tabs' trends and events, in X's order for this account.

The default tab (for you) comes with X's Explore answer; any other tab is read by the timeline id that answer names,
so it costs a second request. Posts and accounts X mixes into Explore are counted, not shown: trends reads trends.
"""
from twitter import connect
from twitter.errors import TwitterError

# the skill's tab name → X's Explore tab id (P2 R8)
TABS = {'trending': 'trending', 'foryou': 'for_you', 'news': 'news', 'sports': 'sports', 'entertainment': 'entertainment'}


def _trends_only(page):
    kept = [r for r in page.records if r.get('kind') in ('trend', 'event')]
    page.other += len(page.records) - len(kept)
    page.records = kept
    return page


def trends(options):
    tab = options['tab']
    identity = {'tab': tab}

    def read(connection, state, out):
        client = connection.client
        timeline_id = (state or {}).get('timeline_id')
        if not timeline_id:
            tabs, default, first = client.explore()
            if TABS[tab] == default:
                first = _trends_only(first)
                reading = {'results': first.records, 'stop_reason': 'not_paginable', 'coverage': []}
                if first.promoted:
                    reading['coverage'].append(f'{first.promoted} promoted entries (ads) left out')
                if first.other:
                    reading['coverage'].append(f'{first.other} other items X mixed in were left out')
                return reading
            timeline_id = tabs.get(TABS[tab])
            if not timeline_id:
                raise TwitterError(6, f'X\'s Explore no longer names a {tab} tab.', 'Use another --tab, or tell the '
                                                                                     'user the X reader needs an '
                                                                                     'update.', reason='shape_changed')
        return connect.read_list(options, identity, state, None, order=None, command='trends', target=None,
                                 extra={'timeline_id': timeline_id},
                                 fetch=lambda cursor: _trends_only(client.timeline('GenericTimelineById',
                                                                                   {'timelineId': timeline_id}, cursor)))

    return connect.run(options, command='trends', target=None, identity=identity, reader=read)
