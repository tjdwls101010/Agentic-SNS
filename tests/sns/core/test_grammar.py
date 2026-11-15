"""The common grammar exposed by the assembled parser."""
import argparse

import pytest

import cli


def leaves():
    root = cli.parser(cli.load_platforms())
    branches = next(a for a in root._actions if isinstance(a, argparse._SubParsersAction))
    return {word: next(a for a in branch._actions if isinstance(a, argparse._SubParsersAction)).choices for word, branch in branches.choices.items()}


def test_core_commands_exist_on_their_platforms():
    for word, commands in leaves().items():
        assert {'feed', 'profile', 'about', 'me', 'post', 'search', 'images', 'doctor', 'schema'} <= commands.keys()
        assert ('graph' in commands) == (word in {'x', 'threads', 'naver-blog'})


def test_shared_options_mean_the_same_everywhere():
    """The options every reading command shares read the same on every platform (only the time zone differs); the
    closed-set options keep one name and offer their platform's own words as choices, with their own wording."""
    zones = ('Korea time (KST)', "this computer's time zone", "X's own days (this account's time zone)")
    shared, closed = {'--since', '--until', '--limit', '--chars', '--after', '--out', '--json'}, {'--tab', '--sort',
                                                                                                    '--type'}
    helps = {}
    for word, commands in leaves().items():
        for name, parser in commands.items():
            for action in parser._actions:
                flag = next((f for f in action.option_strings if f in shared | closed | {'--in'}), None)
                if flag is None:
                    continue
                assert action.help and action.help.strip(), (word, name, flag)
                if flag in closed:
                    assert action.choices, (word, name, flag)
                # a composite read's --out saves the whole read at once, not page by page: its own wording
                if flag in shared and (word, name, flag) != ('naver-blog', 'post', '--out'):
                    text = action.help
                    for zone in zones:
                        text = text.replace(zone, 'ZONE')
                    helps.setdefault(flag, set()).add(text)
    assert set(helps) == shared
    assert all(len(texts) == 1 for flag, texts in helps.items() if flag not in ('--limit', '--chars')), helps


def test_no_old_view_flags_and_positional_labels():
    old = {'--popular', '--notices', '--top', '--followers', '--groups', '--feed', '--filter'}
    labels = {'ACCOUNT', 'POST', 'SUB', 'GROUP', 'LIST', 'COMMUNITY', 'BLOG', 'HANDLE', 'TEXT', 'RELATION', 'KIND', 'N', 'PAGE', 'object'}
    for commands in leaves().values():
        for parser in commands.values():
            for action in parser._actions:
                assert not old.intersection(action.option_strings)
                if not action.option_strings:
                    assert (action.metavar or action.dest) in labels


@pytest.mark.parametrize('argv', [
    ['x', 'feed', '--feed', 'following'], ['threads', 'feed', '--feed', 'following'],
    ['reddit', 'profile', 'u/example', '--type', 'posts'], ['threads', 'activity'],
    ['threads', 'me', 'activity', '--filter', 'all'], ['facebook', 'notifications'],
    ['facebook', 'search', 'x', '--in-group', 'g'], ['naver-blog', 'search', 'x', '--blog', 'b'],
    ['naver-blog', 'search', 'x', '--sort', 'sim'], ['naver-blog', 'blog', 'b'],
    ['naver-blog', 'posts', 'b'], ['naver-blog', 'profile', 'b', '--popular'],
    ['naver-blog', 'profile', 'b', '--notices'], ['naver-blog', 'buddies'],
    ['naver-blog', 'buddies', '--followers'], ['naver-blog', 'buddies', '--groups'],
    ['naver-blog', 'topic', '5', '--top'],
])
def test_old_forms_are_argument_errors(argv):
    assert cli.main(argv) == 2
