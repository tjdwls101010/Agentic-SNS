"""Shared wiring of the reading commands: a guarded connection, handles, --out files, and the finished result."""
from facebook import guard as protection
from facebook import handles
from facebook.aside import Aside
from facebook.collection import OutFile, peek
from facebook.errors import FacebookError
from facebook.graphql import Client
from facebook.results import finish
from facebook.session import Session


class Connection:
    """One invocation's guarded connection: the client, its guard, and the Facebook account in use.

    Built first and started second, so the requests a failed start already made are still reported.
    """

    def __init__(self, budget, verbose=False):
        self.guard = protection.Guard(budget)
        browser = Aside()
        self.memory = Session(browser.account_key)
        self.client = Client(browser, self.guard, self.memory, verbose)
        self.account_id = None

    def start(self):
        self.guard.check()  # a saved block stops the invocation before the browser is touched
        self.account_id = self.client.start()
        return self


def run(options, *, command, target, identity, reader, window=None):
    """Run one reading command and finish it into (kind, envelope).

    reader(connection, state, out) returns a reading (see results.finish) and may set 'continuation' to
    {command, target, identity, words, state}: what a later invocation needs to go on from here.
    """
    connection, reading = None, None
    out_path = options.get('out')
    try:
        if out_path:
            reading = _settled_file(out_path, _context(command, target, identity, None))
        if reading is None:
            connection = Connection(options['max_requests'], options.get('verbose'))
            connection.start()
            reading = _read(connection, options, command, target, identity, reader, out_path)
    except FacebookError as error:
        reading = {**(reading or {}), 'failure': error}
        reading.setdefault('results', [])
    if window:
        reading['window'] = window
    return finish(reading, command=command, requests=connection.guard.count if connection else 0,
                  budget=options['max_requests'], identity=_public(identity), out=out_path,
                  setup=connection.guard.setup if connection else 0)


def _settled_file(path, context):
    """Decide a --out file from the file alone, before the browser: a foreign or older file is refused, a complete one
    reads nothing. Returns the reading of a complete file, else None (read on)."""
    saved, complete, count = peek(path)
    if saved is None:
        return None
    if {k: v for k, v in saved.items() if k != 'account_id'} != {k: v for k, v in context.items() if k != 'account_id'}:
        raise FacebookError(2, 'The --out file belongs to another command, target, order or account.',
                            'Use a new --out path, or rerun the command that started this file.')
    if complete:
        return {'results': [], 'stop_reason': 'exhausted', 'already_complete': True, 'count': count}
    return None


def _read(connection, options, command, target, identity, reader, out_path):
    context = _context(command, target, identity, connection.account_id)
    state = handles.load(options['after'], context) if options.get('after') else None
    out = OutFile(out_path, context) if out_path else None
    reading = None
    try:
        if out is not None and out.complete:
            reading = {'results': [], 'stop_reason': 'exhausted', 'already_complete': True}
        else:
            reading = reader(connection, state, out)
        if out is not None:
            reading['count'] = out.count
            reading['continuable'] = out.state is not None and not out.complete
            failure = reading.get('failure')
            stopped = isinstance(failure, FacebookError) and failure.code in (4, 5)
            if not stopped and (reading.get('stop_reason') == 'budget' or isinstance(failure, FacebookError)):
                reading['next'] = words(command, target, reading.get('words', []), options, out=out_path)
    finally:
        if out is not None:
            out.close()
    _continue(reading, options, connection.account_id)
    if reading.pop('detail', None):
        reading['detail'] = words(command, target, reading.get('words', []), options, after=options.get('after'),
                                  chars=0)
    return reading


def _continue(reading, options, account_id):
    continuation = reading.pop('continuation', None)
    failure = reading.get('failure')
    if not continuation or options.get('out') or (isinstance(failure, FacebookError) and failure.code in (4, 5)):
        return  # after a block or a logout, a continuation would only invite another request
    context = _context(continuation['command'], continuation['target'], continuation['identity'], account_id)
    try:
        number = handles.save(context, continuation['state'])
    except FacebookError as error:
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
    if options.get('max_requests') not in (None, 25):
        result += ['--max-requests', str(options['max_requests'])]
    return result + tail


def _context(command, target, identity, account_id):
    return {'command': command, 'target': target, **identity, 'account_id': account_id}


def _public(identity):
    """The identity options a result names in its header (sort, type)."""
    return {key: value for key, value in identity.items() if key in ('sort', 'type') and value is not None}
