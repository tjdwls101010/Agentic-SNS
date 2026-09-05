"""One bounded Aside process, one response envelope, no raw diagnostics."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from _errors import FacebookError

SNIPPETS = Path(__file__).resolve().parent / 'browser'


def run_snippet(name, args):
    if not isinstance(name, str) or Path(name).name != name:
        raise FacebookError(3, 'Invalid browser snippet.', 'Reinstall the Facebook skill.')
    name = name if name.endswith('.js') else name + '.js'
    try:
        source = (SNIPPETS / name).read_text(encoding='utf-8')
        if not source.strip():
            raise ValueError
        code = 'const ARGS = ' + json.dumps(args, ensure_ascii=True) + ';\n' + source
    except (OSError, ValueError, TypeError):
        raise FacebookError(3, 'Browser snippet is missing or invalid.', 'Reinstall the Facebook skill.') from None
    binary = os.environ.get('FACEBOOK_ASIDE_BIN') or shutil.which('aside')
    if not binary:
        raise FacebookError(3, 'Aside is unavailable.', 'Start Aside and make its CLI available on PATH.')
    try:
        result = subprocess.run([binary, '--account', 'u0', 'repl', code], capture_output=True, text=True, timeout=125)
    except subprocess.TimeoutExpired:
        raise FacebookError(3, 'Aside request exceeded its 120-second time limit.', 'Reduce the request size.') from None
    except (OSError, UnicodeError):
        raise FacebookError(3, 'Aside could not run.', 'Start Aside, then run doctor.') from None
    if result.returncode:
        timed_out = any(s in (result.stderr + result.stdout).lower()
                        for s in ('other side closed', 'daemon is not reachable'))
        message = 'Aside request ended at the REPL time limit or lost its connection.' if timed_out else 'Aside request failed.'
        raise FacebookError(3, message, 'Check Aside, then run doctor.')
    try:
        lines = [re.sub(r'\x1b\[[0-9;]*m', '', line).strip() for line in result.stdout.splitlines()]
        records = [json.loads(line) for line in lines if line.startswith('{')]
        if not records:
            raise ValueError
        envelope = records[-1]
        if not isinstance(envelope, dict) or 'body_file' in envelope:
            raise ValueError
        if 'body_chunks' in envelope:
            if type(envelope['body_chunks']) is not int or envelope.pop('body_chunks') != len(records) - 1:
                raise ValueError
            parts = []
            for index, record in enumerate(records[:-1]):
                if (not isinstance(record, dict) or record.get('kind') != 'body_chunk'
                        or record.get('index') != index or not isinstance(record.get('body'), str)):
                    raise ValueError
                parts.append(record['body'])
            envelope['body'] = ''.join(parts)
        elif len(records) != 1:
            raise ValueError
        if (not isinstance(envelope, dict) or type(envelope.get('status')) is not int
                or not 100 <= envelope['status'] <= 599 or not isinstance(envelope.get('url'), str)
                or not isinstance(envelope.get('body'), str)):
            raise ValueError
        return envelope
    except (ValueError, TypeError, OSError, UnicodeError):
        raise FacebookError(3, 'Aside returned an invalid response envelope.', 'Run doctor to check the browser bridge.') from None
