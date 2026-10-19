#!/usr/bin/env python3
"""A scripted stand-in for the `aside` CLI, injected with REDDIT_ASIDE_BIN.

It understands the two calls the skill makes: `aside account status` (prints the scenario's account_status text, exit
account_status_exit) and `aside [--account A] repl <program>`, where the program starts with `const ARGS = {...};`
followed by the fetch snippet. ARGS is {path, query} or {url}. Responses come from REDDIT_FAKE_SCENARIO:
{"account_status": str, "responses": [{"match": {...}, "response": {...}}], "buckets": {...}}. The first unused response
whose match fits is used: match keys path (exact), url (exact), query (a subset of the sent query). A response is
{status (default 200), body (a string, or any JSON value serialized), url, location, ratelimit {used, remaining, reset}
or "auto"} — "auto" (the default) answers like Reddit: a per-bucket counter (wiki paths count in the wiki bucket, share
links carry no headers). {"__raw_stdout": "...", "__exit": n} prints exactly that; {"__sleep": s} waits first;
{"__kill_parent": true} kills the calling process (the CLI) after the request counts and before answering. Every call
is appended to REDDIT_FAKE_LOG.
"""
import json
import os
import re
import signal
import sys
import time

LIMITS = {'general': 100, 'wiki': 600}


def load():
    with open(os.environ['REDDIT_FAKE_SCENARIO']) as f:
        return json.load(f)


def save(scenario):
    with open(os.environ['REDDIT_FAKE_SCENARIO'], 'w') as f:
        json.dump(scenario, f)


def log(entry):
    with open(os.environ['REDDIT_FAKE_LOG'], 'a') as f:
        f.write(json.dumps(entry) + '\n')


def fits(match, args):
    for key, value in match.items():
        if key == 'query':
            sent = args.get('query') or {}
            if any(str(sent.get(k)) != str(v) for k, v in value.items()):
                return False
        elif args.get(key) != value:
            return False
    return True


def take(scenario, args):
    for response in scenario['responses']:
        if response.get('used'):
            continue
        if fits(response.get('match', {}), args):
            response['used'] = True
            save(scenario)
            return response['response']
    return None


def bucket(args):
    if args.get('url'):
        return None
    return 'wiki' if '/wiki/' in args.get('path', '') else 'general'


def headers(scenario, args):
    """Reddit-like rate-limit headers: a counter per bucket in the scenario."""
    name = bucket(args)
    if name is None:
        return {'used': None, 'remaining': None, 'reset': None}
    counters = scenario.setdefault('buckets', {})
    used = counters.get(name, 0) + 1
    counters[name] = used
    save(scenario)
    return {'used': str(used), 'remaining': f'{max(0, LIMITS[name] - used)}.0', 'reset': '300'}


def main(argv):
    account = None
    if argv[:1] == ['--account']:
        account, argv = argv[1], argv[2:]
    scenario = load()
    if argv[:2] == ['account', 'status']:
        log({'op': 'account_status', 'account': account})
        sys.stdout.write(scenario.get('account_status', '* u0  viewer@example.com  signed in  profiles: Profile 0\n'))
        return scenario.get('account_status_exit', 0)
    if argv[:1] != ['repl']:
        print(f'fake aside: unknown call {argv}', file=sys.stderr)
        return 2
    program = argv[1]
    match = re.match(r'const ARGS = (.*?);\n', program)
    args = json.loads(match.group(1))
    assert 'reddit-snippet: fetch' in program, 'the fetch snippet must follow ARGS'
    log({'op': 'fetch', 'account': account, 'args': args})
    response = take(scenario, args)
    if response is None:
        print(f'fake aside: no scripted response for {json.dumps(args)[:300]}', file=sys.stderr)
        return 1
    if '__sleep' in response:
        time.sleep(response['__sleep'])
        scenario = load()
    rate = response.get('ratelimit', 'auto')
    rate = headers(scenario, args) if rate == 'auto' else rate
    if response.get('__kill_parent'):
        os.kill(os.getppid(), signal.SIGKILL)
        return 1
    if '__raw_stdout' in response:
        sys.stdout.write(response['__raw_stdout'])
        return response.get('__exit', 0)
    body = response.get('body', '')
    body = body if isinstance(body, str) else json.dumps(body)
    sent = args.get('url') or 'https://www.reddit.com' + args['path']
    envelope = {'status': response.get('status', 200), 'url': response.get('url', sent), 'body': body,
                'location': response.get('location'), 'ratelimit': rate}
    print(json.dumps(envelope))
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
