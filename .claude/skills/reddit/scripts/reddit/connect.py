"""Shared wiring of the reading commands: a guarded connection pinned to one Aside account, the account check, handles,
--out files, and the finished result."""
from reddit import guard as protection
from reddit import handles
from reddit.aside import Aside
from reddit.collection import OutFile, peek, resolve
from reddit.errors import RedditError
from reddit.paging import paginate
from reddit.reddit_web import Client
from reddit.results import finish
from reddit.window import Window

DISPLAY = 25


class Connection:
    """One invocation's connection: the Aside account (resolved before any request), its guard and the client.

    Built first and started second, so the requests a failed start already made are still reported.
    """

    def __init__(self, budget, verbose=False, bound=True):
        self.aside = Aside()
        self.guard = protection.Guard(self.aside.account, budget)
        self.client = Client(self.aside, self.guard, verbose)
        self.bound = bound           # whether the reading can leave a handle or a file tied to a Reddit account
        self.reddit_account = None   # the Reddit account confirmed by this invocation's check, if it made one
        self.observed = None         # the Reddit account a continued reading was read with

    @property
    def account(self):
        return self.aside.account

    def start(self):
        """Refuse a standing block before anything is read."""
        self.guard.check()
        return self

    def network(self):
        """The client, once a bound reading has confirmed which Reddit account the browser is logged in to (one
        request, made before the first other request of the invocation) and that it is the one a continued reading
        was read with. A reading served from what a handle kept never gets here, so it makes no request."""
        if self.bound and self.reddit_account is None:
            self.reddit_account = self.client.account()
        if self.observed is not None and self.reddit_account is not None and self.observed != self.reddit_account:
            raise RedditError(4, f'This reading was read as u/{self.observed}, but the Aside browser is now logged in '
                                 f'to Reddit as u/{self.reddit_account}.', 'Run the original command again (without '
                                                                           '--after) to read as the current account.',
                              reason='account_changed')
        return self.client

    def report(self):
        """What finish() needs to know about the requests."""
        return {'requests': self.guard.used, 'reddit': self.guard.window(), 'slowest': self.guard.slowest}


def run(options, *, command, target, identity, reader, window=None, bound=True):
    """Run one reading command and finish it into (kind, envelope).

    reader(connection, state, out) returns a reading (see results.finish) and may set 'continuation' to
    {command, target, identity, words, state}: what a later invocation needs to go on from here. A bound reading (one
    that can leave a handle or an --out file) checks the Reddit account first; the others say they did not.
    """
    connection, reading = None, None
    out_path = options.get('out')
    try:
        connection = Connection(options['max_requests'], options.get('verbose'), bound)
        if out_path:
            reading = _settled_file(out_path, _context(command, target, identity, connection.account, None))
        if reading is None:
            connection.start()
            reading = _read(connection, options, command, target, identity, reader, out_path)
    except RedditError as error:
        reading = {**(reading or {}), 'failure': error}
        reading.setdefault('results', [])
    if window is not None and 'window' not in reading:
        reading['window'] = window
    report = connection.report() if connection else {'requests': 0, 'reddit': {}, 'slowest': 0}
    account = None
    if connection is not None and bound:
        account = {'observed': reading.get('observed') or connection.observed or connection.reddit_account,
                   'checked': connection.reddit_account is not None}
    elif connection is not None:
        account = {'observed': None, 'checked': False}
    kind, envelope = finish(reading, command=command, requests=report['requests'], budget=options['max_requests'],
                            identity=_public(identity), out=str(resolve(out_path)) if out_path else None,
                            reddit=report['reddit'], account=account)
    if report['slowest'] >= 10:
        envelope['slowed'] = round(report['slowest'])
    return kind, envelope


def _settled_file(path, context):
    """Decide a --out file from the file alone, before any request: a foreign or older file is refused, a complete
    one reads nothing. Returns the reading of a complete file, else None (read on)."""
    saved, complete, count = peek(path)
    if saved is None:
        return None
    if {k: v for k, v in saved.items() if k != 'reddit_account'} != {k: v for k, v in context.items()
                                                                     if k != 'reddit_account'}:
        raise RedditError(2, 'The --out file belongs to another command, target, order, window or account.',
                          'Use a new --out path, or rerun the command that started this file.')
    if complete:
        return {'results': [], 'stop_reason': 'exhausted', 'already_complete': True, 'count': count,
                'observed': saved.get('reddit_account')}
    return None


def _read(connection, options, command, target, identity, reader, out_path):
    state = None
    if options.get('after'):
        state, connection.observed = handles.load(connection.account, options['after'],
                                                  _context(command, target, identity, connection.account, None))
    if out_path:
        connection.network()  # a collection is always read now, and its file is tied to the account that reads it
    out = OutFile(out_path, _context(command, target, identity, connection.account, connection.reddit_account)) \
        if out_path else None
    reading = None
    try:
        if out is not None and out.complete:
            reading = {'results': [], 'stop_reason': 'exhausted', 'already_complete': True}
        else:
            reading = reader(connection, state, out)
        reading.setdefault('observed', connection.observed or connection.reddit_account)
        if out is not None:
            reading['count'] = out.count
            reading['continuable'] = out.state is not None and not out.complete
            failure = reading.get('failure')
            stopped = isinstance(failure, RedditError) and failure.code in (4, 5, 9)
            if not stopped and (reading.get('stop_reason') in ('budget', 'window_spent', 'probe_pending')
                                or isinstance(failure, RedditError)):
                reading['next'] = words(command, target, reading.get('words', []), options, out=out_path)
    finally:
        if out is not None:
            out.close()
    _continue(reading, options, connection)
    return reading


