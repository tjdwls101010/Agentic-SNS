"""Run the model scenarios against the fake Aside: each run is an isolated `claude -p` given one task.

    python3 -m tests.twitter.model.run <out-dir> [--scenario ID ...] [--treatment A|C ...] [--skill FILE] [--drop N] [--repeat N]

Treatment A gets the task, the CLI's invocation and the one-command-per-call boundary its permission sets; C also gets SKILL.md's body as an appended system prompt (--skill picks the file, --drop N leaves out its Nth body paragraph, counting from 0). Each run copies the skill's scripts (never SKILL.md) into a scratch directory, seeds its own TWITTER_HOME and fake script, puts the fake Aside behind TWITTER_ASIDE_BIN, removes the real aside from PATH, and allows only `Bash(uv run "<copy>/scripts/cli.py" *)`. A run is invalid and repeated (up to three times) when a permission was denied, the CLI never ran, the fake saw no request, or SKILL.md appears in a command. Results go to <out-dir>/results.jsonl, one line per valid run, with its commands and final answer; each run's stream is kept in <out-dir>/<run>/stream.jsonl.
"""
import argparse
import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from ..fake_data import tweet, user, wrap

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
SKILL = ROOT / '.claude/skills/twitter'
FAKE = HERE.parent / 'fake_aside/aside'
DOUBLES = HERE.parent / 'process_doubles'
FIXTURE = json.loads((HERE.parent / 'fixtures/transaction.json').read_text())
CLAUDE = shutil.which('claude') or str(Path.home() / '.local/bin/claude')
PATH = '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin'
MODEL = 'claude-opus-5-5'


def when(day, hour=12, month='Sep'):
    return time.strftime('%a %b %d %H:%M:%S +0000 %Y', time.strptime(f'2026 {month} {day} {hour}', '%Y %b %d %H'))


def post(identity, text, created, likes=0, author=None, parent=None, **legacy):
    node = tweet(str(identity), parent)
    node['legacy'].update(full_text=text, created_at=created, favorite_count=likes, entities={}, **legacy)
    if author:
        node['core']['user_results']['result'] = author
    return node


def page(op, nodes, cursor=None, after=None, kind='tweet', **extra):
    entries = [{'entryId': f'{kind}-{n["rest_id"]}', 'content': {'itemContent': {f'{kind}_results': {'result': n}}}} for n in nodes]
    if cursor:
        entries.append({'entryId': 'cursor-bottom', 'content': {'cursorType': 'Bottom', 'value': cursor}})
    return {'op': op, 'cursor': after, 'keep': True, 'body': wrap(op, [{'type': 'TimelineAddEntries', 'entries': entries}]), **extra}


def repost():
    writer = user('900', 'writer')
    original = post(900, 'Big announcement: we are open-sourcing the engine.', when(24), 5400, writer)
    return [page('UserTweets', [post(201, 'Our quarterly notes are up.', when(27), 40),
                                post(202, 'Thanks for 1K followers!', when(26), 120),
                                post(203, 'RT @writer: Big announcement: we are open-sourcing the engine.', when(25), 0,
                                     retweeted_status_result={'result': original}),
                                post(204, 'Small fix shipped.', when(23), 15)])]


def ranked_feed():
    return [page('HomeTimeline', [post(301, 'An older viral post.', when(20), 9000, user('31', 'viral')),
                                  post(302, 'A post from yesterday.', when(28), 300, user('32', 'friend')),
                                  post(303, 'A post from Friday.', when(25), 80, user('33', 'news'))]),
            page('HomeLatestTimeline', [post(401, 'Fresh: launch day is here.', when(29, 10), 12, user('41', 'maker')),
                                        post(402, 'Morning coffee thoughts.', when(29, 9), 3, user('42', 'friend')),
                                        post(403, 'Late night reading list.', when(28, 22), 7, user('43', 'reader'))])]


