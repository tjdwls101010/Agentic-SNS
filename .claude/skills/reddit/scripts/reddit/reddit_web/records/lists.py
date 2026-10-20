"""A Listing page → records and where the next page starts."""
import re

from reddit.errors import RedditError
from reddit.reddit_web.records.comments import comment
from reddit.reddit_web.records.entities import community, user
from reddit.reddit_web.records.posts import post

_BUILDERS = {'t3': post, 't1': comment, 't5': community, 't2': user}


def _malformed(what):
    return RedditError(6, f'Reddit sent a listing this skill cannot read ({what}).', 'Retry once; if it persists, '
                                                                                    'report it (Reddit may have '
                                                                                    'changed its format).',
                       reason='shape_changed')


def page(listing):
    """(records, after): every child as a record in Reddit's order; after is the next page's fullname or None. An id
    that disagrees with its fullname or an after that is not a fullname is malformed."""
    data = listing['data']
    after = data.get('after')
    if after is not None and (not isinstance(after, str) or not re.fullmatch(r't[1235]_[a-z0-9]+', after)):
        raise _malformed('its next-page value')
    records = []
    for child in data['children']:
        kind, raw = child['kind'], child['data']
        if kind == 'more':
            continue
        if kind != 't2':
            name = raw.get('name', kind + '_' + str(raw.get('id', '')))
            if not isinstance(name, str) or not re.fullmatch(kind + r'_[a-z0-9]+', name) or \
                    (raw.get('id') is not None and raw['id'] != name[3:]):
                raise _malformed('an item\'s id')
        elif not isinstance(raw.get('id'), str) or not re.fullmatch(r'[a-z0-9]+', raw['id']):
            raise _malformed('an account\'s id')
        records.append(_BUILDERS[kind](raw))
    return records, after
