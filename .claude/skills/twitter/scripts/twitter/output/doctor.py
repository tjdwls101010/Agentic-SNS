"""One-line summaries of doctor and refresh results."""


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
        user, registry_age, txid_age = result['results'][0], result['registry_age_days'], result['txid_age_days']
        line = (f'Aside u0 · @{user["screen_name"]} · viewer {user["id"]} · unblocked · '
                f'registry age {registry_age if registry_age is not None else "bundled"} days · txid age {txid_age} days')
        bucket = result['budget']['operations'].get('Viewer', {})
        line += f' · budget Viewer {bucket.get("remaining", "?")} of {bucket.get("limit", "?")} · window {result["budget"]["window"]}/200'
    result['summary'] = line
    return result
