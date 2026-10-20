"""X's record lines: the dense text of a post, an account, a trend, a list, a community, a space or a notification. The
page frame (header, window, coverage, more:) is the core's; all clipping and labels live here, the records themselves
are never shortened."""
from sns.text import clip, count as _count, limit_of, line as _line, quote as _quote, shown as _shown, time as _time


def _handle(value):
    return _quote(value) if value else 'unavailable'


def _text(record, chars, field='text'):
    """text[N of M chars shown]: "…" """
    return _shown(record.get(field), chars, field)


def _clip(text, chars):
    return clip(text, chars)


def _who(account):
    if not account:
        return 'unavailable'
    if account.get('unavailable'):
        return 'unavailable account'
    parts = ['@' + _line(account.get('username') or '?')]
    if account.get('full_name'):
        parts[0] += f' ({_line(account["full_name"])})'
    if account.get('verified_type'):
        parts.append(f'{account["verified_type"].lower()} badge')
    elif account.get('is_blue_verified'):
        parts.append('paid check')
    if account.get('declared_label'):
        parts.append(f'{account["declared_label"].lower()} account')
    if account.get('private'):
        parts.append('protected')
    return ' · '.join(parts)


def _media(record):
    parts = []
    for item in record.get('media') or []:
        part = item.get('kind', 'photo')
        if item.get('alt'):
            part += ' alt=' + _quote(item['alt'])
        parts.append(part)
    return ' · '.join(parts)


def _counts(record):
    return (f'likes={_count(record.get("like_count"))} replies={_count(record.get("reply_count"))} '
            f'reposts={_count(record.get("repost_count"))} quotes={_count(record.get("quote_count"))} '
            f'views={_count(record.get("view_count"))}')


def _nested(label, record, chars, indent):
    if record.get('unavailable'):
        ident = f' (post {record["id"]})' if record.get('id') else ''
        return f'{indent}     {label}: unavailable{ident} — {_line(record.get("unavailable_reason") or "")}'
    return (f'{indent}     {label}: {_who(record.get("author"))} · {_time(record.get("created_at"))} · '
            f'{_text(record, chars)} · url: {_handle(record.get("url"))}')


def _extras(record, chars, indent):
    lines = []
    if record.get('media'):
        lines.append(f'{indent}     media: ' + _media(record))
    note = record.get('community_note')
    if note:
        lines.append(f'{indent}     community note (other users\' context, not the author\'s words): '
                     f'{_quote(_clip(note.get("text"), chars)[0])} · {_line(note.get("url") or "")}')
    card = record.get('card')
    if card:
        if card.get('poll'):
            poll = card['poll']
            choices = ' · '.join(f'{_line(c["label"])} {_count(c.get("count"))}' for c in poll.get('choices') or [])
            state = 'final' if poll.get('final') else f'open until {_time(poll.get("ends_at"))}'
            lines.append(f'{indent}     poll ({state}): {choices}')
        elif card.get('space_url'):
            lines.append(f'{indent}     space: {card["space_url"]}')
        elif card.get('title') or card.get('url'):
            lines.append(f'{indent}     link: {_quote(card.get("title") or "")} ({_line(card.get("url") or "")})')
    article = record.get('article')
    if article:
        body = article.get('text') or article.get('preview') or ''
        field = 'article text' if article.get('text') else 'article preview'
        shown, n, m = _clip(body, chars)
        lines.append(f'{indent}     article {_quote(article.get("title") or "")}: {field}[{n} of {m} chars shown]: '
                     f'{_quote(shown)}')
    edit = record.get('edit')
    if edit:
        versions = edit.get('versions') or []
        place = versions.index(record['id']) + 1 if record.get('id') in versions else '?'
        lines.append(f'{indent}     edited: version {place} of {len(versions)}'
                     + ('' if edit.get('latest') else ' (not the latest)') + ' · versions: ' + ', '.join(versions))
    return lines


