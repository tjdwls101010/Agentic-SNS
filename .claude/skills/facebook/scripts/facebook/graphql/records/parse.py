"""Decode GraphQL NDJSON and merge story fragments by feedback id.

Path-only patches cannot be applied safely without validated capture paths;
ParsedStories.incomplete exposes that loss rather than claiming full data.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any

# --- bytes -> JSON objects ----------------------------------------------------


def iter_json_objects(bodies: Iterable[bytes], *, issues: list[str] | None = None) -> Iterator[dict]:
    """Decode captured response bodies and yield each NDJSON line's parsed object.

    ``Response.body`` is raw bytes (scrapling, verified against 0.4.10 source) —
    decoding must happen here, explicitly, before any string operation.
    Unparseable lines are skipped rather than raising: a single malformed line
    (e.g. a truncated stream) must not lose every other post in the batch.
    """
    for body in bodies:
        text = body.decode("utf-8", errors="replace")
        if "\ufffd" in text and issues is not None:
            issues.append("invalid_utf8")
        if text.startswith("for (;;);"):
            text = text[len("for (;;);"): ]
        for line in text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                if issues is not None:
                    issues.append("malformed_json")
                continue
            if isinstance(obj, dict):
                yield obj
            elif issues is not None:
                issues.append("non_object_json")


# --- deep merge ----------------------------------------------------------------


def deep_merge(a: dict, b: dict) -> dict:
    """Merge ``b`` into ``a``: non-null wins, dicts recurse, id-keyed lists union.

    ``@defer`` ships a story in pieces across multiple lines/bodies (plan
    §8 G-ndjson-defer) — picking "the more complete" instance silently drops
    whichever fields only live in the other one.
    """
    result = dict(a)
    for key, b_val in b.items():
        if b_val is None:
            continue
        a_val = result.get(key)
        if a_val is None:
            result[key] = b_val
        elif isinstance(a_val, dict) and isinstance(b_val, dict):
            result[key] = deep_merge(a_val, b_val)
        elif isinstance(a_val, list) and isinstance(b_val, list):
            result[key] = _merge_lists(a_val, b_val)
        # else: both non-null scalars that disagree — keep the first seen.
    return result


def _merge_lists(a: list, b: list) -> list:
    if a and isinstance(a[0], dict) and "id" in a[0]:
        by_id: dict[Any, dict] = {}
        order: list[Any] = []
        for item in a:
            if isinstance(item, dict) and "id" in item:
                by_id[item["id"]] = item
                order.append(item["id"])
        for item in b:
            if isinstance(item, dict) and "id" in item:
                item_id = item["id"]
                if item_id in by_id:
                    by_id[item_id] = deep_merge(by_id[item_id], item)
                else:
                    by_id[item_id] = item
                    order.append(item_id)
        return [by_id[i] for i in order]
    # No id key to union by (e.g. an "attachments" list) — picking one list
    # wholesale (the old "longer wins" rule) silently drops a genuinely new
    # item the OTHER list has whenever it isn't the longer one. Concatenate
    # and dedupe by content instead, so a distinct item from either side
    # always survives.
    combined: list = []
    seen_keys: set[str] = set()
    for item in (*a, *b):
        try:
            key = json.dumps(item, sort_keys=True, default=str)
        except TypeError:
            key = repr(item)
        if key not in seen_keys:
            seen_keys.add(key)
            combined.append(item)
    return combined


# --- story-node discovery -------------------------------------------------------


def _is_story_shaped(obj: Any) -> bool:
    return (
        isinstance(obj, dict)
        and isinstance(obj.get("feedback"), dict)
        and obj["feedback"].get("id") is not None
    )


# 성진: Path-only patches remain unsupported; apply them after capture validation.

#: Confirmed via live capture (2026-07): a post's inline "top comment"
#: preview is a SEPARATE feedback-shaped object nested under this key
#: (path seen: comet_sections.feedback.story.story_ufi_container.story.
#: feedback_context.interesting_top_level_comments[].comment) — reached
#: without ever passing through attached_story, so it would otherwise be
#: misidentified as an independent top-level post. It is a comment, not a
#: post or a share: skipped entirely, never merged, never top-level.
_NON_POST_CONTAINER_KEYS = frozenset({"interesting_top_level_comments"})


def _walk(
    obj: Any, stories: dict[str, dict], top_level_seen: dict[str, None], *, is_nested_share: bool
) -> None:
    if isinstance(obj, dict):
        if obj.get("__typename") == "Comment" or ("depth" in obj and "author" in obj):
            return
        if _is_story_shaped(obj):
            story_id = str(obj["feedback"]["id"])
            if not is_nested_share:
                # A story earns top-level status if EVER encountered outside
                # someone else's attached_story, even if it's ALSO nested
                # under a share elsewhere in the same capture (a friend can
                # reshare a post that's also, independently, in your own
                # feed) — tracking this positively, rather than recording
                # "seen as a child" and excluding by that, means a later or
                # earlier top-level sighting can't be permanently discarded.
                top_level_seen.setdefault(story_id, None)
            stories[story_id] = (
                deep_merge(stories[story_id], obj) if story_id in stories else dict(obj)
            )

        for key, value in obj.items():
            if key in _NON_POST_CONTAINER_KEYS:
                continue
            _walk(value, stories, top_level_seen,
                  is_nested_share=is_nested_share or key == "attached_story")
    elif isinstance(obj, list):
        for item in obj:
            _walk(item, stories, top_level_seen, is_nested_share=is_nested_share)


@dataclass
class ParsedStories:
    stories: dict[str, dict]  # feedback.id -> deep-merged raw story dict
    top_level_seen: set[str]  # ids ever encountered outside someone else's attached_story

    incomplete: bool = False
    incomplete_reasons: list[str] = field(default_factory=list)

    top_level_order: list[str] = field(default_factory=list)

    def top_level_ids(self) -> list[str]:
        """IDs of stories ever seen outside someone else's ``attached_story``."""
        return self.top_level_order.copy() if self.top_level_order else [
            story_id for story_id in self.stories if story_id in self.top_level_seen]


