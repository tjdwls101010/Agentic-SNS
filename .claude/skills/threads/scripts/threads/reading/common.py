"""Access checks and result completion shared by the reading commands."""
from ..errors import ThreadsError
from ..graphql.target import parse_target


def resolve_target(value, kind):
    """A command's target as a Threads route, refused before any request when it is not one."""
    return parse_target(value, kind)


def check_actor(state, transport):
    if state.get('actor') and state['actor'] != transport.session.actor:
        raise ThreadsError(2, 'The continuation belongs to a different logged-in Threads account.', 'Restart this query.')
    state['actor'] = transport.session.actor


def profile_from_route(ssr, transport, user_id):
    name = 'BarcelonaProfilePageDirectQuery'
    profile = ssr.select(name, user_id)['user']
    if profile is None:
        profile = transport.query(name, {'userID': user_id})['data']['user']
    return profile


def check_access(page, transport, state):
    if page.records:
        return
    if state.get('private_unfollowed') is None:
        profile = transport.query('BarcelonaProfilePageDirectQuery', {'userID': state['user_id']})['data']['user']
        state['private_unfollowed'] = bool(profile.get('text_post_app_is_private') and
                                          (profile.get('friendship_status') or {}).get('following') is False)
    if state['private_unfollowed']:
        raise ThreadsError(9, 'This profile is private and not followed by the viewer.')


def finish(result, transport):
    result.setdefault('next', None)
    result['budget'] = transport.budget.snapshot()
    result['fetched_bytes'] = transport.fetched_bytes
    if result.get('code') == 7:
        result.update(ok=False, error='empty', message='No matching records in the returned surface.',
                      fix='Try another target or date window; stop_reason describes the coverage.')
    return result
