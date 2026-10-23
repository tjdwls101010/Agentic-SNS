#!/usr/bin/env python3
"""A scripted stand-in for the `aside` CLI, injected with SNS_ASIDE_BIN, for all five platforms.

It understands every call the skill makes:
- `aside account status`: prints the scenario's account_status (default: u0 active), exit account_status_exit.
- `aside --account A <url>`: opens a persistent tab (a new id from the scenario's open_ids, else TAB<n>) at <url>.
- `aside --account A repl` with the opener on stdin: answers {"kind": "opened", "tabs": [...]} from the scripted
  "opener" response, then waits for stdin to close; with "opener_end_closes_tab" the tab disappears then.
- `aside --account A repl <program>`: the program starts with `const ASIDE = {...};` and `const ARGS = {...};`.
  ASIDE.op tabs lists the scenario's tabs; evaluate, load and run answer from the scripted responses. A function names
  itself with `// sns-snippet: <platform>.<name>` (the last such marker, after any shared library it carries); the
  response op is that name ("load:" in front for load). A snippet
  named *.blank empties its tab, *.close removes it unless "close_fails".
Responses come from SNS_FAKE_SCENARIO: {"tabs": [...], "responses": [{"op", "match", "response"}], ...}; the first
unused response whose op fits and whose match is a subset of ARGS is used. A response may be {"__raw_stdout": "...",
"__exit": n} to print exactly that, {"__sleep": s} to wait first, {"__write": {path: text}} to change files first,
{"__kill_parent": true} to kill the calling CLI after the call counts, or carry "__ratelimit": {"bucket", "limit",
"reset"} to have a per-bucket counter fill its "ratelimit" field ({used, remaining, reset} strings). Every call is
appended to SNS_FAKE_LOG.
"""
import fcntl
import json
import os
import re
import signal
import sys
import time
from contextlib import contextmanager


def load():
    with open(os.environ['SNS_FAKE_SCENARIO']) as f:
        return json.load(f)


def save(scenario):
    path = os.environ['SNS_FAKE_SCENARIO']
    with open(path + '.tmp', 'w') as f:
        json.dump(scenario, f)
    os.replace(path + '.tmp', path)


