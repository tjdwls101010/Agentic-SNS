"""The command surface as the model reads it (cli.py): a top-level map of every platform's commands that fits a screen,
then each command's --help explaining every argument, its closed sets and the exit codes it can return, alone."""
import argparse
import json
import re
import subprocess
import sys

import pytest

import cli
from sns.results import KINDS
from tests.sns.support.cli import CLI
from tests.sns.support.stub_platform import STUBS, STUB_COMMANDS, STUB_CHOICES

REAL_PLATFORMS = cli.load_platforms()
PLATFORMS = {**REAL_PLATFORMS, **STUBS}
REAL_COMMANDS, REAL_CHOICES = cli.command_tables(REAL_PLATFORMS)
COMMANDS = {**REAL_COMMANDS, **STUB_COMMANDS}
CHOICES = {**REAL_CHOICES, **STUB_CHOICES}


def leaves():
    root = cli.parser(PLATFORMS, commands=COMMANDS)
    found = []
    for action in root._actions:  # argparse keeps its tree here; there is no public accessor
        if isinstance(action, argparse._SubParsersAction):
            for word, branch in action.choices.items():
                for sub in branch._actions:
                    if isinstance(sub, argparse._SubParsersAction):
                        found += [(word, name, leaf) for name, leaf in sub.choices.items()]
    return found


def test_the_top_level_map_fits_a_screen_and_names_every_command():
    """The map (plan 'help 구조'): each core word's meaning once, then one line per platform with every command it has,
    the platform's own places after |, doctor and schema named once for all; at most 40 lines."""
    text = cli.parser(PLATFORMS, commands=COMMANDS).format_help()
    lines = text.splitlines()
    assert len(lines) <= 40, len(lines)
    meanings, platforms = text.split('platforms and their commands')
    for word in cli.CORE_COMMANDS:  # each word once, where a column starts
        assert len(re.findall(rf'(?:^  |   |^  replies, ){word}[ ,]', meanings, re.M)) == 1, word
    assert 'every platform also has doctor and schema' in platforms
    for word, module in PLATFORMS.items():
        line = next(line for line in lines if line.strip().startswith(word + ' '))
        core, _, own = ' '.join(line.split()[1:]).partition(' | ')
        assert set(core.split()) <= set(cli.CORE_COMMANDS) and not set(own.split()) & set(cli.CORE_COMMANDS), word
        named = core.split() + own.split() + ['doctor', 'schema']
        assert sorted(named) == sorted(cli.surface(module, COMMANDS[word])), word
    exits = text.split('exit codes:')[1]
    assert all(f'{code} {cli.EXIT_SUMMARY[code]}' in ' '.join(exits.split()) for code in cli.EXIT_CODES)
    assert ' idle' not in text


@pytest.mark.parametrize('word,name,leaf', leaves(), ids=lambda v: v if isinstance(v, str) else '')
def test_each_command_explains_every_argument_and_only_its_exit_codes(word, name, leaf):
    text = leaf.format_help()
    for action in leaf._actions:
        if action.dest == 'help':
            continue
        assert action.help and action.help != argparse.SUPPRESS, (word, name, action.dest)
    spec = cli.surface(PLATFORMS[word], COMMANDS[word])[name]
    listed = [line.split()[0] for line in text.split('exit codes:\n')[1].splitlines() if line.strip()]
    assert [int(code) for code in listed] == list(spec['exits'])
    assert set(spec['exits']) <= set(cli.EXIT_CODES) and 0 in spec['exits'] and 2 in spec['exits']
    assert all(len(line) <= 90 for line in text.split('exit codes:\n')[1].splitlines()), (word, name)
    assert 'max-requests' not in text and 'max_requests' not in text


@pytest.mark.parametrize('word', sorted(PLATFORMS))
def test_closed_sets_are_choices_and_match_the_platforms_choices(word):
    found = {}
    for name, spec in COMMANDS[word].items():
        for argument in spec['arguments']:
            if isinstance(argument, str):
                continue
            flags, settings = argument
            if 'choices' in settings:
                dest = settings.get('dest') or flags[-1].lstrip('-').replace('-', '_')
                found[f'{name}.{dest}'] = list(settings['choices'])
    assert found == CHOICES[word]


def test_every_result_kind_has_one_exit_code_and_every_code_a_kind():
    assert set(cli.KIND_EXIT) == set(KINDS)
    assert set(cli.KIND_EXIT.values()) == set(cli.EXIT_CODES) == set(cli.EXIT_SUMMARY)


