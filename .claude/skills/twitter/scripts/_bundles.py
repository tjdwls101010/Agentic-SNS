"""Stage registry/signature updates and publish only after both replay checks."""
import json
import os
import tempfile
import time
from ._blocked import account_lock, cache_dir, read_state, write_state
from ._registry import Registry
from ._txid import derive
from ._errors import TwitterError


def refresh(transport):
    harvested = json.loads(transport.auxiliary('bundles', {})['body'])
    discovered = harvested.get('operations', {})
    if not discovered:
        raise TwitterError(6, 'No read operations were found in the bundles.', 'Inspect the bundle parser; no cache was changed.', 'operation_rotated')
    previous = read_state('registry.json')
    current = transport.registry
    ingredients = harvested.get('txid_ingredients', {})
    if not ingredients.get('html') or not ingredients.get('ondemand_js'):
        raise TwitterError(6, 'Refresh did not find the signature HTML or ondemand chunk.', 'Try refresh later; no cache was changed.', 'transaction_unavailable')
    material = derive(ingredients['html'], ingredients['ondemand_js'], ingredients.get('ondemand_url'))
    operations, changed, missing = {}, [], []
    for name, spec in current.data['operations'].items():
        query_id = discovered.get(name, spec['query_id'])
        operations[name] = dict(query_id=query_id, gated=spec['gated'])
        if name not in discovered:
            missing.append(name)
        if query_id != spec['query_id']:
            changed.append(dict(operation=name, old=spec['query_id'], new=query_id))
    features = dict(current.data['features'])
    absent_features = []
    for name in set(features) | set(previous.get('missing_features', [])):
        if name in harvested.get('features', {}):
            features[name] = harvested['features'][name]
        elif name not in features:
            features[name] = False
            absent_features.append(name)
    candidate = dict(operations=operations, features=features, refreshed_at=time.time(), missing_features=[])
    registry = Registry(candidate)
    transport.registry, transport.material = registry, material
    # The transport can learn errors or refresh txid on a retry. Restore both caches if replay fails.
    originals = {name: (cache_dir() / name).read_bytes() if (cache_dir() / name).exists() else None for name in ('registry.json', 'txid.json')}
    try:
        transport.query('UserByScreenName', {'screen_name': 'X'})
        transport.query('SearchTimeline', {'rawQuery': 'x', 'product': 'Latest', 'count': 1})
        with account_lock():
            write_state('txid.json', material)
            write_state('registry.json', candidate)
    except Exception:
        with account_lock():
            for name, content in originals.items():
                path = cache_dir() / name
                if content is None:
                    path.unlink(missing_ok=True)
                else:
                    with tempfile.NamedTemporaryFile(dir=cache_dir(), delete=False) as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(stream.name, path)
        transport.registry, transport.material = current, None
        raise
    feature_changes = [name for name, value in features.items() if current.data['features'].get(name) != value]
    verified = ['UserByScreenName', 'SearchTimeline']
    summary = (f'verified {verified} · discovered {len(operations) - len(missing)} · changed {len(changed)} · '
               f'unchanged {len(operations) - len(changed)} · missing {missing} · features {len(features)} '
               + ' '.join(('+' if features[name] else '-') + name for name in feature_changes) + ' · txid ok')
    if changed:
        summary += ' · ' + ', '.join(f'{c["operation"]}({c["old"]}→{c["new"]})' for c in changed)
    return dict(ok=True, results=[], stop_reason='not_paginable', verified=verified, discovered=len(operations) - len(missing),
                changed=changed, missing=missing, features=features, absent_features=absent_features,
                txid='ok', summary=summary, failures=harvested.get('failures', []), code=0)
