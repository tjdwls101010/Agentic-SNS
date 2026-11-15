"""The lists Facebook renders into a screen's own page (P7c): read through the real cli.py and a fake Aside from one GET
of that screen, whose server-rendered payload carries the list's first page. No next-page request was observed for
any of them, so a list Facebook says goes on ends with stopped=not_built and a coverage line.

Every page here is synthetic, in the shape the recon captures showed (2026-11-16): script blobs whose
RelayPrefetchedStreamCache results carry {data}, with the decoys a real screen carries beside the list (the profile
switcher's connection, other lists of the same screen)."""
import base64
import json

from tests.sns.facebook.scenes import known_tab, look, page_result, rerun, run, story
from tests.sns.support.cli import head, more_line, regrouped

SAVED = 'https://www.facebook.com/saved/'


def preloaded(result, name='Example'):
    """One script blob of a server-rendered page: a preloaded query's result as RelayPrefetchedStreamCache gets it."""
    return {'require': [['ScheduledServerJS', 'handle', None, [{'__bbox': {'require': [
        ['RelayPrefetchedStreamCache', 'next', [], [f'adp_{name}QueryRelayPreloader_5f0c1a', {'__bbox': {
            'complete': True, 'result': result, 'sequence_number': 0}}]],
        ['CometResourceScheduler', 'registerHighPriHashes', None, [['aB1cD2e']]]]}}, {'__bbox': None}]]]}


def screen(*results):
    """A facebook.com page whose scripts preload `results` (with the timing and bootloader blobs every page has)."""
    blobs = [{'require': [['qplTimingsServerJS', None, None, ['77001', 'adp_ExampleQueryRelayPreloader_{N}']]]},
             {'require': [['Bootloader', 'handlePayload', None, [{'consistency': {'rev': 1}}]]]}]
    blobs += [preloaded(result) for result in results]
    scripts = ''.join(f'<script type="application/json" data-content-len="10" data-sjs>{json.dumps(blob)}</script>'
                      for blob in blobs)
    return f'<!DOCTYPE html><html><head><title>Facebook</title></head><body><div id="mount"></div>{scripts}</body></html>'


def connection(edges, has_next=False, cursor='END1'):
    return {'edges': edges, 'page_info': {'end_cursor': cursor, 'has_next_page': has_next}}


# The profile switcher every screen preloads: a connection of other profiles, never part of a list read
SWITCHER = {'data': {'viewer': {'actor': {'__typename': 'User', 'id': '1000123', 'profile_switcher_eligible_profiles': {
    'count': 1, 'profiles': connection([{'node': {'__typename': 'ProfileSwitcherEligibleProfile', 'profile': {
        '__typename': 'User', 'id': '7000001', 'name': 'Decoy Switcher Profile'}}, 'cursor': 'PS1'}])}}}},
    'extensions': {'is_final': True}}


def serve(browser, url, *results):
    known_tab(browser)
    browser.respond('facebook.page', page_result(url, screen(*results)))


def pages(browser):
    return [c['args']['url'] for c in browser.calls() if c['op'] == 'facebook.page']


# --- me saved ---------------------------------------------------------------------------------------------------------

def save(identity, title, *, typename, permalink, details=(), external=None, category='LINK'):
    savable = {'__typename': typename, 'id': 'SV' + identity, '__isSavable': typename,
               'savable_image': {'uri': 'https://scontent.example.invalid/' + identity + '.jpg'},
               'savable_title': {'text': title}, 'savable_attributes': [{'text': d} for d in details],
               'savable_permalink': permalink, 'savable_default_category': category, 'can_viewer_share': True,
               '__isEntity': typename, 'url': permalink}
    if external:
        savable['external_url'] = external
    return {'node': {'id': identity, '__isContentCollectionItem': 'Save', 'savable': savable, 'story_pointer': None,
                     'creator': {'__typename': 'User', 'id': '1000123'}, 'containing_lists': {'count': 0, 'nodes': []},
                     'container_savable': None, 'saver': None, '__typename': 'Save'}, 'cursor': 'C' + identity}


