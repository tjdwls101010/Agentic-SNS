"""The command surface as the model reads it (cli.py): a top-level map of every platform's commands that fits a screen,
then each command's --help explaining every argument, its closed sets and the exit codes it can return, alone."""
import argparse
import subprocess
import sys

import pytest

import cli
from sns.results import KINDS
from tests.sns.support.cli import CLI
from tests.sns.support.stub_platform import STUBS

PLATFORMS = {**cli.load_platforms(), **STUBS}


def leaves():
    root = cli.parser(PLATFORMS)
    found = []
    for action in root._actions:  # argparse keeps its tree here; there is no public accessor
        if isinstance(action, argparse._SubParsersAction):
            for word, branch in action.choices.items():
                for sub in branch._actions:
                    if isinstance(sub, argparse._SubParsersAction):
                        found += [(word, name, leaf) for name, leaf in sub.choices.items()]
    return found


def test_the_top_level_map_fits_a_screen_and_names_every_command():
    text = cli.parser(PLATFORMS).format_help()
    assert len(text.splitlines()) <= 40, len(text.splitlines())
    for word, module in PLATFORMS.items():
        line = next(line for line in text.splitlines() if line.strip().startswith(word + ' '))
        assert line.split()[1:] == list(cli.surface(module)), word
    assert ' idle' not in text


@pytest.mark.parametrize('word,name,leaf', leaves(), ids=lambda v: v if isinstance(v, str) else '')
def test_each_command_explains_every_argument_and_only_its_exit_codes(word, name, leaf):
    text = leaf.format_help()
    for action in leaf._actions:
        if action.dest == 'help':
            continue
        assert action.help and action.help != argparse.SUPPRESS, (word, name, action.dest)
    spec = cli.surface(PLATFORMS[word])[name]
    listed = [line.split()[0] for line in text.split('exit codes:\n')[1].splitlines() if line.strip()]
    assert [int(code) for code in listed] == list(spec['exits'])
    assert set(spec['exits']) <= set(cli.EXIT_CODES) and 0 in spec['exits'] and 2 in spec['exits']
    assert 'max-requests' not in text and 'max_requests' not in text


@pytest.mark.parametrize('word', sorted(PLATFORMS))
def test_closed_sets_are_choices_and_match_the_platforms_choices(word):
    module = PLATFORMS[word]
    found = {}
    for name, spec in module.COMMANDS.items():
        for argument in spec['arguments']:
            if isinstance(argument, str):
                continue
            flags, settings = argument
            if 'choices' in settings:
                dest = settings.get('dest') or flags[-1].lstrip('-').replace('-', '_')
                found[f'{name}.{dest}'] = list(settings['choices'])
    assert found == module.CHOICES


def test_every_result_kind_has_one_exit_code_and_every_code_a_kind():
    assert set(cli.KIND_EXIT) == set(KINDS)
    assert set(cli.KIND_EXIT.values()) == set(cli.EXIT_CODES) == set(cli.EXIT_SUMMARY)


def test_the_real_entry_point_prints_its_help():
    done = subprocess.run([sys.executable, str(CLI), '--help'], capture_output=True, text=True)
    assert done.returncode == 0 and done.stdout.startswith('usage: cli.py [--verbose] <platform> <command>')


def test_bad_arguments_are_one_json_envelope_and_exit_2():
    done = subprocess.run([sys.executable, str(CLI), 'nowhere', 'feed'], capture_output=True, text=True)
    assert done.returncode == 2 and '"error": "argument"' in done.stdout
