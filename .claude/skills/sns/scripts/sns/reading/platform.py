"""What a platform hands the shared pipeline, and what the pipeline hands a platform's reader."""
from dataclasses import dataclass, field
from typing import Callable

from sns.errors import SnsError


@dataclass(frozen=True)
class Platform:
    """One platform's adapter, exported by its package as PLATFORM.

    key: the package name (x, threads, reddit, facebook, naver_blog); the command word is key with - for _.
    title, site: how messages name it (X, x.com).
    transport: 'tab' (a dedicated tab whose app makes the requests) or 'fetch' (tab-less requests in the REPL).
    policy: its limits.LimitPolicy; window: its window.WindowPolicy.
    connect(connection) → client: the platform's client (its web system), built from the connection's aside, guard and
      session. The client protocol: start() → the platform account the page shows (tab) or None (fetch); viewer() →
      the platform account, asking the platform when it must (one request); release() → the tab lease token to leave
      to the idle cleanup, or None; report() → {setup, unwatched, session_reset} beyond the guard's counts;
      verify(check) → make the unblock check's one request inside protection's verify_unblock and raise unless the
      answer is clean (the caller then clears); release_tab() → the idle cleanup: take in what the tab saw, then empty
      it (connection.empty_tab), True once nothing polls; doctor() → the platform's own doctor fields.
      What every client must do, because the pipeline cannot see it: send each request inside guard.request() and
      classify every answer (slot.classify — an unclassified one counts as lost); record what the answer said before
      leaving the slot (slot.fact for limit headers, raise slot.hold(...) for a 429, raise slot.block(...) for a
      person block); take in what an open tab saw on its own (background requests via slot.charge or
      guard.log_unwatched, their block signals and limit headers) before its next request; pass every account a
      response shows to connection.seen(); in verify, make exactly one request (the first non-setup request in the
      check's scope uses the check's reservation) and raise unless the answer is clean and for the account the block
      names; keep learned query ids in the session with bounded recovery (a fixed number of relearns or reloads per
      command), so a failing page never loops.
    render(envelope, chars, command) → the record lines of a text page, or (lines, shown) when the number of records
      the header should name differs from len(results) (a post's context rows, a tree's parent lines).
    schemas: {object name: schema document} for its records.
    locate(url) → (command, argument) when the URL is this platform's and that command opens it, else None (pure).
    unblock_scope: the scope the unblock check's request is counted in (X Viewer, Reddit general), or None.
    idle_action: what empties its dedicated tab first: 'close' or 'blank' (tab platforms), None (fetch).
    """
    key: str
    title: str
    site: str
    transport: str
    policy: object
    window: object
    connect: Callable
    render: Callable
    schemas: dict = field(default_factory=dict)
    locate: Callable = lambda url: None
    unblock_scope: str | None = None
    idle_action: str | None = None

    @property
    def word(self):
        return self.key.replace('_', '-')


@dataclass
class Invocation:
    """One run of cli.py: its options, the deadline made at process start, every platform (to name the right one for a
    URL), the cli.py that was invoked (for more: lines) and the exit table (for schema)."""
    options: dict
    deadline: object
    platforms: dict
    cli_path: str
    exit_codes: list = field(default_factory=list)

    @property
    def verbose(self):
        return bool(self.options.get('verbose'))


def foreign(platform, invocation, target):
    """Refuse a URL another platform reads, naming the command that reads it (before any request)."""
    for value in target if isinstance(target, list) else [target]:
        if not isinstance(value, str) or '://' not in value and not value.split('/')[0].count('.'):
            continue
        if platform.locate(value):
            continue
        for other in invocation.platforms.values():
            if other.key == platform.key:
                continue
            found = other.locate(value)
            if found:
                command, argument = found
                raise SnsError('argument', f'This is a {other.title} link, not a {platform.title} one.',
                               f'Read it with: {other.word} {command} {argument}')
