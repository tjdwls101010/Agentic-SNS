#!/usr/bin/env python3
"""A scripted stand-in for the `aside` CLI, injected with THREADS_ASIDE_BIN.

It understands the two calls the skill makes: `aside [--account A] <url>` (open a persistent tab) and
`aside [--account A] repl <program>`. A repl program starts with `const ASIDE = {...};` and `const ARGS = {...};`;
ASIDE.op is "tabs" or "evaluate", and an evaluated page function names itself with `// threads-snippet: <name>`.
blank and navigate also change the tab's address in the scenario, as they do in the browser.
Responses come from THREADS_FAKE_SCENARIO: {"tabs": [...], "responses": [{"op", "match", "response"}]}; the first
unused response whose op and match fit is used. Every call is appended to THREADS_FAKE_LOG.
A response may be {"__raw_stdout": "...", "__exit": n} to print exactly that, or {"__sleep": seconds}.
"""
import json
import os
import re
import sys
import time


def load():
    with open(os.environ['THREADS_FAKE_SCENARIO']) as f:
        return json.load(f)


def save(scenario):
    with open(os.environ['THREADS_FAKE_SCENARIO'], 'w') as f:
        json.dump(scenario, f)


def log(entry):
    with open(os.environ['THREADS_FAKE_LOG'], 'a') as f:
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


def main(argv):
    account = None
    if argv[:1] == ['--account']:
        account, argv = argv[1], argv[2:]
    scenario = load()
    if argv[:1] != ['repl']:
        url = argv[0]
        log({'op': 'open', 'url': url, 'account': account})
        response = take(scenario, 'open', {'url': url}) or {}
        if '__sleep' in response:
            time.sleep(response['__sleep'])
            scenario = load()  # another process may have changed it meanwhile
        if response.get('__fail'):
            return 1
        new = response.get('tab', {'id': 'OPENED', 'url': url})
        scenario['tabs'].append(new)
        save(scenario)
        print(f'Opened {url}.')
        return 0
    program = argv[1]
    aside, args = const(program, 'ASIDE'), const(program, 'ARGS')
    if aside['op'] == 'tabs':
        log({'op': 'tabs', 'account': account})
        emit([{'targetId': t['id'], 'url': t['url']} for t in scenario['tabs']])
        return 0
    snippet = re.search(r'// threads-snippet: ([a-z_]+)', program).group(1)
    log({'op': snippet, 'tab': aside.get('tab'), 'args': args, 'account': account})
    if aside.get('tab') not in [t['id'] for t in scenario['tabs']]:
        print(json.dumps({'kind': 'error', 'error': 'tab_missing', 'message': 'no such tab'}))
        return 0
    # What the page functions do to the tab itself: blank empties it, navigate sends it to a Threads screen.
    if snippet in ('blank', 'navigate'):
        for t in scenario['tabs']:
            if t['id'] == aside.get('tab'):
                t['url'] = 'about:blank' if snippet == 'blank' else args.get('url', t['url'])
        save(scenario)
    if snippet == 'state' and scenario.get('vanish_after_state') == aside.get('tab'):
        scenario['tabs'] = [t for t in scenario['tabs'] if t['id'] != aside.get('tab')]
        scenario['vanish_after_state'] = None
        save(scenario)
    response = take(scenario, snippet, args)
    if response is None:
        print(f'fake aside: no scripted response for {snippet} {json.dumps(args)[:300]}', file=sys.stderr)
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
