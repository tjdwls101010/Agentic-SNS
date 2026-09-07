"""The ledger must stay identical to the approved snapshot, field by field."""
import re

import pytest

from naver_blog_skill._api import ALLOWED, OPERATIONS, PATH_KEYS, REFERER, SEARCH_CEILING, build, operation
from naver_blog_skill._errors import NaverBlogError


def normalized(path):
    """Placeholder names are the transcriber's choice; segment order is the contract."""
    return re.sub(r'\{([^}]*)\}', lambda m: '{}' if m[1] in ('blogId', 'me', 'maybeDomainId') else '{' + m[1] + '}', path)


def test_operation_set_matches_the_snapshot_exactly(snapshot):
    assert set(OPERATIONS) == {entry['op'] for entry in snapshot['operations']}


def test_the_snapshot_itself_lists_no_operation_twice(snapshot):
    names = [entry['op'] for entry in snapshot['operations']]
    assert len(names) == len(set(names))


def test_every_operation_transcribes_its_snapshot_row(snapshot):
    rows = {entry['op']: entry for entry in snapshot['operations']}
    for name, spec in OPERATIONS.items():
        row = rows[name]
        assert spec.host == row['host'], name
        assert normalized(spec.path) == normalized(row['path']), name
        assert spec.success == row.get('success'), name
        assert spec.leaf == row.get('leaf') if spec.accept == 'json' else True, name
        assert spec.leaf_type == row.get('leaf_type'), name
        assert spec.identity == row.get('identity'), name
        assert spec.pagination == row.get('pagination', 'single'), name
        assert spec.cap == row.get('cap'), name
        assert spec.marker == row.get('marker'), name
        assert spec.total_field == row.get('total_field'), name
        assert spec.login is bool(row.get('login')), name
        # The snapshot marks the one operation no command calls with useful:"unknown".
        assert spec.role == row.get('role', 'unused' if row.get('useful') == 'unknown' else 'primary'), name
        assert (spec.accept == 'html') is (row.get('accept') == 'text/html'), name


def test_default_parameters_match_the_snapshot_values(snapshot):
    rows = {entry['op']: entry for entry in snapshot['operations']}
    for name, spec in OPERATIONS.items():
        # A snapshot value is a default only if the ledger does not require the caller to supply it:
        # "<text>" is a placeholder, "sim|date" is a choice, 2026/8 are samples, a trailing ? is optional.
        expected = {key: value for key, value in rows[name].get('params', {}).items()
                    if not (isinstance(value, str) and (value.startswith('<') or '|' in value))
                    and key not in PATH_KEYS and key not in spec.required
                    and not str(value).endswith('?')}
        if name == 'comments':
            # objectId and groupId are composed from blogNo and logNo, not sent as defaults.
            expected.pop('objectId', None)
            expected.pop('groupId', None)
        expected.pop(spec.page_param or '', None)
        assert spec.params == expected, name


def test_paged_operations_declare_the_page_parameter_the_snapshot_names(snapshot):
    rows = {entry['op']: entry for entry in snapshot['operations']}
    for name, spec in OPERATIONS.items():
        assert spec.paginated == bool(spec.page_param), name
        assert spec.paginated == bool(spec.page_size), name
        assert spec.cap in (None, SEARCH_CEILING), name
        if spec.page_param:
            assert spec.page_param in rows[name].get('params', {}), name


def test_declared_page_size_matches_the_size_the_request_asks_for(snapshot):
    rows = {entry['op']: entry for entry in snapshot['operations']}
    for name, spec in OPERATIONS.items():
        if not spec.paginated:
            continue
        params = rows[name].get('params', {})
        declared = rows[name].get('page_size') or next(
            (params[key] for key in ('pageSize', 'countPerPage', 'itemCount') if isinstance(params.get(key), int)), None)
        assert spec.page_size == declared, name
        # If the request carries a size at all, it must be the size the ledger claims.
        for key in ('pageSize', 'countPerPage', 'itemCount'):
            if key in spec.params:
                assert spec.params[key] == spec.page_size, name


def test_json_leaves_are_declared_and_html_operations_have_none():
    for name, spec in OPERATIONS.items():
        if spec.accept == 'html':
            assert spec.leaf_type is None, name
        else:
            assert spec.leaf and spec.leaf_type in ('list', 'dict'), name


def test_every_host_has_a_referer_and_a_path_allowlist():
    hosts = {spec.host for spec in OPERATIONS.values()}
    assert hosts <= set(REFERER) and hosts <= set(ALLOWED)
    for spec in OPERATIONS.values():
        assert any(spec.path.startswith(prefix) for prefix in ALLOWED[spec.host]), spec.op


def test_building_a_request_fills_the_path_and_the_query():
    _, path, query = build('post_list', page=2, blogId='naverofficial', categoryNo=108)
    assert path == '/api/blogs/naverofficial/post-list'
    assert sorted(query.split('&')) == ['categoryNo=108', 'itemCount=30', 'page=2']


def test_the_comment_box_object_id_is_composed_here_and_not_by_callers():
    _, path, query = build('comments', page=1, blogNo='142227876', logNo='224400531915')
    assert path == '/commentBox/cbox/web_naver_list_json.json'
    assert 'objectId=142227876_201_224400531915' in query.replace('%5F', '_').replace('%3D', '=')
    assert 'groupId=142227876' in query


def test_building_never_mutates_the_shared_ledger():
    before = dict(operation('post_list').params)
    build('post_list', page=9, blogId='x', categoryNo=1)
    build('search_posts', page=3, keyword='파이썬', sortType='date')
    assert operation('post_list').params == before
    assert 'page' not in operation('search_posts').params


def test_a_missing_required_identifier_is_a_contract_error_not_a_request():
    with pytest.raises(NaverBlogError) as caught:
        build('search_posts', page=1)
    assert caught.value.code == 6 and 'keyword' in caught.value.message


def test_paging_an_unpaginated_operation_is_refused():
    with pytest.raises(NaverBlogError):
        build('buddy_feed', page=2)


def test_legacy_rows_are_marked_so_their_page_contract_is_not_trusted_as_measured():
    # Blog-internal tag search was only ever seen anonymously; its totalPage is miscomputed.
    assert operation('blog_tag_search').source == 'legacy'
    assert operation('blog_tag_search').marker is None
    assert all(spec.source in ('measured', 'legacy') for spec in OPERATIONS.values())


def test_a_short_page_near_the_thousand_item_ceiling_is_the_ceiling_not_the_end():
    posts, tags = operation('search_posts'), operation('search_tags')
    # Post search: 33 full pages (990), page 34 returns 10 and stops at exactly 1,000.
    assert posts.at_ceiling(1000) and posts.at_ceiling(990)
    # Tag search went empty at 990 while reporting 151,093 results; that is the same ceiling.
    assert tags.at_ceiling(990)
    # An early short page is real exhaustion, nowhere near the ceiling.
    assert not posts.at_ceiling(90)
    # Topic listings page ten at a time and reach the ceiling on their own scale.
    assert operation('directory_posts').at_ceiling(1000) and not operation('directory_posts').at_ceiling(500)


def test_operations_without_a_ceiling_never_claim_one():
    assert not operation('post_list').at_ceiling(10 ** 6)
    assert not operation('my_buddies').at_ceiling(10 ** 6)
