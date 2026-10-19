#!/usr/bin/env python3
"""A scripted stand-in for the `aside` CLI, injected with TWITTER_ASIDE_BIN.

It understands the calls the skill makes:
- `aside [--account A] repl` with the opener on stdin: answers {"kind": "opened", "tabs": [...]} from the scripted
  "opener" response (a new about:blank tab), then waits for stdin to close; with "opener_end_closes_tab" in the
  scenario the tab disappears then (Aside closing an unattached tab with its session).
- `aside [--account A] repl <program>`: the program starts with `const ASIDE = {...};` and `const ARGS = {...};`;
  ASIDE.op is "tabs", "evaluate" or "load" (send the tab to ASIDE.url, then the page function's answer). A page
  function names itself with `// twitter-snippet: <name>`. blank empties the tab; close removes it unless the scenario
  says "close_fails".
Responses come from TWITTER_FAKE_SCENARIO: {"tabs": [...], "responses": [{"op", "match", "response"}]}; the first
unused response whose op and match fit is used. Every call is appended to TWITTER_FAKE_LOG.
A response may be {"__raw_stdout": "...", "__exit": n} to print exactly that, or {"__sleep": seconds}.
"""
import json
import os
import re
import sys
import time


def load():
    with open(os.environ['TWITTER_FAKE_SCENARIO']) as f:
        return json.load(f)


def save(scenario):
    with open(os.environ['TWITTER_FAKE_SCENARIO'], 'w') as f:
        json.dump(scenario, f)


def log(entry):
    with open(os.environ['TWITTER_FAKE_LOG'], 'a') as f:
        f.write(json.dumps(entry) + '\n')


def const(program, name):
    match = re.search(r'const ' + name + r' = (.*?);\n', program)
    return json.loads(match.group(1)) if match else None


def take(scenario, op, args):
    for response in scenario['responses']:
        if response.get('used') or response['op'] != op:
            continue
        if all(args.get(key) == value for key, value in response.get('match', {}).items()):
            response['used'] = True
            save(scenario)
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


def opener(account):
    line = sys.stdin.readline()
    scenario = load()
    log({'op': 'opener', 'account': account, 'marked': 'twitter-opener' in line})
    response = take(scenario, 'opener', {}) or {'tabs': ['OPENED']}
    if '__sleep' in response:
        time.sleep(response['__sleep'])
        scenario = load()
    tabs = response.get('tabs') or []
    scenario['tabs'] += [{'id': t, 'url': 'about:blank'} for t in tabs]
    save(scenario)
    sys.stdout.write('\x1b[2maccount: u0\x1b[0m\n\x1b[32mrepl\x1b[0m > ' + json.dumps({'kind': 'opened', 'tabs': tabs}) + '\n')
    sys.stdout.flush()
    sys.stdin.read()  # held until the skill ends the session
    log({'op': 'opener_end'})
    scenario = load()
    if scenario.get('opener_end_closes_tab'):
        scenario['tabs'] = [t for t in scenario['tabs'] if t['id'] not in tabs]
        save(scenario)
    return 0


def main(argv):
    account = None
    if argv[:1] == ['--account']:
        account, argv = argv[1], argv[2:]
    if argv == ['repl']:
        return opener(account)
    scenario = load()
    program = argv[1]
    aside, args = const(program, 'ASIDE'), const(program, 'ARGS')
    if aside['op'] == 'tabs':
        log({'op': 'tabs', 'account': account})
        emit([{'targetId': t['id'], 'url': t['url']} for t in scenario['tabs']])
        return 0
    snippet = re.search(r'// twitter-snippet: ([a-z_]+)', program).group(1)
    op = 'load:' + snippet if aside['op'] == 'load' else snippet
    log({'op': op, 'tab': aside.get('tab'), 'args': args, 'url': aside.get('url'), 'account': account})
    if aside.get('tab') not in [t['id'] for t in scenario['tabs']]:
        print(json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'no such tab'}))
        return 0
    for t in scenario['tabs']:
        if t['id'] == aside.get('tab'):
            if aside['op'] == 'load':
                t['url'] = aside['url']
            elif snippet == 'blank':
                t['url'] = 'about:blank'
    if snippet == 'close' and not scenario.get('close_fails'):
        scenario['tabs'] = [t for t in scenario['tabs'] if t['id'] != aside.get('tab')]
    save(scenario)
    response = take(scenario, op, args)
    if response is None and snippet in ('close', 'blank'):
        response = {'resources': 0, 'ours': 0, 'statuses': [], 'signals': [], 'location': 'about:blank', 'moved': None}
    if response is None:
        print(f'fake aside: no scripted response for {op} {json.dumps(args)[:300]}', file=sys.stderr)
        return 1
    if '__sleep' in response:
        time.sleep(response['__sleep'])
    if '__raw_stdout' in response:
        sys.stdout.write(response['__raw_stdout'])
        return response.get('__exit', 0)
    emit(response)
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