def test_the_real_entry_point_prints_its_help():
    done = subprocess.run([sys.executable, str(CLI), '--help'], capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout.startswith('usage: cli.py [--verbose] <platform> <command>')


def test_bad_arguments_are_one_json_envelope_and_exit_2():
    done = subprocess.run([sys.executable, str(CLI), 'nowhere', 'feed'], capture_output=True, text=True)
    assert done.returncode == 2 and '"error": "argument"' in done.stdout


def test_every_images_help_says_how_numbers_and_stops_work():
    """reading.pictures is shared: what it does with a number the post lacks and with a stop is told the same way."""
    for key in ('x', 'reddit', 'threads', 'facebook', 'naver_blog'):
        text = ' '.join(REAL_COMMANDS[key.replace('_', '-')]['images']['epilog'])
        assert 'more:' in text and 'numbers left' in text, key


# --- how long a leaf is, and what it may name (plan 'help 구조': the measured targets) --------------------------------

REAL_LEAVES = [(word, name, leaf) for word, name, leaf in leaves() if word in REAL_PLATFORMS]
TAB_PLATFORMS = {word for word, module in REAL_PLATFORMS.items() if module.PLATFORM.transport == 'tab'}


@pytest.fixture
def width(monkeypatch):
    """argparse wraps the usage to the terminal; measure at one width."""
    monkeypatch.setenv('COLUMNS', '80')


def parts(text):
    """(③④, ⑤, ⑥) of a leaf: what it reads up to its one requests: line, the common block, the exit codes."""
    head, exits = text.split('\nexit codes:\n')
    lines = head.split('\n')
    marks = [i for i, line in enumerate(lines) if line.startswith('requests:')]
    if not marks:
        return head, '', exits
    assert len(marks) == 1, marks
    return '\n'.join(lines[:marks[0] + 1]), '\n'.join(lines[marks[0] + 1:]), exits


@pytest.mark.parametrize('word,name,leaf', REAL_LEAVES, ids=lambda v: v if isinstance(v, str) else '')
def test_a_leaf_says_what_it_reads_first_and_stays_short(word, name, leaf, width):
    text = leaf.format_help()
    reads, common, _ = parts(text)
    assert len(text) <= 3200, len(text)
    assert len(reads) <= 2500, len(reads)
    assert (name == 'doctor') == ('\nrequests:' not in reads), 'every command but doctor has its one requests: line'
    common = [line for line in common.splitlines() if line.strip()]
    assert len(common) <= 6, common
    if name in ('doctor', 'schema'):
        return
    flags = {flag for action in leaf._actions for flag in action.option_strings}
    joined = '\n'.join(common)
    assert 'saved=' in joined and f'{word} schema result' in joined
    for flag in ('--json', '--out'):
        assert (flag in joined) == (flag in flags), flag
    assert ('tab opened' in joined) == (word in TAB_PLATFORMS)


def test_all_leaves_together_are_half_of_what_they_were(width):
    total = sum(len(leaf.format_help()) for _, _, leaf in REAL_LEAVES)
    assert total <= 140_000, total


@pytest.mark.parametrize('word,name,leaf', leaves(), ids=lambda v: v if isinstance(v, str) else '')
def test_a_leaf_names_only_the_options_its_parser_has(word, name, leaf):
    flags = {flag for action in leaf._actions for flag in action.option_strings}
    named = set(re.findall(r'(?<![\w-])--[a-z][a-z0-9-]*', leaf.format_help()))
    assert named <= flags, sorted(named - flags)


def test_the_tab_is_explained_by_doctor_and_record_kinds_by_schema(capsys):
    for word, name, leaf in REAL_LEAVES:
        text = leaf.format_help()
        assert ('the dedicated tab:' in text) == (name == 'doctor' and word in TAB_PLATFORMS), (word, name)
        assert 'labelled [' not in text, (word, name)
    for word, label in (('x', '[t1] trend'), ('threads', '[n1] notification'), ('facebook', '[e1] person')):
        cli.main([word, 'schema', 'result'])
        assert label in json.loads(capsys.readouterr().out)['results'][0]['text']['records'], word


CHAIN = {'x': 'replies', 'threads': 'replies', 'reddit': 'comments', 'facebook': 'replies', 'naver-blog': 'comments'}


@pytest.mark.parametrize('word', sorted(CHAIN))
def test_following_one_lead_reads_at_most_15000_characters_of_help(word, width):
    """The leadchain path (a post, its branch, the author's posts, a related search, its pictures) read the way the
    help is built to be read: the top-level map, then each leaf once — no platform-level help (the map names every
    command). It was about 30,000 characters in nine reads."""
    by_name = {name: leaf for w, name, leaf in REAL_LEAVES if w == word}
    path = ['post', CHAIN[word], 'profile', 'search', 'images']
    total = len(cli.parser(cli.load_platforms()).format_help()) + sum(len(by_name[name].format_help()) for name in path)
    assert total <= 15_000, total