def date_window():
    days = [(d, 'Sep') for d in range(30, 0, -1)] + [(31, 'Aug'), (30, 'Aug')]
    posts = [post(1000 + i, f'Daily note for {month} {day}.', when(day, 12, month), 10) for i, (day, month) in enumerate(days)]
    return [page('UserTweets', posts[:10], 'c1'), page('UserTweets', posts[10:20], 'c2', 'c1'),
            page('UserTweets', posts[20:], None, 'c2')]


def thread_sample():
    focal = post(500, 'We are changing the free tier limits starting next month.', when(28), 800, reply_count=1460)
    moods = ['This is great news for small teams.', 'Terrible decision, I am leaving.', 'Makes sense given the costs.',
             'Please keep the old limits for students.', 'Finally, fair pricing.']
    replies = [post(510 + i, moods[i % 5], when(28, 13), 5, user(str(60 + i), f'replier{i}'), '500') for i in range(60)]
    hidden = [{'type': 'TimelineAddToModule', 'moduleEntryId': f'conversationthread-{m}', 'moduleItems': [
        {'entryId': f'more-{m}', 'item': {'itemContent': {'cursorType': 'ShowMoreThreads', 'value': m}}}]} for m in 'abc']
    first = page('TweetDetail', [focal, *replies[:20]], 'r2')
    first['body']['data']['threaded_conversation_with_injections_v2']['instructions'] += hidden
    return [first, page('TweetDetail', replies[20:40], 'r3', 'r2'), page('TweetDetail', replies[40:], None, 'r3')]


def search_bucket():
    entries = []
    for remaining in (2, 1, 0):
        entry = page('SearchTimeline', [post(600 + remaining * 10 + i, f'A notable post on this topic, number {i}.', when(29, 8), 50,
                                             user(str(70 + i), f'dev{i}')) for i in range(3)])
        entry.update(keep=False, ratelimit={'limit': 50, 'remaining': remaining, 'reset': int(time.time()) + 900})
        del entry['cursor']
        entries.append(entry)
    return entries


def signature_substitute():
    frames = ''.join('<svg id="loading-x-anim-' + index + '"><g>' + ''.join('<path d="' + p + '"></path>' for p in paths)
                     + '</g></svg>' for index, paths in FIXTURE['frames'].items())
    html = '<meta name="twitter-site-verification" content="' + FIXTURE['verification'] + '">' + frames + ',1:"ondemand.s",1:"abc123"'
    js = ';'.join('(a[' + str(index) + '],16)' for index in FIXTURE['indices'])
    mixed = [post(801, '@other0 agreed, thanks for the link.', when(29, 9), 2, parent='950', in_reply_to_screen_name='other0'),
             post(802, 'New blog post is out today.', when(29, 8), 30),
             post(803, '@other1 that bug is fixed in 2.1.', when(28, 20), 1, parent='951', in_reply_to_screen_name='other1'),
             post(804, 'Conference slides uploaded.', when(28, 15), 12),
             post(805, '@other2 yes, DMs are open.', when(28, 11), 0, parent='952', in_reply_to_screen_name='other2')]
    return ([{'op': 'UserTweetsAndReplies', 'keep': True, 'status': 404, 'body': ''}]
            + [item for _ in range(6) for item in ({'snippet': 'page', 'body': html}, {'snippet': 'page', 'body': js})]
            + [page('UserRepliesTimeline', mixed)])


def friends():
    following = [user(str(20 + i), f'follows{i}') for i in range(5)]
    followers = [user(str(20 + i), f'follows{i}') for i in range(2)] + [user(str(40 + i), f'fan{i}') for i in range(4)]
    return [page('Following', following, kind='user'), page('Followers', followers, kind='user')]


