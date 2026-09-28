"""Profile cards: the profile and its relationship counts."""
from ..errors import ThreadsError
from ..graphql.decode import read_page
from ..graphql.normalize import build_counts, build_user
from ..graphql.operations import OPERATIONS
from ..graphql.ssr import SSR
from ..graphql.transport import Transport
from ..store import OutFile
from .common import finish, profile_from_route


def run(target, *, limit, out, ctx):
    transport = Transport(40 if limit or out else 10)
    html = transport.page(target.path)
    user_id = transport.session.identity(transport.registry.name('profile.page'), 'userID')
    user = build_user(profile_from_route(SSR(html), transport, user_id))
    if not user or user.username.lower() != target.username:
        raise ThreadsError(6, 'Profile identity differs from the request.', 'Run refresh.', error='envelope_drift')
    result = {'ok': True, 'results': [user.to_dict()], 'stop_reason': 'exhausted'}
    try:
        payload = transport.query('graph.following', {'userID': user_id, 'first': 20})
        read_page(payload, OPERATIONS['graph.following'])
        counts = payload['data'].get('counts')
        if not isinstance(counts, dict) or 'following' not in counts:
            raise ThreadsError(6, 'Relationship counts are missing.', 'Run refresh --capture.', error='envelope_drift')
        result['results'][0]['counts'] = build_counts(counts).to_dict()
    except ThreadsError as error:
        result['results'][0]['counts'] = build_counts({'followers': user.follower_count}).to_dict()
        result.update(ok=False, code=error.code if error.code in (4, 5) else 8,
                      stop_reason='blocked' if error.code in (4, 5) else 'query_failure',
                      error=error.error, message=error.message, fix=error.fix)
    if out:
        output = OutFile(out, ctx)
        try:
            output.commit(result['results'], {'terminal': result['stop_reason']}, result['stop_reason'])
            result.update(out=str(output.path), count=output.count, results=[])
        finally:
            output.close()
    return finish(result, transport)
