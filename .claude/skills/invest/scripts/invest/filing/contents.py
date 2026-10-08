"""The document's own linked contents, chosen only when the document leaves no doubt which links they are.

Internal links are grouped by where they sit: one table, or one block outside tables. A group is the contents when it reaches three or more distinct targets, its links follow the targets' document order at least 90% of the time, it sits before its first target, and it reaches more targets than any other group that does all of that. No form or ticker rule is used, so a document whose contents cannot be told apart from its other links gets none, and every group stays a candidate in the map.
"""
from urllib.parse import unquote, urlsplit

MIN_TARGETS = 3


def groups(document):
    """{group name: [(link, target key, target position)]} for every internal link whose target has a position, in link order."""
    found = {}
    for link in document.links:
        if link["kind"] != "internal" or "target_block" not in link:
            continue
        name = link.get("table_id") or f"block-{link['block']}"
        target = unquote(urlsplit(link["url"]).fragment)
        position = (link["target_block"], link.get("target_row", -1), link["target_offset"])
        found.setdefault(name, []).append((link, target, position))
    return found


def judge(name, pairs):
    targets = list(dict.fromkeys(target for _, target, _ in pairs))
    positions = [position for _, _, position in pairs]
    steps = list(zip(positions, positions[1:]))
    forward = sum(1 for a, b in steps if b >= a)
    # Every link of the group sits before the earliest target, in reading order (a footer declared first is read last): a group that straddles one of its targets is not a contents list.
    before = max((link["block"], link.get("row", -1), link.get("offset", 0)) for link, _, _ in pairs) < min(positions)
    return {"group": name, "block": pairs[0][0]["block"], "targets": len(targets), "ordered": round(forward / len(steps), 3) if steps else 1.0,
            "qualifies_order": not steps or forward * 10 >= len(steps) * 9, "before": before, "chosen": False, "pairs": pairs}


def choose(document):
    """(chosen candidate or None, every candidate in document order); a chosen candidate keeps its links under "pairs"."""
    candidates = [judge(name, pairs) for name, pairs in groups(document).items()]
    candidates.sort(key=lambda c: c["block"])
    qualifying = sorted((c for c in candidates if c["targets"] >= MIN_TARGETS and c["qualifies_order"] and c["before"]),
                        key=lambda c: -c["targets"])
    chosen = None
    if qualifying and (len(qualifying) == 1 or qualifying[0]["targets"] > qualifying[1]["targets"]):
        chosen = qualifying[0]
        chosen["chosen"] = True
    return chosen, candidates
