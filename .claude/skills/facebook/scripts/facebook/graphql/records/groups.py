"""The group card: what a group's header says about it, in the skill's terms."""
from facebook.graphql.records.parse import pieces
from facebook.graphql.records.time import iso, timestamp

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
    'description': 'string | null — the group\'s description as written by its admins; never cut',
    'privacy_description': 'string | null — what the privacy label means, as Facebook explains it to the viewer',
    'posts_last_day': 'integer | null — posts in the last day, as Facebook counts them',
    'posts_last_month': 'integer | null — posts in the last month, as Facebook counts them',
    'created_at': 'string | null — ISO-8601 UTC time the group was created',
    'rules': 'array<object> — the group\'s rules in order: {title, description}; empty when none are shown',
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


def about(chunks):
    """(the extra card fields from the group's About screen, or None when absent; response issues)."""
    units, issues = None, []
    for _, data, errors, _ in pieces(chunks):
        if errors:
            issues.append('graphql_errors')
        found = ((data or {}).get('group') or {}).get('about_feed_units') if isinstance(data, dict) else None
        if isinstance(found, list):
            units = found
    if units is None:
        return None, list(dict.fromkeys(issues))
    details = {'description': None, 'privacy_description': None, 'posts_last_day': None, 'posts_last_month': None,
               'created_at': None, 'rules': []}
    for unit in units:
        group = unit.get('group') if isinstance(unit, dict) and isinstance(unit.get('group'), dict) else {}
        description = group.get('description_with_entities')
        if isinstance(description, dict) and _text(description.get('text')):
            details['description'] = description['text']
        for item in group.get('about_info_items') or []:
            info = ((item or {}).get('group') or {}).get('privacy_info') if isinstance(item, dict) else None
            text = ((info or {}).get('description') or {}).get('text') if isinstance(info, dict) else None
            if _text(text):
                details['privacy_description'] = text
        for key, field in (('number_of_posts_in_last_day', 'posts_last_day'), ('number_of_posts_in_last_month', 'posts_last_month')):
            if type(group.get(key)) is int and group[key] >= 0:
                details[field] = group[key]
        if timestamp(group.get('created_time')):
            details['created_at'] = iso(timestamp(group['created_time']))
        if _text(group.get('group_total_members_info_text')):
            details['member_count_text'] = group['group_total_members_info_text']
        rules = group.get('group_rules') if isinstance(group.get('group_rules'), dict) else {}
        for node in rules.get('nodes') or []:
            if isinstance(node, dict) and _text(node.get('rule_title')):
                details['rules'].append({'title': node['rule_title'], 'description': _text(node.get('description'))})
    return details, list(dict.fromkeys(issues))