SHELF = save('4100001', 'Handmade cedar shelf', typename='ExternalUrl', details=('Link', 'example-shop.test'),
             permalink='https://l.facebook.com/l.php?u=https%3A%2F%2Fexample-shop.test%2Fshelf&h=AT0',
             external='https://example-shop.test/shelf')
BAKERY = save('4100002', 'Sample Bakery', typename='Page', details=('Page', 'Bakery'),
              permalink='https://facebook.com/samplebakery')


def saved_screen(edges, has_next=False):
    """/saved/: the collections the account made (SaveList), then its saved items beside the notification saves."""
    collections = {'data': {'viewer': {'saver_content_collections': connection([{'node': {
        '__typename': 'SaveList', 'id': '5100001', 'name': 'Decoy Collection'}, 'cursor': 'L1'}])}},
        'extensions': {'is_final': True}}
    items = {'data': {'viewer': {'saved_list_items': connection(edges, has_next, 'SVEND'),
                                 'saves_from_notification': {'nodes': []}},
                      'saved_home': {'hoisted_unit_renderer': None}}, 'extensions': {'is_final': True}}
    return collections, items, SWITCHER


def test_me_saved_reads_the_saved_items_from_the_saved_screen(browser):
    serve(browser, SAVED, *saved_screen([SHELF, BAKERY]))
    code, out, _ = run(browser, 'me', 'saved')
    assert code == 0, out
    lines = regrouped(out)
    assert head(lines[0]) == 'facebook me · collection=saved · 2 shown · stopped=exhausted · requests=1'
    assert lines[1:7] == ['[s1] LINK · ExternalUrl · Link · example-shop.test',
                          '     title[20 of 20 chars shown]: "Handmade cedar shelf"',
                          '     url: "https://example-shop.test/shelf"',
                          '[s2] LINK · Page · Page · Bakery',
                          '     title[13 of 13 chars shown]: "Sample Bakery"',
                          '     url: "https://facebook.com/samplebakery"']
    assert 'Decoy' not in out
    assert pages(browser) == [SAVED]


def test_me_saved_records_name_the_item_and_where_it_points(browser):
    serve(browser, SAVED, *saved_screen([SHELF, BAKERY]))
    code, out, _ = run(browser, 'me', 'saved', '--json')
    records = json.loads(out)['results']
    assert code == 0
    assert [{k: v for k, v in r.items() if k != 'captured_at'} for r in records] == [
        {'kind': 'saved', 'id': '4100001', 'title': 'Handmade cedar shelf', 'item_type': 'ExternalUrl',
         'item_id': 'SV4100001', 'category': 'LINK', 'details': ['Link', 'example-shop.test'],
         'url': 'https://example-shop.test/shelf', 'created_at': None},
        {'kind': 'saved', 'id': '4100002', 'title': 'Sample Bakery', 'item_type': 'Page', 'item_id': 'SV4100002',
         'category': 'LINK', 'details': ['Page', 'Bakery'], 'url': 'https://facebook.com/samplebakery',
         'created_at': None}]