def _continue(reading, options, connection):
    continuation = reading.pop('continuation', None)
    failure = reading.get('failure')
    if not continuation or options.get('out') or (isinstance(failure, RedditError) and failure.code in (4, 5, 9)):
        return  # after a block, a logout or an unreadable target, a continuation would only invite another request
    context = _context(continuation['command'], continuation['target'], continuation['identity'], connection.account,
                       reading.get('observed') or connection.reddit_account)
    try:
        number = handles.save(connection.account, context, continuation['state'])
    except RedditError as error:
        current = reading.get('failure')
        reading['failure'] = error if current is None or current.code == 8 else current
        return
    reading['continuable'] = True
    reading['next'] = words(continuation['command'], continuation['target'], continuation['words'], options,
                            after=number, limit=continuation.get('limit', ...))


def words(command, target, identity_words, options, *, after=None, out=None, limit=..., chars=None):
    """The argument words that rerun or continue a command: target last after `--` when it looks like an option."""
    result = [command]
    tail = []
    if target is not None:
        if str(target).startswith('-'):
            tail = ['--', str(target)]
        else:
            result.append(str(target))
    result += identity_words
    limit = options.get('limit') if limit is ... else limit  # an explicit None drops --limit
    if limit is not None:
        result += ['--limit', str(limit)]
    chars = options.get('chars') if chars is None else chars
    if chars is not None:
        result += ['--chars', str(chars)]
    if after is not None:
        result += ['--after', str(after)]
    if out is not None:
        result.append('--out=' + out)
    if options.get('json'):
        result.append('--json')
    if options.get('max_requests') not in (None, protection.DEFAULT_BUDGET):
        result += ['--max-requests', str(options['max_requests'])]
    return result + tail


def _context(command, target, identity, aside_account, reddit_account):
    return {'command': command, 'target': target, **identity, 'aside_account': aside_account,
            'reddit_account': reddit_account}


def _public(identity):
    """The identity options a result names in its header."""
    return {key: value for key, value in identity.items()
            if key in ('sort', 'time', 'type', 'collection', 'within') and value is not None}


def read_pages(connection, options, identity, state, out, *, request, command, target, words=None, extra=None):
    """A listing read page by page in Reddit's order, as a reading for run().

    A page asks for 100 records and shows --limit of them (25 by default); the rest wait in the handle, so the next
    more: shows them with no request. A date window is only for sort new (a timeline): it keeps the records of its
    local days and closes at the first record older than --since, pinned posts aside; a listing that ends first did
    not cover the window (partial).
    """
    start = dict(out.state or {}) if out is not None else dict(state or {})
    window = Window(options.get('since'), options.get('until'), start.pop('window', None))
    for key in (extra or {}):
        start.pop(key, None)

    received = []

    def fetch(cursor):
        records, after = connection.network().listing(request(cursor))
        received.append(len(records))
        return records, {'has_next_page': after is not None, 'end_cursor': after}, bool(records)

    def commit(records, page_state, reason, skipped):
        out.commit(records, {**page_state, 'window': window.state(), **(extra or {})} if page_state else None, reason,
                   skipped, window.report())

    if out is not None:
        start.update(seen=sorted(out.ids, key=str), pending=[])
    limit = options.get('limit') or (None if out is not None else DISPLAY)
    if out is not None and options.get('limit') is not None:
        if out.count >= options['limit']:
            return {'results': [], 'stop_reason': 'limit_reached', 'words': _words(identity, words)}
        limit -= out.count
    closes = window.closes if window.active and window.bounds['start'] is not None else None
    result = paginate(fetch, limit=limit, state=start, keep=window.keep, closes=closes,
                      commit=commit if out is not None else None, whole_pages=out is not None)
    stop, failure = result['stop_reason'], result['failure']
    if stop == 'exhausted' and not any(received) and not start.get('seen') and not start.get('cursor'):
        failure = RedditError(7, 'Reddit returned nothing here.', 'Try another target, order or period.')
    elif stop == 'exhausted' and window.bounds['start'] is not None:
        failure = RedditError(8, 'The listing ended before the window\'s start: Reddit had no older posts to show '
                                 'here, so the window is not covered.', 'Use a later --since, or search with --sort '
                                                                        'new instead of reading the listing.',
                              reason='listing_ended')
    reading = {'results': [] if out is not None else result['results'], 'stop_reason': stop, 'failure': failure,
               'coverage': window.report(), 'words': _words(identity, words), 'partial': bool(result['results'])}
    if window.active:
        reading['window'] = window.describe()
    if not result['results'] and failure is None and result['state'] is None and out is None and not window.active:
        reading['failure'] = RedditError(7, 'Reddit returned nothing here.', 'Try another target, order or period.')
    if result['state'] is not None:
        reading['continuation'] = {'command': command, 'target': target, 'identity': identity,
                                   'words': _words(identity, words),
                                   'state': {**result['state'], 'window': window.state(), **(extra or {})}}
    return reading


def _words(identity, positional=None):
    words = list(positional or [])
    for key in ('type', 'sort', 'time', 'since', 'until'):
        if identity.get(key):
            words += ['--' + key, identity[key]]
    return words