def post(record, label, labels, chars):
    """One post, reply or parent; `labels` maps ids already shown on this page to their labels."""
    indent = '  ' * min(max(record.get('depth') or 0, 0), 10)
    if record.get('unavailable'):
        return f'{indent}[{label}] unavailable — {_line(record.get("unavailable_reason") or "")}'
    original = record.get('reposted_post')
    if original:
        lines = [f'{indent}[{label}] {_who(record.get("author"))} reposted · {_time(record.get("created_at"))}'
                 + (' · pinned' if record.get('pinned') else '')]
        if original.get('unavailable'):
            lines.append(f'{indent}     repost of: unavailable — {_line(original.get("unavailable_reason") or "")}')
        else:
            lines.append(f'{indent}     repost of: {_who(original.get("author"))} · {_time(original.get("created_at"))} '
                         f'· {_counts(original)}')
            lines.append(f'{indent}     {_text(original, chars)}')
            if original.get('quoted_post'):
                lines.append(_nested('quoting', original['quoted_post'], chars, indent))
            lines += _extras(original, chars, indent)
        lines.append(f'{indent}     url: {_handle(original.get("url") or record.get("url"))}   author: '
                     f'{_handle((original.get("author") or {}).get("username"))}   reposter: '
                     f'{_handle((record.get("author") or {}).get("username"))}')
        return '\n'.join(lines)
    flags = [_who(record.get('author')), _time(record.get('created_at')), _counts(record)]
    if record.get('role') == 'parent':
        flags.append('parent')
    if record.get('role') == 'reply' and record.get('depth'):
        target = labels.get(record.get('parent_id'))
        flags.append(f'reply-to={target}' if target else 'reply to a post not shown')
    elif record.get('is_reply') and record.get('role') not in ('reply',):
        flags.append('a reply')
    if record.get('pinned'):
        flags.append('pinned')
    lines = [f'{indent}[{label}] ' + ' · '.join(flags), f'{indent}     {_text(record, chars)}']
    if record.get('quoted_post'):
        lines.append(_nested('quoting', record['quoted_post'], chars, indent))
    elif record.get('quoted_post_id'):
        lines.append(f'{indent}     quoting: a post X did not include (post {record["quoted_post_id"]})')
    lines += _extras(record, chars, indent)
    tail = f'{indent}     url: {_handle(record.get("url"))}   author: {_handle((record.get("author") or {}).get("username"))}'
    if record.get('replies_handle'):
        tail += f'   replies {record["replies_handle"]}'
    lines.append(tail)
    return '\n'.join(lines)


def account(record, label):
    if record.get('unavailable'):
        return f'[{label}] unavailable account — {_line(record.get("unavailable_reason") or "")}'
    parts = [_who(record),
             f'followers={_count(record.get("follower_count"))} following={_count(record.get("following_count"))} '
             f'posts={_count(record.get("post_count"))}']
    relation = record.get('relationship') or {}
    if relation.get('following') and relation.get('followed_by'):
        parts.append('you follow each other')
    elif relation.get('following'):
        parts.append('you follow')
    elif relation.get('followed_by'):
        parts.append('follows you')
    lines = [f'[{label}] ' + ' · '.join(parts)]
    if record.get('bio'):
        lines.append('     bio: ' + _quote(record['bio']))
    details = [f'{key}={_line(record[key])}' for key in ('location', 'website') if record.get(key)]
    if record.get('created_at'):
        details.append('joined=' + _time(record['created_at'])[:10])
    if record.get('affiliation') and record['affiliation'].get('label'):
        details.append('affiliation=' + _line(record['affiliation']['label']))
    if details:
        lines.append('     ' + ' · '.join(details))
    lines.append(f'     url: {_handle(record.get("url"))}   author: {_handle(record.get("username"))}')
    return '\n'.join(lines)


def trend(record, label):
    parts = [_quote(record.get('name') or ''), record.get('kind') or 'trend']
    parts += [_line(record[key]) for key in ('context', 'description') if record.get(key)]
    if record.get('rank') is not None:
        parts.insert(2, f'#{record["rank"]}')
    line = f'[{label}] ' + ' · '.join(parts)
    if record.get('query'):
        line += '\n     search: ' + _quote(record['query'])
    elif record.get('url'):
        line += '\n     url: ' + _handle(record['url'])
    return line


def x_list(record, label):
    owner = (record.get('owner') or {}).get('username')
    parts = [_quote(record.get('name') or '') + (f' by @{owner}' if owner else '')]
    if record.get('private') is not None:
        parts.append('private' if record['private'] else 'public')
    parts.append(f'members={_count(record.get("member_count"))} followers={_count(record.get("follower_count"))}')
    parts += [text for key, text in (('you_follow', 'you follow it'), ('you_are_member', 'you are a member'))
              if record.get(key)]
    lines = [f'[{label}] ' + ' · '.join(parts)]
    if record.get('description'):
        lines.append('     about: ' + _quote(record['description']))
    if record.get('created_at'):
        lines.append('     created=' + _time(record['created_at'])[:10])
    lines.append(f'     url: {_handle(record.get("url"))}')
    return '\n'.join(lines)


