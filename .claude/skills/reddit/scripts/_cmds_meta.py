"""Local schema and account/community diagnostics."""
from ._cmds_common import transport, identity
from datetime import datetime, timezone
from ._entities import build_subreddit, build_user, build_rule


def run(args):
    if args.command == 'schema':
        from ._schema import schema
        return {'schema': schema(), 'requests': 0}
    client = transport(args)
    if args.command == 'doctor':
        from ._budget import Budget
        budget = Budget()
        if args.unblock:
            budget.unblock()
        name = identity(client)
        cache_size = sum(path.stat().st_size for directory in ('threads', 'cursors')
                         for path in (budget.home / directory).glob('*.json') if not path.is_symlink())
        return {'doctor': {'account': 'u/' + name, 'cache_bytes': cache_size,
                           'cache': str(budget.home), 'block': client.budget.get('block')},
                'account': name, 'budget': client.budget, 'requests': client.requests, 'captured_at': datetime.now(timezone.utc).isoformat()}
    target = args.parsed_target
    if target.kind == 'subreddit':
        body = client.get(f'/r/{target.sub}/about.json', 'thing:t5')
        item = build_subreddit(body['data']).to_dict()
        rules = client.get(f'/r/{target.sub}/about/rules.json', 'rules')
        item['rules'] = [build_rule(rule).to_dict() for rule in rules['rules']]
    else:
        item = build_user(client.get(f'/user/{target.user}/about.json', 'thing:t2')['data']).to_dict()
    result = {'results': [item], 'budget': client.budget, 'requests': client.requests, 'captured_at': datetime.now(timezone.utc).isoformat()}
    if args.out:
        from ._output import OutFile
        with OutFile(args.out, {'command': 'about', 'target': args.target}) as output:
            output.commit([item], None, 'exhausted')
            result.update(results=[], out=args.out, count=output.count)
    return result
