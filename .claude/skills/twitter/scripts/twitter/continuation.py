"""Numbered private continuation handles bound to their query and viewer."""
import json
import os
from .account.state import cache_dir
from .errors import TwitterError


class CursorStore:
    def __init__(self):
        self.directory = cache_dir() / 'cursors'

    def save(self, context, state):
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        number = 1
        while True:
            try:
                fd = os.open(self.directory / f'{number}.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                break
            except FileExistsError:
                number += 1
        with os.fdopen(fd, 'wb') as stream:
            stream.write((json.dumps(dict(state, context=context), ensure_ascii=False) + '\n').encode())
            stream.flush()
            os.fsync(stream.fileno())
        return number

    def load(self, number, context):
        try:
            if not str(number).isdigit() or int(number) < 1:
                raise ValueError
            data = json.loads((self.directory / f'{int(number)}.json').read_text())
            if data.get('context') != context or not isinstance(data.get('pending'), list):
                raise ValueError
            return data
        except (OSError, ValueError, AttributeError):
            raise TwitterError(2, 'Continuation is missing or belongs to a different query/account.', 'Copy the complete more: command, or start a new query.') from None