def community(record, label):
    parts = [_quote(record.get('name') or ''),
             f'members={_count(record.get("member_count"))} moderators={_count(record.get("moderator_count"))}']
    if record.get('open_to_join') is not None:
        parts.append('open to join' if record['open_to_join'] else 'joining needs approval')
    parts += [_line(record['topic']).lower()] if record.get('topic') else []
    parts += ['nsfw'] if record.get('nsfw') else []
    if record.get('your_role'):
        parts.append('you are not a member' if record['your_role'] == 'not a member' else
                     f'you are {"an" if record["your_role"][0] in "aeiou" else "a"} {_line(record["your_role"])}')
    lines = [f'[{label}] ' + ' · '.join(parts)]
    if record.get('description'):
        lines.append('     about: ' + _quote(record['description']))
    if record.get('rules'):
        lines.append('     rules: ' + ' · '.join(_quote(rule) for rule in record['rules']))
    made = [f'created by @{record["creator"]["username"]}'] if (record.get('creator') or {}).get('username') else []
    made += ['created=' + _time(record['created_at'])[:10]] if record.get('created_at') else []
    if made:
        lines.append('     ' + ' · '.join(made))
    lines.append(f'     url: {_handle(record.get("url"))}')
    return '\n'.join(lines)


def space(record, label):
    parts = [_quote(record.get('title') or ''), _line(record.get('state') or 'state unknown')]
    if (record.get('host') or {}).get('username'):
        parts.append(f'hosted by @{record["host"]["username"]}')
    parts += [f'listeners={_count(record.get("live_listener_count"))}',
              f'participants={_count(record.get("participant_count"))}']
    lines = [f'[{label}] ' + ' · '.join(parts)]
    if record.get('speakers'):
        lines.append('     speakers: ' + ' '.join('@' + name for name in record['speakers']))
    when = [f'{key}={_time(record[field])}' for key, field in (('scheduled', 'scheduled_start'), ('started', 'started_at'),
                                                               ('ended', 'ended_at')) if record.get(field)]
    if record.get('replay_available') is not None:
        when.append('replay available' if record['replay_available'] else 'no replay')
    if when:
        lines.append('     ' + ' · '.join(when))
    lines.append(f'     url: {_handle(record.get("url"))}')
    return '\n'.join(lines)


def notification(record, label):
    lines = [f'[{label}] {_line(record.get("event") or "notification")} · {_time(record.get("created_at"))}']
    if record.get('message'):
        lines.append('     ' + _quote(record['message']))
    details = []
    if record.get('accounts'):
        details.append('accounts: ' + ' '.join('@' + name for name in record['accounts']))
    if record.get('post_ids'):
        details.append('posts: ' + ' '.join(record['post_ids']))
    if details:
        lines.append('     ' + '   '.join(details))
    if record.get('url'):
        lines.append(f'     url: {_handle(record["url"])}')
    return '\n'.join(lines)


def _replies_line(replies):
    reported = '?' if replies.get('reported') is None else replies['reported']
    return (f'replies: {replies.get("direct_shown", 0)} direct and {replies.get("nested_shown", 0)} nested shown of '
            f'{reported} X reports · {replies.get("branches", 0)} collapsed branches · {replies.get("hidden", 0)} '
            f'hidden by X · {replies.get("unavailable", 0)} unavailable')


def render(envelope, chars, command):
    """The record lines of a text page (a post read's replies line first). chars None: the default; 0: everything
    received."""
    limit = limit_of(chars)
    lines = [_replies_line(envelope['replies'])] if envelope.get('replies') else []
    labels, counts = {}, {'p': 0, 'r': 0, 'a': 0, 't': 0, 'l': 0, 'c': 0, 's': 0, 'n': 0}
    for record in envelope.get('results') or []:
        kind = record.get('kind')
        if kind == 'notification':
            counts['n'] += 1
            lines.append(notification(record, f'n{counts["n"]}'))
            continue
        if kind == 'space':
            counts['s'] += 1
            lines.append(space(record, f's{counts["s"]}'))
            continue
        if kind == 'community':
            counts['c'] += 1
            lines.append(community(record, f'c{counts["c"]}'))
            continue
        if kind == 'list':
            counts['l'] += 1
            lines.append(x_list(record, f'l{counts["l"]}'))
            continue
        if kind == 'account':
            counts['a'] += 1
            lines.append(account(record, f'a{counts["a"]}'))
            continue
        if kind in ('trend', 'event'):
            counts['t'] += 1
            lines.append(trend(record, f't{counts["t"]}'))
            continue
        prefix = 'r' if record.get('role') == 'reply' else 'p'
        counts[prefix] += 1
        label = f'{prefix}{counts[prefix]}'
        whole = command == 'post' and record.get('role') == 'post'
        lines.append(post(record, label, labels, None if whole else limit))
        if record.get('id'):
            labels[record['id']] = label
    return lines
