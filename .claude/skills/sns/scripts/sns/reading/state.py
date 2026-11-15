"""Taking in what an install from before the state moved left in its data/ beside SKILL.md (paths.legacy_dir()).

Not a one-time copy: every command looks again, because a copy of the old version may still write there, or a person
may put an old data/ back after an update; the protection store takes the content in whenever it differs from what it
last took from that path. Every platform and Aside account the old data/ holds is taken in by whichever command runs
first, because the next reinstall removes the folder again. The old data/ is never changed or removed.
"""
from sns import handles, protection
from sns.errors import SnsError
from sns.paths import legacy_dir
from sns.session import adopt as adopt_session


def adopt_all(platforms, deadline, own=None, legacy=None):
    """Take the old data/ in for every platform (adapters) and every Aside account it holds, then the handle
    numbering; before the command resolves its account, opens its session or sends anything. A failure to take in
    the command's `own` platform stops the command (it must not send past a block it could not read); another
    platform's is left for that platform's next command. Returns the old protection folders taken in this time."""
    legacy = legacy or legacy_dir()
    if legacy is None:
        return []
    taken = []
    for platform in platforms:
        root = legacy / platform.key
        try:
            accounts = sorted(p.name for p in root.iterdir() if p.is_dir()) if root.exists() else []
        except OSError:
            if platform.key == own:
                raise SnsError('blocked', f'The old state in {root} cannot be read, so requests are refused.',
                               f'Make {root} readable (or move that old data/ away after checking it), then run the '
                               'command again.', reason='unreadable') from None
            accounts = []
        for account in accounts:
            try:
                if adopt(platform, account, deadline, legacy=legacy):
                    taken.append(str(root / account / 'protection'))
            except ValueError:
                continue  # not a name this skill ever wrote (an account id is [A-Za-z0-9_-])
            except SnsError:
                if platform.key == own:
                    raise
    if (legacy / 'handles').is_dir():
        handles.adopt_counter(legacy / 'handles')
    return taken


def adopt(platform, account, deadline, legacy=None):
    """Take the old data/ in for `platform` (the adapter) and Aside `account`: protection (merged under its lock),
    then the session files this account has none of. Unreadable old protection state becomes a person block, so
    nothing is skipped silently. True when protection state was taken in."""
    legacy = legacy or legacy_dir()
    if legacy is None:
        return False
    root = legacy / platform.key / account
    taken = False
    if (root / 'protection').is_dir():
        guard = protection.open(platform.key, account, platform.policy, deadline, title=platform.title,
                                site=platform.site)
        taken = guard.adopt(root / 'protection')
    if (root / 'session').is_dir():
        adopt_session(platform.key, account, root / 'session')
    return taken

