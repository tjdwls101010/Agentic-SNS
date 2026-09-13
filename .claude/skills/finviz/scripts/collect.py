"""Checkpoint collection progress and export observations without overwriting edits."""

import hashlib
import json
import os
from pathlib import Path
import tempfile
from uuid import uuid4

from extract import parse, walk
from runtime import Failure, fetch, now


def items(result):
    data = result["data"]
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and data.get("tables"):
        return [row for table in data["tables"] for row in table["rows"]]
    for node in walk(data):
        if isinstance(node, dict) and isinstance(node.get("items"), list):
            return node["items"]
    return [] if data is None else [data]


def collect(args, store):
    if args.id.startswith("c_"):
        key = args.id
        state = store.collection(key)
    else:
        first = store.get(args.id)
        if first["status"] == "error":
            raise Failure(
                "invalid_collection_start",
                "The starting observation has no usable data.",
                "Retry the source first, then collect its new result ID.",
            )
        key = "c_" + uuid4().hex
        state = dict(
            started_at=now(),
            observations=[first["id"]],
            failures=[],
            next_url=first["continuation"],
            stop_reason="no_continuation",
            exports={},
        )
    store.collection(key, state)
    visited = {store.get(i)["source"]["url"] for i in state["observations"]}
    for _ in range(args.max_pages):
        url = state["next_url"]
        if not url:
            break
        if url in visited:
            state["stop_reason"] = "repeated_page"
            break
        result = fetch(url, args, store, parse)
        if result["status"] == "error":
            state["failures"].append(result["id"])
            state["stop_reason"] = "request_failed"
            store.collection(key, state)
            break
        visited.add(url)
        state["observations"].append(result["id"])
        state["next_url"] = result["continuation"]
        state["stop_reason"] = "page_limit" if state["next_url"] else "no_continuation"
        store.collection(key, state)
    records, seen = [], set()
    duplicates = 0
    source_totals = []
    for observation in state["observations"]:
        result = store.get(observation)
        source_totals.append(result["coverage"].get("source_total"))
        records.append(result)
        for item in items(result):
            fingerprint = json.dumps(item, ensure_ascii=False, sort_keys=True)
            if fingerprint in seen:
                duplicates += 1
                continue
            seen.add(fingerprint)

    state.update(unique_items=len(seen), duplicates=duplicates, source_totals=source_totals, exhaustive=False)
    if args.out:
        target = Path(args.out).expanduser().absolute()
        expected = state["exports"].get(str(target))
        if (
            target.is_symlink()
            or target.exists()
            and (expected is None or hashlib.sha256(target.read_bytes()).hexdigest() != expected)
        ):
            raise Failure(
                "export_conflict",
                "The destination exists outside this export or was edited.",
                "Choose a new --out path; existing content was not changed.",
            )
        content = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records).encode()
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            with target.open("xb") as output:
                output.write(content)
        else:
            with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as output:
                output.write(content)
                temp = output.name
            try:
                os.replace(temp, target)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
        state["exports"][str(target)] = hashlib.sha256(content).hexdigest()
    store.collection(key, state)
    status = (
        "partial"
        if state["next_url"] or any(store.get(i)["status"] == "partial" for i in state["observations"])
        else "ok"
    )
    errors = [dict(error, observation_id=r["id"]) for r in records for error in r["errors"]]
    if state["stop_reason"] == "request_failed":
        errors.extend(store.get(state["failures"][-1])["errors"])
    return dict(id=key, status=status, store=str(store.path), data=state, errors=errors)
