"""The ledger must stay identical to the approved snapshot, field by field."""
import re

from naver_blog_skill._api import ALLOWED, OPERATIONS, REFERER, SEARCH_CEILING


def test_operation_set_matches_the_snapshot_exactly(snapshot):
    assert set(OPERATIONS) == {entry['op'] for entry in snapshot['operations']}


def test_every_operation_transcribes_its_snapshot_row(snapshot):
    rows = {entry['op']: entry for entry in snapshot['operations']}
    for name, operation in OPERATIONS.items():
        row = rows[name]
        assert operation.host == row['host'], name
        # Placeholder names are the transcriber's choice; the path segments are the contract.
        assert re.sub(r'\{[^}]*\}', '{}', operation.path) == re.sub(r'\{[^}]*\}', '{}', row['path']), name
        assert operation.success == row.get('success'), name
        assert operation.pagination == row.get('pagination', 'single'), name
        # A paginated row states its size either as a field or inside the query it sends.
        # buddy_feed sends countPerPage and is still not paginated, so only paginated rows count.
        params = row.get('params', {}) if operation.pagination in ('page', 'page_marked') else {}
        declared = row.get('page_size') or next(
            (params[key] for key in ('pageSize', 'countPerPage', 'itemCount') if isinstance(params.get(key), int)), None)
        assert operation.page_size == declared, name
        assert operation.cap == row.get('cap'), name
        assert operation.marker == row.get('marker'), name
        assert operation.login is bool(row.get('login')), name
        assert (operation.accept == 'html') is (row.get('accept') == 'text/html'), name


def test_json_leaves_are_declared_and_html_operations_have_none():
    for name, operation in OPERATIONS.items():
        if operation.accept == 'html':
            assert operation.leaf_type is None, name
        else:
            assert operation.leaf and operation.leaf_type in ('list', 'dict'), name


def test_every_host_has_a_referer_and_a_path_allowlist():
    hosts = {operation.host for operation in OPERATIONS.values()}
    assert hosts <= set(REFERER) and hosts <= set(ALLOWED)
    for operation in OPERATIONS.values():
        assert any(operation.path.startswith(prefix) for prefix in ALLOWED[operation.host]), operation.op


def test_paged_operations_declare_how_to_ask_for_the_next_page():
    for name, operation in OPERATIONS.items():
        paged = operation.pagination in ('page', 'page_marked')
        assert paged == bool(operation.page_param), name
        assert paged == bool(operation.page_size), name
        assert operation.cap in (None, SEARCH_CEILING), name
