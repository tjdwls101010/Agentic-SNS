"""The full commands a result names (more:, resume:, replies <handle>): the cli.py that was invoked, double-quoted the
way the skill's allowed-tools rule spells it, so the line runs as written and matches the permission rule."""
import os
import re
import shlex


def invocation(cli_path):
    """`uv run "<cli.py>"` for the cli.py that is running (a copied skill names its own copy)."""
    return 'uv run "' + re.sub(r'([\\"$`])', r'\\\1', os.path.abspath(cli_path)) + '"'


def command_line(cli_path, words):
    return invocation(cli_path) + ' ' + shlex.join(str(word) for word in words)


def words(platform, command, target, identity_words, options, *, after=None, out=None, limit=..., chars=None):
    """The argument words that rerun or continue a command: the platform word, the command, the target (last, after
    `--`, when it looks like an option), its identity options, --limit/--chars/--after/--out/--json."""
    result = [platform.replace('_', '-'), command]
    tail = []
    targets = target if isinstance(target, list) else ([] if target is None else [target])
    for value in targets:
        if str(value).startswith('-'):
            tail = ['--', *map(str, targets)]
            break
    else:
        result += [str(value) for value in targets]
    result += list(identity_words)
    limit = options.get('limit') if limit is ... else limit  # an explicit None drops --limit
    if limit is not None:
        result += ['--limit', str(limit)]
    chars = options.get('chars') if chars is None else chars
    if chars is not None:
        result += ['--chars', str(chars)]
    if after is not None:
        result += ['--after', str(after)]
    if out is not None:
        result.append('--out=' + str(out))
    if options.get('json'):
        result.append('--json')
    return result + tail
