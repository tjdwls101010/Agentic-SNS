import json
from datetime import UTC, datetime
from _about import build_fields, iter_collections, json_schema


NOW = datetime(2026, 9, 5, tzinfo=UTC)


def test_about_discovers_collections_and_deduplicates_fields_by_section():
    section = {'field_section_type': 'directory_work', 'profile_fields': {'nodes': [
        {'field_type': 'work', 'title': {'text': 'Synthetic Work'}, 'link_url': 'https://example.test/work'}]}}
    body = json.dumps({'data': {'user': {'all_collections': {'nodes': [
        {'id': 'synthetic-work', 'name': '직장'}, {'id': 'synthetic-work', 'name': '직장'}]},
        'sections': [section, section]}}}).encode()
    assert iter_collections([body]) == [{'id': 'synthetic-work', 'name': '직장'}]
    fields = build_fields([body, body], profile_id='synthetic-profile',
                         collection_names=[None, '직장'], captured_at=NOW)
    assert [f.to_dict() for f in fields] == [{'profile_id': 'synthetic-profile',
        'section': 'directory_work', 'collection': None, 'field_type': 'work',
        'text': 'Synthetic Work', 'url': 'https://example.test/work',
        'captured_at': '2026-09-05T00:00:00Z'}]
    assert json_schema()['title'] == 'ProfileField'
