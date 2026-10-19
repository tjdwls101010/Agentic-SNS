"""A post page (TweetDetail): the asked post, its parents above it, and its replies in conversation modules.

Roles follow position and ids, never query names: the entry whose post id is the asked id is the post; on a first
page, posts before it outside any module are parents (top first); posts in conversationthread-* modules are replies.
A reply's depth is its place in its module (0: the module's first item, which answers the post), because X's modules
can skip posts: a later item may answer a post that is not on the page (parent_shown false). Other modules (related
posts, who to follow) are not the conversation and are counted, not shown.

Coverage: reported (the post's own reply count, first page only), direct_shown and nested_shown, branches (ShowMore
cursors inside modules: more of a collapsed branch), hidden (ShowMoreThreads* cursors outside modules: replies X hid
as low quality), unavailable (tombstones among the replies).
"""
from dataclasses import dataclass, field

from twitter.errors import TwitterError
from twitter.x_web.records.posts import post_record
from twitter.x_web.records.timeline import walk

CONVERSATION = 'conversationthread-'


@dataclass
class PostPage:
    records: list
    cursor: str | None                 # the next batch of direct replies (Bottom), None at the end
    coverage: dict
    branches: dict = field(default_factory=dict)   # reply id → ShowMore cursor of its collapsed branch
    hidden_cursor: str | None = None   # the cursor that reads the replies X hid
    other: int = 0
    unreadable: int = 0                # post entries this skill could not turn into a record


def _result(node):
    """An entry's tweet result; an empty tweet_results is how X sends a deleted post (an unavailable record)."""
    results = node.get('tweet_results') if isinstance(node.get('tweet_results'), dict) else {}
    return results.get('result') or {}


def post_page(instructions, post_id, continuing=False):
    page = walk(instructions)
    records, found, reported, other, unreadable = [], False, None, page.other, 0
    positions = {}   # module → posts seen in it so far
    for entry in page.entries:
        if entry.kind != 'post':
            continue
        conversation = bool(entry.module) and entry.module.startswith(CONVERSATION)
        if entry.module and not conversation:
            other += 1
            continue
        record = post_record(_result(entry.node), entry_id=entry.entry_id)
        if record is None:
            unreadable += 1
            continue
        if record.get('id') == post_id and not conversation:
            if record.get('unavailable'):
                raise TwitterError(9, 'This post is unavailable: deleted, withheld or not visible to this account.',
                                   'Tell the user; retrying will not change it.', reason='unavailable')
            record.update(role='post', depth=0)
            found, reported = True, record.get('reply_count')
        elif not conversation:
            record.update(role='parent' if not found and not continuing else 'reply', depth=0)
        else:
            depth = positions.get(entry.module, 0)
            positions[entry.module] = depth + 1
            record.update(role='reply', depth=depth, unit=entry.module)
        records.append(record)
    shown = {r.get('id') for r in records if r.get('id')} | {post_id}
    for record in records:
        if record['role'] == 'reply':
            record['parent_shown'] = record.get('reply_to_id') in shown
    branches = {}
    for branch in page.branches:
        in_module = [r for r in records if r.get('unit') == branch.module]
        if in_module:
            branches[in_module[-1]['id']] = branch.value
    replies = [r for r in records if r['role'] == 'reply']
    coverage = {'direct_shown': sum(1 for r in replies if r['depth'] == 0 and not r.get('unavailable')),
                'nested_shown': sum(1 for r in replies if r['depth'] > 0 and not r.get('unavailable')),
                'branches': len(page.branches), 'hidden': len(page.hidden),
                'unavailable': sum(1 for r in replies if r.get('unavailable'))}
    if found:
        coverage['reported'] = reported
    elif unreadable and not continuing:
        raise TwitterError(6, 'X\'s answer to TweetDetail is not where or what this skill expects.',
                           'X changed this read; the skill needs an update. Tell the user which read failed; other '
                           'commands may work.', reason='shape_changed')
    cursor = page.bottom if page.bottom and not page.terminated else None
    return PostPage(records=records, cursor=cursor, coverage=coverage, branches=branches,
                    hidden_cursor=page.hidden[0] if page.hidden else None, other=other, unreadable=unreadable)