def test_saved_items_facebook_says_go_on_end_at_the_first_page_and_say_so(browser):
    serve(browser, SAVED, *saved_screen([SHELF], has_next=True))
    code, out, _ = run(browser, 'me', 'saved', '--limit', '30', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == ['4100001']
    assert result['stop_reason'] == 'not_built' and 'next' not in result
    assert any(line.startswith('Facebook says more follow') for line in result['coverage'])
    assert pages(browser) == [SAVED]


def test_a_limit_below_the_page_shows_the_rest_from_the_handle_without_fetching_the_screen_again(browser):
    serve(browser, SAVED, *saved_screen([SHELF, BAKERY], has_next=True))
    code, out, _ = run(browser, 'me', 'saved', '--limit', '1')
    assert code == 0 and 'Handmade cedar shelf' in out and 'Sample Bakery' not in out
    line = more_line(out)
    assert line.startswith('more: ')
    look(browser)
    code, out, _ = rerun(browser, line)
    assert code == 0, out
    assert 'Sample Bakery' in out and 'Handmade cedar shelf' not in out
    assert 'stopped=not_built' in out.splitlines()[0] and 'Facebook says more follow' in out
    assert pages(browser) == [SAVED]


def test_no_saved_items_is_explicitly_nothing(browser):
    serve(browser, SAVED, *saved_screen([]))
    code, out, _ = run(browser, 'me', 'saved')
    assert code == 7, out


def test_a_saved_screen_without_the_list_is_a_changed_answer(browser):
    serve(browser, SAVED, SWITCHER)
    code, out, _ = run(browser, 'me', 'saved')
    assert code == 6 and json.loads(out)['error'] == 'failed'
    assert 'may have changed that screen' in json.loads(out)['message']


def test_a_list_that_does_not_say_whether_more_follow_is_a_changed_answer_not_a_retry(browser):
    """page_info without has_next_page: the end cannot be told, and fetching the same screen again cannot help."""
    collections, items, switcher = saved_screen([SHELF])
    del items['data']['viewer']['saved_list_items']['page_info']['has_next_page']
    serve(browser, SAVED, collections, items, switcher)
    code, out, _ = run(browser, 'me', 'saved')
    envelope = json.loads(out)
    assert code == 6 and 'may have changed that screen' in envelope['message'] and 'more:' not in envelope['fix']


def test_more_said_without_a_cursor_still_ends_not_built(browser):
    collections, items, switcher = saved_screen([SHELF], has_next=True)
    items['data']['viewer']['saved_list_items']['page_info']['end_cursor'] = None
    serve(browser, SAVED, collections, items, switcher)
    code, out, _ = run(browser, 'me', 'saved')
    assert code == 0 and 'stopped=not_built' in out.splitlines()[0], out


def test_saved_rows_of_another_kind_are_counted_as_left_out(browser):
    broken = save('4100003', 'No savable', typename='ExternalUrl', permalink='https://example-shop.test/x')
    broken['node']['savable'] = None
    serve(browser, SAVED, *saved_screen([SHELF, broken]))
    code, out, _ = run(browser, 'me', 'saved')
    assert code == 0 and ' 1 shown ' in out.splitlines()[0]
    assert any(line.startswith('coverage: 1 ') and 'left out' in line for line in out.splitlines()), out


# --- me groups --------------------------------------------------------------------------------------------------------

JOINS = 'https://www.facebook.com/groups/joins/'


def group(identity, name, url, **extra):
    return {'node': {'id': identity, 'name': name, 'url': url, '__typename': 'Group',
                     'profile_picture': {'uri': 'https://scontent.example.invalid/g' + identity + '.jpg'}, **extra},
            'cursor': 'G' + identity}


HIKERS = group('2200001', 'Weekend Hikers', 'https://www.facebook.com/groups/weekendhikers/',
               viewer_last_visited_time=1790000000, viewer_join_state='MEMBER', subspace_type='NONE')
TRAINS = group('2200002', 'Model Train Club', 'https://www.facebook.com/groups/2200002/',
               viewer_last_visited_time=1780000000, viewer_join_state='MEMBER', subspace_type='NONE')


def joins_screen(edges, has_next=False):
    """/groups/joins/: the left rail's groups (by last post, and the ones the account admins), then the joined list
    beside its total."""
    rail = {'data': {'viewer': {'groups_tab': {'tab_groups_list': connection([group(
        '2200009', 'Decoy Rail Group', 'https://www.facebook.com/groups/decoyrail/', last_post_time=1791000000)],
        has_next=True)}}, 'adminGroups': {'groups_tab': {'tab_groups_list': connection([])}}},
        'extensions': {'is_final': True}}
    joined = {'data': {'viewer': {'groups_tab': {'joined': {'joined_list': connection(edges, has_next, 'GEND'),
                                                            'total_joined_groups': len(edges)},
                                                 'pending_groups': connection([])}}}, 'extensions': {'is_final': True}}
    return rail, joined, SWITCHER


def test_me_groups_reads_the_joined_list_not_the_left_rail(browser):
    serve(browser, JOINS, *joins_screen([HIKERS, TRAINS]))
    code, out, _ = run(browser, 'me', 'groups')
    assert code == 0, out
    lines = regrouped(out)
    assert head(lines[0]) == 'facebook me · collection=groups · 2 shown · stopped=exhausted · requests=1'
    assert lines[1:3] == [
        '[e1] group id=2200001 · Weekend Hikers · verified=? · url: "https://www.facebook.com/groups/weekendhikers/"',
        '[e2] group id=2200002 · Model Train Club · verified=? · url: "https://www.facebook.com/groups/2200002/"']
    assert 'Decoy' not in out and pages(browser) == [JOINS]


def test_joined_groups_facebook_says_go_on_end_at_the_first_page(browser):
    serve(browser, JOINS, *joins_screen([HIKERS], has_next=True))
    code, out, _ = run(browser, 'me', 'groups', '--json')
    result = json.loads(out)
    assert code == 0 and [r['id'] for r in result['results']] == ['2200001']
    assert result['results'][0]['kind'] == 'group' and result['stop_reason'] == 'not_built'


# --- profile --tab photos and graph followers: a profile's app collections --------------------------------------------

def app_id(kind, text):
    """An app collection's or item's id as Facebook writes it: base64 of '<kind>:<text>'."""
    return base64.b64encode(f'{kind}:{text}'.encode()).decode()


MODULES = {'__module_operation_ProfileCometPaginatedAppCollection_timelineAppCollection': {'__dr': 'X$normalization.graphql'},
           '__module_component_ProfileCometPaginatedAppCollection_timelineAppCollection': {'__dr': 'X.react'}}


def app_screen(edges, has_next=False, *, collection='pfbidSynthCollection01', nesting='photos'):
    """A profile tab (/<account>/photos, /<account>/followers): the app collection holding the tab's items, beside the
    profile's nav sections (a page_info without items). As the captures nest it: on photos the collection's id sits
    beside the items (and again on the collection); on followers the items sit in a wrapper without an id, beside the
    module fields, and the id is one object further out."""
    items, identity = connection(edges, has_next, 'APPEND'), app_id('app_collection', collection)
    if nesting == 'photos':
        renderer = {'collection': {'pageItems': items, 'id': identity}, **MODULES}
    else:
        renderer = {'collection': {'pageItems': items}, **MODULES}
    tab = {'data': {'node': {'__typename': 'User', 'id': '1000777', 'all_collections': {'nodes': [{
        'style_renderer': renderer, 'id': identity}]}, 'null_state_message': {'text': 'Nothing to show'},
        'user': {'timeline_nav_app_sections': {'page_info': {'end_cursor': 'NAV1'}}}}},
        'extensions': {'is_final': True}}
    return tab, SWITCHER


def photo(identity, alt, width=1600, height=900):
    return {'node': {'id': app_id('app_item', '1000777:2305272732:5::' + identity), 'node': {
        '__typename': 'Photo', 'id': identity, 'accessibility_caption': alt, 'immersive_photo_encodings': [],
        'viewer_image': {'uri': f'https://scontent.example.invalid/v{identity}.jpg', 'height': height, 'width': width}},
        'image': {'uri': f'https://scontent.example.invalid/t{identity}.jpg'},
        'url': f'https://www.facebook.com/photo.php?fbid={identity}&set=pb.1000777.-2207520000&type=3',
        'actions_renderer': None, '__typename': 'TimelineAppCollectionItem'}, 'cursor': 'P' + identity}


CANOE = photo('3300001', 'A red canoe on a calm lake')
TOWER = photo('3300002', 'Clock tower at dusk', width=1080, height=1350)


def test_profile_photos_tab_reads_the_photos_the_tab_lists(browser):
    serve(browser, 'https://www.facebook.com/samplepage/photos', *app_screen([CANOE, TOWER]))
    code, out, _ = run(browser, 'profile', 'samplepage', '--tab', 'photos')
    assert code == 0, out
    lines = regrouped(out)
    assert head(lines[0]) == 'facebook profile · tab=photos · 2 shown · stopped=exhausted · requests=1'
    assert lines[1:7] == [
        '[m1] photo id=3300001 · 1600x900',
        '     alt[26 of 26 chars shown]: "A red canoe on a calm lake"',
        '     url: "https://www.facebook.com/photo.php?fbid=3300001&set=pb.1000777.-2207520000&type=3"',
        '[m2] photo id=3300002 · 1080x1350',
        '     alt[19 of 19 chars shown]: "Clock tower at dusk"',
        '     url: "https://www.facebook.com/photo.php?fbid=3300002&set=pb.1000777.-2207520000&type=3"']
    assert pages(browser) == ['https://www.facebook.com/samplepage/photos']


def test_a_numeric_profiles_photos_tab_is_its_sk_screen_and_more_photos_are_not_built(browser):
    serve(browser, 'https://www.facebook.com/profile.php?id=1000777&sk=photos', *app_screen([CANOE], has_next=True))
    code, out, _ = run(browser, 'profile', '1000777', '--tab', 'photos', '--json')
    result = json.loads(out)
    assert code == 0 and result['stop_reason'] == 'not_built'
    assert [{k: v for k, v in r.items() if k != 'captured_at'} for r in result['results']] == [{
        'kind': 'photo', 'id': '3300001',
        'url': 'https://www.facebook.com/photo.php?fbid=3300001&set=pb.1000777.-2207520000&type=3',
        'alt': 'A red canoe on a calm lake', 'image': 'https://scontent.example.invalid/v3300001.jpg', 'width': 1600,
        'height': 900, 'created_at': None}]
    assert pages(browser) == ['https://www.facebook.com/profile.php?id=1000777&sk=photos']


def test_the_photos_tab_takes_no_window(browser):
    code, out, _ = run(browser, 'profile', 'samplepage', '--tab', 'photos', '--since', '2026-01-01')
    assert code == 2 and browser.calls() == []


# --- graph ------------------------------------------------------------------------------------------------------------

def follower(identity, name, url):
    """A follower row of a page's Followers tab: the title Facebook pads with spaces, the person under it."""
    return {'node': {'id': app_id('app_item', '1000777:2356318349:32::' + identity),
                     'image_v2': {'uri': f'https://scontent.example.invalid/a{identity}.jpg'},
                     'title': {'text': f' {name} '}, 'subtitle_text': {'ranges': [], 'text': ''}, 'url': url,
                     'actions_renderer': {'__typename': 'TimelineAppCollectionItemFollowersListActionsRenderer',
                                          'profile_actions': [{'__typename': 'ProfileActionFollow', 'profile_owner': {
                                              'name': 'Decoy Action Owner', 'id': '9' + identity}}]},
                     'privacy_scope': None, 'node': {'__typename': 'User', 'id': identity, 'is_verified': False,
                                                     '__isEntity': 'User', 'url': url},
                     '__typename': 'TimelineAppCollectionItem'}, 'cursor': 'F' + identity}


MIRA = follower('61500001', 'Mira Okafor', 'https://www.facebook.com/mira.okafor.example')
JONAH = follower('61500002', 'Jonah Lindqvist', 'https://www.facebook.com/profile.php?id=61500002')


def test_graph_followers_reads_a_pages_followers_tab(browser):
    serve(browser, 'https://www.facebook.com/samplepage/followers',
          *app_screen([MIRA, JONAH], has_next=True, collection='pfbidSynthFollowers02', nesting='followers'))
    code, out, _ = run(browser, 'graph', 'samplepage', 'followers')
    assert code == 0, out
    lines = regrouped(out)
    assert head(lines[0]) == 'facebook graph · relation=followers · 2 shown · stopped=not_built · requests=1'
    assert lines[1:3] == [
        '[e1] person id=61500001 · Mira Okafor · unverified · url: "https://www.facebook.com/mira.okafor.example"',
        '[e2] person id=61500002 · Jonah Lindqvist · unverified · url: '
        '"https://www.facebook.com/profile.php?id=61500002"']
    assert 'Decoy' not in out and 'more:' not in out
    assert any(line.startswith('coverage: Facebook says more follow') for line in lines)


def friends_screen(edges):
    """/friends/list: the account's own friends, beside their count."""
    friends = {'data': {'viewer': {'all_friends_data': {'count': len(edges), 'friend_count': len(edges)},
                                   'all_friends': connection(edges)}}, 'extensions': {'is_final': True}}
    return friends, SWITCHER


def friend(identity, name):
    return {'node': {'__typename': 'User', '__isFriendNode': 'User', 'id': identity,
                     'social_context': {'text': '3 mutual friends'}, 'friendship_status': 'ARE_FRIENDS', 'name': name,
                     'short_name': name.split()[0], 'url': 'https://www.facebook.com/' + name.lower().replace(' ', '.'),
                     'profile_picture': {'uri': f'https://scontent.example.invalid/f{identity}.jpg'},
                     '__isNode': 'User'}, 'cursor': 'R' + identity}


def test_graph_friends_reads_your_own_friends_list(browser):
    serve(browser, 'https://www.facebook.com/friends/list', *friends_screen([friend('1000501', 'Ines Barros')]))
    code, out, _ = run(browser, 'graph', 'friends')
    assert code == 0, out
    lines = regrouped(out)
    assert head(lines[0]) == 'facebook graph · relation=friends · 1 shown · stopped=exhausted · requests=1'
    assert lines[1] == '[e1] person id=1000501 · Ines Barros · verified=? · url: "https://www.facebook.com/ines.barros"'
    assert 'Decoy' not in out


def test_another_accounts_friends_and_followers_without_an_account_are_refused(browser):
    assert run(browser, 'graph', 'samplepage', 'friends')[0] == 2
    assert run(browser, 'graph', 'followers')[0] == 2
    assert browser.calls() == []


# --- group --tab members ----------------------------------------------------------------------------------------------

MEMBERS = 'https://www.facebook.com/groups/weekendhikers/members'


def member(identity, name, joined):
    return {'invite_status_text': None, 'join_status_text': {'ranges': [], 'text': joined}, 'node': {
        '__typename': 'User', 'id': identity, '__isProfile': 'User', 'name': name, 'is_verified': False,
        '__isEntity': 'User', 'url': 'https://www.facebook.com/profile.php?id=' + identity, '__isGroupMember': 'User',
        'group_membership': {'associated_group': {'__typename': 'Group', 'id': '2200001'}, 'id': '88' + identity,
                             'member_actions': []},
        'profile_picture': {'uri': f'https://scontent.example.invalid/m{identity}.jpg'}}, 'cursor': 'M' + identity}


def members_screen(edges, has_next=False):
    """/groups/<g>/members: a bucket of members with something in common (whose rows name other people in their
    context), then the new members section."""
    context_user = {'__typename': 'User', 'id': '61599999', 'name': 'Decoy Context Friend',
                    'url': 'https://www.facebook.com/decoy.context'}
    bucket = {'data': {'node': {'__typename': 'Group', 'id': '2200001', 'members_in_common': {'edges': [{'node': {
        '__typename': 'User', 'id': '61599998', 'name': 'Decoy Bucket Member', 'url': 'https://www.facebook.com/decoy.b',
        'timeline_context_items': {'edges': [{'node': {'title': {'text': '1 mutual friend: Decoy Context Friend',
                                                                 'ranges': [{'entity': context_user}]}}}]}},
        'cursor': None}], 'page_info': {'end_cursor': 'bucket_item:1:2:Synth', 'has_next_page': True}}}},
        'extensions': {'is_final': True}}
    newest = {'data': {'node': {'__typename': 'Group', 'id': '2200001', 'new_members': connection(edges, has_next, 'NM'),
                                'group_purposes': {'nodes': [{'purpose_enum': 'NONE'}]}}},
              'extensions': {'is_final': True}}
    return bucket, newest, SWITCHER


def test_group_members_tab_reads_the_new_members_section(browser):
    serve(browser, MEMBERS, *members_screen([member('61500011', 'Ana Ruiz', 'Joined 3 days ago'),
                                             member('61500012', 'Tomas Berg', 'Joined 2 weeks ago')], has_next=True))
    code, out, _ = run(browser, 'group', 'weekendhikers', '--tab', 'members')
    assert code == 0, out
    lines = regrouped(out)
    assert head(lines[0]) == 'facebook group · tab=members · 2 shown · stopped=not_built · requests=1'
    assert lines[1:3] == [
        '[e1] person id=61500011 · Ana Ruiz · unverified · url: "https://www.facebook.com/profile.php?id=61500011"',
        '[e2] person id=61500012 · Tomas Berg · unverified · url: "https://www.facebook.com/profile.php?id=61500012"']
    assert 'Decoy' not in out and pages(browser) == [MEMBERS]


def test_the_new_members_section_read_to_its_end_is_still_not_the_whole_group(browser):
    """Only the new members section is read; the group's other member sections are not, so its end is not the end."""
    serve(browser, MEMBERS, *members_screen([member('61500011', 'Ana Ruiz', 'Joined 3 days ago')], has_next=False))
    code, out, _ = run(browser, 'group', 'weekendhikers', '--tab', 'members')
    assert code == 0 and 'stopped=not_built' in out.splitlines()[0], out
    assert any(line.startswith('coverage: ') and 'new members' in line for line in out.splitlines()), out


def test_the_members_tab_takes_no_sort_or_window(browser):
    assert run(browser, 'group', 'weekendhikers', '--tab', 'members', '--sort', 'recent')[0] == 2
    assert run(browser, 'group', 'weekendhikers', '--tab', 'members', '--since', '2026-01-01')[0] == 2
    assert browser.calls() == []


# --- search --type videos ---------------------------------------------------------------------------------------------

def video_story(identity):
    node = story(identity, '2026-03-02T10:00:00Z', text=f'clip {identity}')
    node.update({'__typename': 'Story', '__isTrackableFeedUnit': 'Story',
                 'permalink_url': f'https://www.facebook.com/samplepage/videos/{identity}/'})
    return {'node': node, 'cursor': None}


def video_screen(edges, has_next=True):
    """/search/videos/?q=: the result list (browse_serp) beside the screen's filter pills, whose values are a
    connection too."""
    pills = {'filter_values': connection([{'node': {'text': 'Decoy Most recent', 'value_type': 'RADIO'}}])}
    results = {'data': {'serpResponse': {'filters': [{'main_filter': pills}], 'results': {
        **connection(edges, has_next, '{"page_number":0}'), 'logging_unit_id': 'browse_serp:synthetic'}}},
        'extensions': {'is_final': True}}
    return results, SWITCHER


def test_video_search_reads_the_first_page_of_the_videos_screen(browser):
    serve(browser, 'https://www.facebook.com/search/videos/?q=moon%20base',
          *video_screen([video_story('7700001'), video_story('7700002')]))
    code, out, _ = run(browser, 'search', 'moon base', '--type', 'videos', '--json')
    result = json.loads(out)
    assert code == 0, out
    assert [(r['id'], r['url'], r['author']['name']) for r in result['results']] == [
        ('7700001', 'https://www.facebook.com/samplepage/videos/7700001/', 'Author 7700001'),
        ('7700002', 'https://www.facebook.com/samplepage/videos/7700002/', 'Author 7700002')]
    assert result['stop_reason'] == 'not_built' and 'next' not in result
    assert pages(browser) == ['https://www.facebook.com/search/videos/?q=moon%20base']
    assert not [c for c in browser.calls() if c['op'] == 'facebook.query']


def test_video_search_takes_no_post_filters(browser):
    assert run(browser, 'search', 'moon', '--type', 'videos', '--recent')[0] == 2
    assert browser.calls() == []
