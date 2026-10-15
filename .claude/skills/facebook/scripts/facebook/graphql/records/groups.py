"""The group card: what a group's header says about it, in the skill's terms."""
from facebook.graphql.records.parse import pieces
from facebook.graphql.records.time import iso

FIELDS = {
    'kind': 'string — group',
    'id': 'string — numeric id; the group command\'s argument',
    'name': 'string | null — the group\'s name',
    'url': 'string | null — the group\'s Facebook URL',
    'vanity': 'string | null — the group\'s address, the last part of its URL',
    'privacy': 'string | null — the privacy label as Facebook shows it, in the viewer\'s language (e.g. Public group)',
    'privacy_icon': 'string | null — Facebook\'s locale-independent icon name for that label',
    'member_count_text': 'string | null — the member count as Facebook formats it for the viewer (e.g. 90K members); '
                         'not an exact number',
    'join_state': 'string | null — the viewing account\'s relation to the group, e.g. CAN_JOIN, MEMBER, REQUESTED',
    'membership_questions': 'boolean | null — joining asks membership questions',
    'captured_at': 'string — ISO-8601 UTC time this tool received it; changes every run',
}


def _text(value):
    return value if isinstance(value, str) else None


def card(chunks, *, group_id, captured_at):
    """(the group's card or None, response issues)."""
    header, issues = None, []
    for _, data, errors, _ in pieces(chunks):
        if errors:
            issues.append('graphql_errors')
        group = (((data or {}).get('group') or {}).get('profile_header_renderer') or {}).get('group') \
            if isinstance(data, dict) else None
        if isinstance(group, dict) and str(group.get('id')) == str(group_id):
            header = group
    if header is None:
        return None, list(dict.fromkeys(issues))
    privacy = header.get('privacy_info') if isinstance(header.get('privacy_info'), dict) else {}
    title = privacy.get('title')
    members = header.get('group_member_profiles') if isinstance(header.get('group_member_profiles'), dict) else {}
    questions = header.get('has_membership_questions')
    return {'kind': 'group', 'id': str(header['id']), 'name': _text(header.get('name')), 'url': _text(header.get('url')),
            'vanity': _text(header.get('group_address')),
            'privacy': _text(title.get('text')) if isinstance(title, dict) else _text(title),
            'privacy_icon': _text(privacy.get('icon_name')), 'member_count_text': _text(members.get('formatted_count_text')),
            'join_state': _text(header.get('viewer_join_state')),
            'membership_questions': questions if isinstance(questions, bool) else None,
            'captured_at': iso(captured_at)}, list(dict.fromkeys(issues))
