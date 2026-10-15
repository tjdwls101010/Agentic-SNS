"""Profile cards: one request, two when the page renders no profile."""
from ..errors import changed
from ..graphql.normalize import build_counts, build_user
from ..graphql.ssr import SSR
from ..graphql.transport import Transport
from .common import finish, profile_from_route


def run(target, *, max_requests=None):
    transport = Transport(max_requests or 10)
    html = transport.page(target.path)
    user_id = transport.session.identity(transport.registry.name('profile.page'), 'userID')
    user = build_user(profile_from_route(SSR(html), transport, user_id))
    if not user or user.username.lower() != target.username:
        raise changed('Profile identity differs from the request.')
    # Threads publishes a follower count on the profile but no following or mutual count: those stay unknown, and
    # graph following lists the accounts themselves.
    card = user.to_dict() | {'counts': build_counts({'followers': user.follower_count}).to_dict()}
    result = {'ok': True, 'results': [card], 'stop_reason': 'exhausted'}
    return finish(result, transport)
