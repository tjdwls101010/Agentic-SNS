"""The text page's frame, the same for every platform: a header naming scope and cost, the window, the platform's
record lines, coverage, an incomplete-read line, more:. The records themselves are drawn by the platform."""
from sns.clock import local
from sns.text import line


def _limits(envelope):
    parts = []
    stopped = envelope.get('limit')
    if stopped:
        scope = stopped.get('scope') or 'account'
        parts.append(f'limit {line(scope)} resets {local(stopped.get("reset"))} · next '
                     f'{local(stopped.get("next_allowed_at"))}')
    for scope, state in (envelope.get('limits') or {}).items():
        if stopped and stopped.get('scope') == scope:
            continue
        if state.get('status') == 'known':
            remaining = state.get('remaining')
            shown = int(remaining) if isinstance(remaining, float) and remaining.is_integer() else remaining
            total = state.get('limit')
            total = int(total) if isinstance(total, float) and total.is_integer() else total
            parts.append(f'limit {line(scope)} {shown}/{total} resets {local(state.get("reset_at"), seconds=False)}')
        elif state.get('status') == 'unknown':
            parts.append(f'{line(scope)} window not reported')
    return parts


def header(envelope, shown):
    parts = [f'{envelope.get("platform", "")} {envelope.get("command", "")}'.strip()]
    parts += [f'{key}={line(value)}' for key, value in (envelope.get('query') or {}).items() if value is not None]
    if shown is not None:
        parts.append(f'{shown} shown')
    setup = envelope.get('setup_requests') or 0
    parts += [f'stopped={line(envelope.get("stop_reason"))}', f'requests={envelope.get("request_count", 0) - setup}']
    if setup:
        parts.append(f'tab opened (+{setup} requests)')
    if envelope.get('unwatched_requests'):
        parts.append(f'unwatched={envelope["unwatched_requests"]}')
    return parts + _limits(envelope)


def _window(window):
    return f'window {window.get("since") or ""}..{window.get("until") or ""} {window.get("tz") or ""} · ' \
           f'{line(window["coverage"])}'


def page(envelope, records, shown=None):
    """The text page of one result; `records` are the platform's lines for its records (and any preamble lines it
    puts before them), `shown` the number of records they draw."""
    if shown is None:
        shown = len(envelope.get('results') or [])
    lines = [' · '.join(header(envelope, shown))]
    if envelope.get('window'):
        lines.append(_window(envelope['window']))
    lines += records
    lines += ['coverage: ' + line(note) for note in envelope.get('coverage') or []]
    if envelope.get('error'):
        lines.append(f'coverage: incomplete — {line(envelope.get("message"))} fix: {line(envelope.get("fix"))}')
    if envelope.get('next'):
        lines.append('more: ' + envelope['next'])
    return '\n'.join(lines)


def summary(envelope):
    """The one line --out prints."""
    parts = header(envelope, None)
    parts.insert(1, f'{envelope.get("count", 0)} saved to "{envelope.get("out")}"')
    if envelope.get('already_complete'):
        parts.append('already complete')
    if envelope.get('window'):
        parts.append(_window(envelope['window']))
    if envelope.get('coverage'):
        parts.append('coverage: ' + '; '.join(line(c) for c in envelope['coverage']))
    if envelope.get('next'):
        parts.append('resume: ' + envelope['next'])
    if envelope.get('error'):
        parts.append(f'error={envelope["error"]} fix={line(envelope.get("fix"))}')
    return ' · '.join(parts)