def parse_story_nodes(bodies: Iterable[bytes]) -> ParsedStories:
    """Return every distinct, fully deep-merged story found across ``bodies``.

    Keyed by ``feedback.id``. Includes BOTH top-level posts and shared/quoted
    posts nested under someone's ``attached_story`` — use
    :meth:`ParsedStories.top_level_ids` to tell them apart. Merging everything
    first (before filtering) means a shared post whose own fields arrive split
    across ``@defer`` chunks is still merged correctly.
    """
    stories: dict[str, dict] = {}
    top_level_seen: dict[str, None] = {}
    issues: list[str] = []
    for obj in iter_json_objects(bodies, issues=issues):
        for chunk in [obj, *(obj.get("incremental") or [])]:
            if not isinstance(chunk, dict):
                continue
            if "path" in chunk:
                data = chunk.get("data")
                if not _is_story_shaped(data) and not (
                    isinstance(data, dict) and _is_story_shaped(data.get("node"))
                ):
                    issues.append("unsupported_path_patch")
            if chunk.get("errors"):
                issues.append("graphql_errors")
            _walk({k: v for k, v in chunk.items() if k != "incremental"},
                  stories, top_level_seen,
                  is_nested_share="attached_story" in (chunk.get("path") or []))
    def linked(story: dict, ancestors: frozenset[str]) -> dict:
        result = dict(story)
        attached = find_attached_story(story)
        if _is_story_shaped(attached):
            child_id = str(attached["feedback"]["id"])
            if child_id in ancestors:
                result.pop("attached_story", None)
                issues.append("cyclic_shared_story")
            else:
                result["attached_story"] = linked(stories.get(child_id, attached), ancestors | {child_id})
        return result

    stories = {key: linked(story, frozenset({key})) for key, story in stories.items()}
    if issues:
        for story in stories.values():
            for node in iter_story_dicts(story):
                if _is_story_shaped(node):
                    node["incomplete"] = True
    return ParsedStories(stories, set(top_level_seen), bool(issues),
                         list(dict.fromkeys(issues)), list(top_level_seen))


# --- field extraction (best-effort — see module docstring) ---------------------


