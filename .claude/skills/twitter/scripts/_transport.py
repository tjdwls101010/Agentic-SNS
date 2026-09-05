"""Read-only transport and ordered response classification."""
import json
import re
from ._errors import TwitterError, scrub
from ._blocked import account_lock, set_blocked
from ._aside import run_snippet
from ._budget import Budget
from ._registry import Registry, learn


def root_at(data, path):
    current = data
    for piece in path.split('.'):
        if piece.endswith('[]'):
            sequence = current.get(piece[:-2]) if isinstance(current, dict) else None
            if not isinstance(sequence, list):
                return None
            rest = path.split(piece + '.', 1)[-1]
            return [root_at(item, rest) for item in sequence] if rest != path else sequence
        if not isinstance(current, dict) or piece not in current:
            return None
        current = current[piece]
    return current


def classify(envelope, operation, expect):
    status, raw = envelope['status'], envelope['body']
    try:
        body = json.loads(raw)
    except (ValueError, TypeError):
        body = {}
    if not isinstance(body, dict):
        body = {}
    errors = body.get('errors') or []
    errors = [e for e in errors if isinstance(e, dict)]
    codes = {str(e.get('code')) for e in errors}
    messages = ' '.join(str(e.get('message', '')) for e in errors)
    if status == 403 and re.search(r'<!doctype|<html|cf-', raw, re.I):
        raise TwitterError(5, 'X presented a browser challenge.', 'Check x.com in Aside, then run doctor --unblock.', 'challenge')
    if codes & {'64', '326'}:
        raise TwitterError(5, 'X locked or suspended the account.', 'Check x.com in Aside, then run doctor --unblock.', 'account_locked')
    if status == 429:
        reset = (envelope.get('ratelimit') or {}).get('reset', 'the operation reset time')
        raise TwitterError(5, 'X operation rate limit reached.', f'Wait until {reset}; do not retry now.', 'rate_limit')
    if status == 401 or '32' in codes:
        raise TwitterError(4, 'X requires a logged-in session.', 'Log in to X in Aside, then run doctor.', 'session')
    if '353' in codes:
        raise TwitterError(4, 'X rejected the CSRF token.', 'Open x.com in Aside, then run doctor.', 'csrf')
    if status == 404 and not raw.strip():
        raise TwitterError(6, 'X rejected the transaction signature.', 'Run refresh; replies-only and following are ungated alternatives.', 'transaction_rejected')
    if status == 422 or re.search(r'must be defined|coerced Null value|GRAPHQL_VALIDATION_FAILED', messages):
        raise TwitterError(6, 'X changed the variable contract.', f'Update registry.json vars for {operation} (code change).', 'contract_drift')
    if status == 400 and 'features cannot be null:' in messages:
        exc = TwitterError(6, messages, 'Run refresh.', 'operation_rotated')
        exc.missing_features = re.findall(r'[A-Za-z_][A-Za-z_0-9]*', messages.split('features cannot be null:', 1)[1])
        raise exc
    if status in (200, 404) and errors and 'data' not in body:
        raise TwitterError(6, 'The operation may have rotated.', 'Run refresh.', 'operation_rotated')
    if status >= 500 or not body or status >= 400:
        raise TwitterError(6, 'X returned an invalid or transient response.', 'Try later; use refresh only for operation rotation.', 'transient')
    root = root_at(body, expect)
    if operation == 'UserByScreenName' and body.get('data') == {} or isinstance(root, dict) and root.get('__typename') in ('UserUnavailable', 'TweetTombstone'):
        raise TwitterError(9, 'The target is unavailable.', 'Check its handle, visibility, or URL.', 'unavailable')
    malformed = expect.endswith('instructions') and (not isinstance(root, list) or any(not isinstance(item, dict) for item in root))
    if operation in ('UserByScreenName', 'Viewer', 'UsersByScreenNames') and root is not None:
        nodes = root if operation == 'UsersByScreenNames' and isinstance(root, list) else [root]
        malformed = malformed or any(node is not None and (not isinstance(node, dict) or
            node.get('__typename') != 'UserUnavailable' and not str(node.get('rest_id', '')).isdigit()) for node in nodes)
    if root is None or malformed:
        raise TwitterError(6, f'Expected response root is missing for {operation}.', 'The response shape changed; update the envelope parser.', 'envelope_drift')
    return root, scrub(errors)


class Transport:
    def __init__(self, maximum=10, runner=run_snippet, registry=None, budget=None):
        self.runner, self.registry = runner, registry or Registry()
        self.budget = budget or Budget(maximum)
        self.fetched_bytes, self.warnings = 0, []
        self.material = None
        self.changed_viewer = False

    def auxiliary(self, name, args):
        with account_lock():
            self.budget.reserve()
            envelope = self.runner(name, args)
            raw = envelope['body']
            if envelope['status'] == 403 and re.search(r'<!doctype|<html|cf-', raw, re.I):
                set_blocked('challenge')
                raise TwitterError(5, 'X presented a browser challenge.', 'Check x.com in Aside, then run doctor --unblock.', 'challenge')
            if envelope['status'] != 200:
                raise TwitterError(6, 'Page retrieval failed.', 'Try later.', 'transient')
            return envelope

    def session(self, force=False, personal=False):
        from ._session import ensure
        return ensure(self, force, personal)

    def transaction(self, force=False):
        from ._txid import load_material
        if self.material is None or force:
            self.material = load_material(self, force)
        return self.material

    def query(self, operation, variables=None, expect=None):
        from ._txid import generate
        spec = self.registry.get(operation)
        variables = self.registry.variables(operation, **(variables or {}))
        session = self.session()
        csrf_retry = signature_retry = False
        learned = False
        while True:
            path = f'/i/api/graphql/{spec["query_id"]}/{operation}'
            try:
                txid = generate(spec['method'], path, material=self.transaction())
            except TwitterError:
                if spec['gated'] or signature_retry:
                    raise
                txid = None
            args = dict(op=operation, query_id=spec['query_id'], method=spec['method'], variables=variables,
                        features=self.registry.data['features'], bearer=self.registry.data['bearer'], ct0=session['ct0'], txid=txid)
            if spec.get('fieldToggles'):
                args['field_toggles'] = spec['fieldToggles']
            try:
                with account_lock():
                    self.budget.reserve(spec['query_id'])
                    envelope = self.runner('graphql', args)
                    self.fetched_bytes += len(envelope['body'].encode())
                    try:
                        root, warnings = classify(envelope, operation, expect or spec['root'])
                    except TwitterError as error:
                        if error.error in ('challenge', 'account_locked'):
                            set_blocked(error.error)
                        if getattr(error, 'missing_features', None):
                            learn(missing_features=error.missing_features)
                        self.budget.observe(spec['query_id'], envelope.get('ratelimit'), envelope['status'], operation)
                        raise
                    self.budget.observe(spec['query_id'], envelope.get('ratelimit'), envelope['status'], operation)
                    if learned:
                        learn(operation, gated=True)
                    self.warnings.extend(warnings)
                    return root
            except TwitterError as error:
                if error.error == 'csrf' and not csrf_retry:
                    csrf_retry = True
                    previous_viewer = session['viewer_id']
                    session = self.session(force=True)
                    if session['viewer_id'] != previous_viewer:
                        raise TwitterError(2, 'The X account changed while recovering the session.',
                                           'Start a new query and use a new output file for this account.', 'viewer_changed')
                    continue
                if error.error == 'transaction_rejected' and not signature_retry:
                    signature_retry = True
                    learned = txid is None
                    self.transaction(force=True)
                    continue
                raise
