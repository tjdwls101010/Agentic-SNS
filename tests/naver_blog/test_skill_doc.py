"""SKILL.md is prose about Naver Blog, and these checks are what keep it that way.

Command names, flags, defaults and exit codes belong to --help, schema and each error's fix,
because editing the code changes those and cannot change a sentence written here. A rule
listed in the body holds only the cases its author enumerated; a reason lets the model work
out the case nobody thought of. So what is asserted is the absence of the manual, not its
correctness — the manual is checked by test_cli.py against the interface that owns it.
"""
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / '.claude/skills/naver-blog/SKILL.md'
ENTRY = ROOT / '.claude/skills/naver-blog/scripts/naver_blog.py'
COMMANDS = ['search', 'blog', 'posts', 'post', 'comments', 'find', 'buddies', 'home', 'topic',
            'monthly', 'doctor', 'schema']


@pytest.fixture(scope='module')
def document():
    return SKILL.read_text(encoding='utf-8')


@pytest.fixture(scope='module')
def body(document):
    return document.split('---', 2)[2]


@pytest.fixture(scope='module')
def helps():
    texts = {'': subprocess.run([sys.executable, str(ENTRY), '--help'],
                                capture_output=True, text=True).stdout}
    for command in COMMANDS:
        texts[command] = subprocess.run([sys.executable, str(ENTRY), command, '--help'],
                                        capture_output=True, text=True).stdout
    return texts


def test_the_body_names_no_flags(body):
    """A flag's spelling and default live in --help, which cannot drift from the parser.

    --help itself is the exception: it is the pointer to that interface, not a part of it.
    """
    flags = [flag for flag in re.findall(r'(?<![\w-])--[a-z][a-z-]+', body) if flag != '--help']
    assert flags == [], flags


def test_the_body_states_no_exit_codes(body):
    assert re.search(r'\bexit\s+\d', body, re.I) is None
    assert 'exit code' not in body.lower()


def test_the_body_has_no_command_table(body):
    """A table of commands is a manual; it goes stale the first time one is added."""
    for line in body.splitlines():
        if line.strip().startswith('|'):
            pytest.fail('SKILL.md has a table: ' + line)


def test_the_body_does_not_enumerate_the_command_list(body):
    """Naming every command here duplicates the subcommand list --help already prints."""
    named = [command for command in COMMANDS if re.search(rf'`{command}[ `]', body)]
    assert len(named) <= 4, named


def test_the_body_never_repeats_a_sentence_from_the_help(body, helps):
    """A sentence in both places is one that can be edited in one and left wrong in the other."""
    sentences = [part.strip() for part in re.split(r'(?<=[.!?])\s+', body) if len(part.strip()) > 40]
    combined = ' '.join(helps.values())
    duplicated = [sentence for sentence in sentences if sentence in combined]
    assert duplicated == [], duplicated


def test_every_section_says_what_is_true_and_what_follows_from_it(body):
    """A section that only states facts leaves the model to guess what to do with them."""
    consequence = re.compile(
        r'\bso\b|\bthe consequence\b|\bmeans\b|\bwhich is\b|\brather than\b|\bnever\b|\bmust\b'
        r'|\bcannot\b|\bit follows\b|\binstead\b|\bwhat you have\b|\bwhat matters\b', re.I)
    for section in body.split('\n## ')[1:]:
        title, text = section.split('\n', 1)
        assert consequence.search(text), f'section states facts without a consequence: {title}'


def test_the_description_says_what_is_out_of_scope(document):
    description = document.split('description:', 1)[1].split('---', 1)[0]
    assert 'Not for' in description
    # The near misses a reader would otherwise route here.
    for neighbour in ('Naver Cafe', 'Naver News', 'Tistory'):
        assert neighbour in description, neighbour
    assert 'blog.naver.com' in description


def test_the_description_carries_korean_triggers(document):
    description = document.split('description:', 1)[1].split('---', 1)[0]
    assert '네이버 블로그' in description
    korean = re.findall(r'[가-힣]{2,}', description)
    assert len(korean) >= 8, korean


def test_the_skill_allows_only_its_own_entry_point(document):
    allowed = document.split('allowed-tools:', 1)[1].split('\n', 1)[0]
    assert allowed.strip() == 'Bash(python3 "${CLAUDE_SKILL_DIR}/scripts/naver_blog.py" *)'


def test_the_body_points_at_the_interfaces_that_own_the_details(body):
    for pointer in ('--help', 'schema', 'fix'):
        assert pointer in body, pointer
