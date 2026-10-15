"""One-line summaries of doctor and refresh results."""
import os


def summary(result):
    """Fill the result's summary line; a refresh result gives up its feature_changes to it."""
    if 'verified' in result:
        changed, missing, features = result['changed'], result['missing'], result['features']
        operations = result['discovered'] + len(missing)
        changes = result.pop('feature_changes')
        line = (f'verified {result["verified"]} · discovered {result["discovered"]} · changed {len(changed)} · '
                f'unchanged {operations - len(changed)} · missing {missing} · features {len(features)} '
                + ' '.join(('+' if features[name] else '-') + name for name in changes) + ' · txid ok')
        if changed:
            line += ' · ' + ', '.join(f'{c["operation"]}({c["old"]}→{c["new"]})' for c in changed)
    else:
        registry = 'registry bundled' if result['registry_age_days'] is None else f'registry refreshed {result["registry_age_days"]}d ago'
        signature = 'signature material missing' if result['txid_age_days'] is None else f'signature material {result["txid_age_days"]}d'
        home = os.path.expanduser('~')
        cache = '~' + result['cache'][len(home):] if result['cache'].startswith(home + os.sep) else result['cache']
        where = f'cache {cache} ({result["continuations"]} continuations)'
        if result.get('error'):
            line = (f'blocked: {result["error"]} · viewer {result["viewer"]} · {registry} · {signature} · {where}\n'
                    f'fix: {result["fix"]}')
        else:
            user = result['results'][0]
            bucket = result['budget']['operations'].get('Viewer', {})
            line = (f'@{user["screen_name"]} · viewer {user["id"]} ({result["viewer"]}) · unblocked · {registry} · {signature} · '
                    f'Viewer {bucket.get("remaining", "?")}/{bucket.get("limit", "?")} · window {result["budget"]["window"]}/200 · {where}')
    result['summary'] = line
    return result