def iter_story_dicts(obj: Any, *, exclude_keys: frozenset[str] = frozenset(),
                     exclude_links: bool = False) -> Iterator[dict]:
    """DFS excluding named containers and, optionally, whole link attachment subtrees."""
    if isinstance(obj, dict):
        if (exclude_links and isinstance(obj.get("url"), str) and "uri" not in obj
                and ("title" in obj or "description" in obj)):
            return
        yield obj
        for key, value in obj.items():
            if key in exclude_keys:
                continue
            yield from iter_story_dicts(value, exclude_keys=exclude_keys, exclude_links=exclude_links)
    elif isinstance(obj, list):
        for item in obj:
            yield from iter_story_dicts(item, exclude_keys=exclude_keys, exclude_links=exclude_links)


SHARE_EXCLUDE = frozenset({"attached_story", *_NON_POST_CONTAINER_KEYS})


def find_attached_story(story: dict) -> dict | None:
    """Find the own attached story, including identity-free content wrappers."""
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        if isinstance(node.get("attached_story"), dict):
            return node["attached_story"]
    return None


def find_creation_time(story: dict) -> int | None:
    """The story's own ``creation_time`` — a direct key on the story root only.

    Deliberately NOT a recursive search: the plan's decoy-int fixture exists
    precisely because "any int in the tree" grabs the wrong value (an edit
    time, a nested attachment's timestamp, a cache-busting int). Restricting
    to a direct key on the merged story dict is the exact-path discipline
    plan §8 asks for. Confirmed via live capture: this is exactly where it
    lives on a real post.
    """
    value = story.get("creation_time")
    return value if isinstance(value, int) else None


def find_permalink(story: dict) -> str | None:
    """The story's permalink. Confirmed via live capture: ``permalink_url`` is
    a direct root key (as reliable a lookup as ``creation_time``); ``wwwURL``
    is the same URL repeated deeper in ``comet_sections``, kept as a fallback.
    """
    value = story.get("permalink_url")
    if isinstance(value, str):
        return value
    value = story.get("wwwURL")
    if isinstance(value, str):
        return value
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        if node is story:
            continue
        value = node.get("wwwURL")
        if isinstance(value, str):
            return value
    return None


def find_message_text(story: dict) -> str | None:
    """First non-empty ``message.text`` reachable from the story root (own text only)."""
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        message = node.get("message")
        if isinstance(message, dict):
            text = message.get("text")
            if isinstance(text, str) and text:
                return text
    return None


def find_actors(story: dict) -> list[dict]:
    """Actor dicts (name/url/id) — prefers a key literally named ``actors``."""
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        actors = node.get("actors")
        if isinstance(actors, list) and actors and all(isinstance(a, dict) for a in actors):
            return actors
    return []


def find_media(story: dict, *, exclude_link_thumbnails: bool = False) -> list[dict]:
    """Media-shaped dicts: anything with an ``image``/``uri`` pair or a playable video URL.

    A video attachment carries BOTH an ``image`` (its poster thumbnail) and a
    ``playable_url`` (the actual video) as siblings — the thumbnail's own kind
    is still "image" regardless of that sibling; only the ``playable_url``
    entry is "video".
    """
    media: list[dict] = []
    seen_urls: set[str] = set()
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE, exclude_links=exclude_link_thumbnails):
        image = node.get("image")
        if isinstance(image, dict) and isinstance(image.get("uri"), str):
            url = image["uri"]
            if url not in seen_urls:
                seen_urls.add(url)
                media.append(
                    {
                        "kind": "image",
                        "url": url,
                        "width": image.get("width"),
                        "height": image.get("height"),
                    }
                )
        playable = node.get("playable_url") or node.get("playable_url_quality_hd")
        if isinstance(playable, str) and playable not in seen_urls:
            seen_urls.add(playable)
            media.append({"kind": "video", "url": playable, "width": None, "height": None})
    return media


def find_links(story: dict) -> list[dict]:
    """External link-share attachments: a dict carrying ``url`` + (``title`` or ``description``)."""
    links: list[dict] = []
    seen_urls: set[str] = set()
    for node in iter_story_dicts(story, exclude_keys=SHARE_EXCLUDE):
        url = node.get("url")
        if (
            isinstance(url, str)
            and url not in seen_urls
            and ("title" in node or "description" in node)
            and "uri" not in node  # exclude media dicts, which use "uri" not "url"
        ):
            seen_urls.add(url)
            links.append(
                {
                    "url": url,
                    "title": node.get("title") if isinstance(node.get("title"), str) else None,
                    "description": node.get("description")
                    if isinstance(node.get("description"), str)
                    else None,
                }
            )
    return links