@contextmanager
def locked():
    """One process at a time reads and updates the scenario (several commands may run at once)."""
    with open(os.environ['SNS_FAKE_SCENARIO'] + '.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def log(entry):
    with open(os.environ['SNS_FAKE_LOG'], 'a') as f:
        f.write(json.dumps(entry) + '\n')


def const(program, name):
    match = re.search(r'const ' + name + r' = (.*?);\n', program)
    return json.loads(match.group(1)) if match else None


def fits(match, args):
    for key, value in match.items():
        given = args.get(key) if isinstance(args, dict) else None
        if isinstance(value, dict) and isinstance(given, dict):
            if not fits(value, given):
                return False
        elif isinstance(value, dict) and isinstance(given, (int, float, str)):
            return False
        elif given != value and not (isinstance(value, (int, float)) and str(given) == str(value)):
            return False
    return True


def take(scenario, op, args):
    for response in scenario['responses']:
        if response.get('used') or response['op'] != op:
            continue
        if fits(response.get('match', {}), args):
            response['used'] = True
            return response['response']
    return None


def emit(value):
    body = json.dumps(value)
    chunk = 1000
    if len(body) > 4000:
        pieces = [body[i:i + chunk] for i in range(0, len(body), chunk)]
        for index, piece in enumerate(pieces):
            print(json.dumps({'kind': 'chunk', 'index': index, 'body': piece}))
        print(json.dumps({'kind': 'result', 'chunks': len(pieces), 'body': ''}))
    else:
        print(json.dumps({'kind': 'result', 'chunks': 0, 'body': body}))


def ratelimit(scenario, spec):
    counters = scenario.setdefault('counters', {})
    used = counters.get(spec['bucket'], 0) + 1
    counters[spec['bucket']] = used
    return {'used': str(used), 'remaining': f'{max(0, spec["limit"] - used)}.0', 'reset': str(spec.get('reset', 300))}


def opener(account):
    line = sys.stdin.readline()
    with locked():
        scenario = load()
        log({'op': 'opener', 'account': account, 'marked': 'sns-opener' in line})
        response = take(scenario, 'opener', {}) or {'tabs': ['OPENED']}
        save(scenario)
    if '__sleep' in response:
        time.sleep(response['__sleep'])
    tabs = response.get('tabs') or []
    with locked():
        scenario = load()
        scenario['tabs'] += [{'id': t, 'url': 'about:blank'} for t in tabs]
        save(scenario)
    sys.stdout.write('\x1b[2maccount: u0\x1b[0m\n\x1b[32mrepl\x1b[0m > ' + json.dumps({'kind': 'opened', 'tabs': tabs})
                     + '\n')
    sys.stdout.flush()
    sys.stdin.read()  # held until the skill ends the session
    log({'op': 'opener_end'})
    with locked():
        scenario = load()
        if scenario.get('opener_end_closes_tab'):
            scenario['tabs'] = [t for t in scenario['tabs'] if t['id'] not in tabs]
            save(scenario)
    return 0


def open_tab(url, account):
    with locked():
        scenario = load()
        log({'op': 'open', 'url': url, 'account': account})
        if scenario.get('open_fails'):
            return 1
        ids = scenario.setdefault('open_ids', [])
        target = ids.pop(0) if ids else f'TAB{len(scenario["tabs"]) + 1}'
        scenario['tabs'].append({'id': target, 'url': url})
        save(scenario)
    return 0


def answer(program, account):
    """The scripted response to one program (or an exit code), with the scenario updated: run under the lock."""
    scenario = load()
    aside, args = const(program, 'ASIDE'), const(program, 'ARGS')
    if aside['op'] == 'tabs':
        log({'op': 'tabs', 'account': account})
        if scenario.get('tabs_fail_after_load') and scenario.get('loaded'):
            print('aside: daemon is not reachable', file=sys.stderr)
            return 1
        emit([{'targetId': t['id'], 'url': t['url']} for t in scenario['tabs']])
        return 0
    # a page function may carry a shared library first (X's kit): its own marker is the last one in the program
    found = re.findall(r'// sns-snippet: ([a-z_]+\.[a-z_]+)', program)
    names = [n for n in found if not n.startswith('aside.')] or [n for n in found if n != 'aside.program']
    snippet = names[-1] if names else 'unnamed'
    op = 'load:' + snippet if aside['op'] == 'load' else snippet
    log({'op': op, 'tab': aside.get('tab'), 'args': args, 'url': aside.get('url'), 'account': account})
    if aside['op'] != 'run':
        if aside.get('tab') not in [t['id'] for t in scenario['tabs']]:
            print(json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'no such tab'}))
            return 0
        for t in scenario['tabs']:
            if t['id'] == aside.get('tab'):
                if aside['op'] == 'load':
                    t['url'] = aside['url']
                    scenario['loaded'] = True
                elif snippet.endswith('.blank'):
                    t['url'] = 'about:blank'
        if snippet.endswith('.close') and not scenario.get('close_fails'):
            scenario['tabs'] = [t for t in scenario['tabs'] if t['id'] != aside.get('tab')]
    response = take(scenario, op, args)
    if response is None and (snippet.endswith('.close') or snippet.endswith('.blank')):
        response = scenario.get('empty_answer', True)
    if response is None:
        save(scenario)
        print(f'fake aside: no scripted response for {op} {json.dumps(args)[:300]}', file=sys.stderr)
        return 1
    if isinstance(response, dict) and '__ratelimit' in response:
        response = {**response, 'ratelimit': ratelimit(scenario, response['__ratelimit'])}
        response.pop('__ratelimit')
    save(scenario)
    return response


def main(argv):
    account = None
    if argv[:1] == ['--account']:
        account, argv = argv[1], argv[2:]
    if argv[:2] == ['account', 'status']:
        with locked():
            scenario = load()
            log({'op': 'account_status', 'account': account})
        if scenario.get('account_status_sleep'):
            time.sleep(scenario['account_status_sleep'])
        sys.stdout.write(scenario.get('account_status', '* u0  viewer@example.com  signed in  profiles: Profile 0\n'))
        return scenario.get('account_status_exit', 0)
    if argv == ['repl']:
        return opener(account)
    if argv[:1] != ['repl']:
        return open_tab(argv[0], account)
    with locked():
        response = answer(argv[1], account)
    if isinstance(response, int):
        return response
    if isinstance(response, dict):
        for path, text in (response.get('__write') or {}).items():
            with open(path, 'w') as handle:
                handle.write(text)
        if '__sleep' in response:
            time.sleep(response['__sleep'])
        if response.get('__kill_parent'):
            os.kill(os.getppid(), signal.SIGKILL)
            return 1
        if '__raw_stdout' in response:
            sys.stdout.write(response['__raw_stdout'])
            return response.get('__exit', 0)
    emit(response)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