def large_collection():
    posts = [post(2000 + i, f'Post number {500 - i}.', when(29 - i // 20, 12), i % 50) for i in range(500)]
    return [page('UserTweets', posts[i * 20:(i + 1) * 20], f'p{i + 1}' if i < 24 else None, f'p{i}' if i else None) for i in range(25)]


def changed_handle():
    new = user('100', 'newname')
    return [page('UserTweets', [post(700 + i, f'Recent post {i}.', when(29 - i), 5, new) for i in (1, 2, 3, 4)])]


FIXTURES = {'1-repost': repost, '2-ranked-feed': ranked_feed, '3-date-window': date_window, '4-thread-sample': thread_sample,
            '5-search-bucket': search_bucket, '6-signature-substitute': signature_substitute, '7-friends': friends,
            '8-large-collection': large_collection, '9-changed-handle': changed_handle}


def skill_body(path, drop=None):
    """SKILL.md without its frontmatter, optionally without one body paragraph (headings are not paragraphs)."""
    text = re.sub(r'\A---\n.*?\n---\n', '', Path(path).read_text(encoding='utf-8'), count=1, flags=re.S).strip()
    blocks = text.split('\n\n')
    paragraphs = [i for i, block in enumerate(blocks) if not block.startswith('#')]
    if drop is not None:
        blocks.pop(paragraphs[drop])
        blocks = [b for i, b in enumerate(blocks) if not (b.startswith('#') and (i + 1 == len(blocks) or blocks[i + 1].startswith('#')))]
    return '\n\n'.join(blocks)


def paragraphs(path):
    text = re.sub(r'\A---\n.*?\n---\n', '', Path(path).read_text(encoding='utf-8'), count=1, flags=re.S).strip()
    return [block for block in text.split('\n\n') if not block.startswith('#')]


def prepare(base, scenario):
    """A run's scratch: working directory, seeded account state and the fake's script for this scenario."""
    work, home = base / 'work', base / 'home'
    work.mkdir(parents=True)
    home.mkdir()
    (home / 'session.json').write_text(json.dumps({'ct0': 'synthetic', 'viewer_id': '100', 'read_at': time.time()}))
    (home / 'txid.json').write_text(json.dumps({'key_bytes': list(base64.b64decode(FIXTURE['verification'])),
                                                'animation_key': FIXTURE['animation_key'], 'fetched_at': time.time()}))
    (base / 'script.json').write_text(json.dumps(FIXTURES[scenario['id']]()))
    return work, home


def run_once(out, copy, scenario, treatment, body, attempt, label):
    base = out / f'{label}-{scenario["id"]}-{treatment}-{attempt}'
    shutil.rmtree(base, ignore_errors=True)
    work, home = prepare(base, scenario)
    cli = copy / 'scripts/cli.py'
    call = f'uv run "{cli}"'
    prompt = (scenario['task'] + f'\n\nThe X reading CLI is `{call}`; start with its --help. Each shell call must be exactly one such command '
              'with its arguments: pipes, `;`, `&&`, redirections and shell variables are refused.')
    env = {**{k: v for k, v in os.environ.items() if not k.startswith(('TWITTER_', 'FAKE_', 'CLAUDE_CODE_'))},
           'PATH': PATH, 'TWITTER_HOME': str(home), 'TWITTER_ASIDE_BIN': str(FAKE), 'TWITTER_FAKE_SCRIPT': str(base / 'script.json'),
           'TWITTER_FAKE_LOG': str(base / 'requests.ndjson'), 'TWITTER_FAKE_TRACE': str(base / 'trace.ndjson'),
           'PYTHONPATH': str(DOUBLES), 'FAKE_NO_SLEEP': '1', 'TZ': 'UTC'}
    command = [CLAUDE, '-p', '--safe-mode', '--restricted', '--strict-mcp-config', '--tools', 'Bash', '--permission-mode', 'dontAsk',
               '--allowedTools', f'Bash({call} *)', '--model', MODEL, '--output-format', 'stream-json', '--verbose']
    if treatment == 'C':
        command += ['--append-system-prompt', body.replace('${CLAUDE_SKILL_DIR}', str(copy))]
    started = time.time()
    with open(base / 'stream.jsonl', 'w') as stream:
        done = subprocess.run([*command, prompt], cwd=work, env=env, stdout=stream, stderr=subprocess.PIPE, stdin=subprocess.DEVNULL,
                              text=True, timeout=1200)
    events = [json.loads(line) for line in (base / 'stream.jsonl').read_text().splitlines() if line.strip()]
    commands = [c['input'].get('command', '') for e in events if e.get('type') == 'assistant'
                for c in e['message'].get('content', []) if c.get('type') == 'tool_use']
    final = next((e for e in events if e.get('type') == 'result'), {})
    requests = len((base / 'requests.ndjson').read_text().splitlines()) if (base / 'requests.ndjson').exists() else 0
    reasons = [reason for reason, failed in [
        ('permission denied', bool(final.get('permission_denials'))),
        ('CLI never ran', not any(str(cli) in c for c in commands)),
        ('fake saw no request', requests == 0),
        ('SKILL.md in a command', any('SKILL.md' in c for c in commands)),
        ('claude failed', done.returncode != 0 or not final)] if failed]
    return dict(run=base.name, scenario=scenario['id'], treatment=treatment, label=label, attempt=attempt, invalid=reasons,
                commands=commands, answer=final.get('result', ''), requests=requests, turns=final.get('num_turns'),
                cost=final.get('total_cost_usd'), seconds=round(time.time() - started), stderr=done.stderr[-500:])


def run(out, copy, scenario, treatment, body, label):
    for attempt in range(1, 4):
        result = run_once(out, copy, scenario, treatment, body, attempt, label)
        print(json.dumps({k: result[k] for k in ('run', 'invalid', 'requests', 'turns', 'seconds')}), file=sys.stderr, flush=True)
        if not result['invalid']:
            return result
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('out', type=Path, help='Directory for results.jsonl and each run\'s stream.')
    parser.add_argument('--scenario', action='append', help='Scenario id to run; repeatable; default all.')
    parser.add_argument('--treatment', action='append', choices=['A', 'C'], help='Treatment; repeatable; default both.')
    parser.add_argument('--skill', type=Path, default=SKILL / 'SKILL.md', help='SKILL.md whose body treatment C appends.')
    parser.add_argument('--drop', type=int, help='Leave out this body paragraph (0-based) from treatment C.')
    parser.add_argument('--repeat', type=int, default=1, help='Runs per scenario and treatment.')
    parser.add_argument('--label', default='base', help='Prefix naming this batch in run directories and results.')
    parser.add_argument('--parallel', type=int, default=6, help='Runs at once.')
    options = parser.parse_args()
    scenarios = [s for s in json.loads((HERE / 'scenarios.json').read_text()) if not options.scenario or s['id'] in options.scenario]
    options.out.mkdir(parents=True, exist_ok=True)
    copy = Path(tempfile.mkdtemp(prefix='twitter-skill-copy-')) / 'twitter'
    shutil.copytree(SKILL / 'scripts', copy / 'scripts', ignore=shutil.ignore_patterns('__pycache__'))
    body = skill_body(options.skill, options.drop)
    jobs = [(s, t) for s in scenarios for t in (options.treatment or ['A', 'C']) for _ in range(options.repeat)]
    with ThreadPoolExecutor(options.parallel) as pool:
        results = list(pool.map(lambda job: run(options.out, copy, job[0], job[1], body, options.label), jobs))
    with open(options.out / 'results.jsonl', 'a') as stream:
        for result in results:
            stream.write(json.dumps(result, ensure_ascii=False) + '\n')
    print(f'{len(results)} runs, {sum(bool(r["invalid"]) for r in results)} still invalid after retries', file=sys.stderr)


if __name__ == '__main__':
    main()
