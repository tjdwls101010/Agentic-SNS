"""schema: the shared objects (the result envelope, the --out file) and a platform's record schemas; no request."""
from sns import outfile
from sns.results import describe, finish


def schema(platform, invocation, labels=None):
    """One object's schema, or the list of objects; `labels` names the platform's record labels in the text page."""
    result = describe(invocation.exit_codes)
    if labels:
        result['text'] = {**result['text'], 'records': f'one block per record, {labels}'}
    documents = {'result': result, 'out': outfile.describe(), **platform.schemas}
    name = invocation.options.get('object')
    results = [documents[name]] if name else [{'object': key, 'description': doc['description']}
                                               for key, doc in documents.items()]
    return finish({'results': results, 'stop_reason': 'complete'}, platform=platform.key, command='schema')


def objects(platform):
    """The objects schema can describe for `platform` (cli.py offers them as choices)."""
    return ['result', 'out', *platform.schemas]
