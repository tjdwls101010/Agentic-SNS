"""Open each filing URL: receive Yahoo's copy, read it, save its text file and map, and print one receipt for every document.

A URL this skill does not read is refused before anything runs (check); every other failure is that document's own result, so one missing exhibit does not hide the ones that were read.
"""
import datetime as dt
import hashlib
from pathlib import PurePosixPath
import re
from urllib.parse import urlsplit

from invest import documents, receipts, results, sec
from invest.filing.render import VERSION, render

WARNINGS = {"encoding_loss": "Some bytes did not decode; each is U+FFFD in the text, so a quotation there may differ from the original."}
NOT_SAVED = {"code": "not_saved", "text": "The receipt could not be saved, so receipt_path is absent; the documents listed with a path were saved."}
# What a caller reads first: where the document is and how large; then how to navigate it; then what conversion left out.
ORDER = ("target", "status", "source", "path", "map_path", "lines", "chars", "contents", "headings", "tables", "images", "links", "limits", "warnings",
         "observed_at", "reused", "error")


def check(urls):
    """Refuse, before any request, a URL that names no filing document this skill reads; Yahoo's spreadsheets pass and fail as their own result."""
    for url in urls:
        try:
            sec.locate(url)
        except receipts.Invalid:
            raise
        except receipts.Failure:
            pass


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def extension(url):
    suffix = PurePosixPath(urlsplit(url).path).suffix.lower()
    return suffix if re.fullmatch(r"\.[a-z0-9]{1,5}", suffix) else ".bin"


def lined(item):
    return f"L{item['line']} {item['text']}"


def one(url, timeout):
    """The receipt entry for one URL; the document is saved when it was read."""
    observed = now()
    try:
        located = sec.locate(url)
        fetched = sec.fetch(located, timeout)
        observed = now()
        document = sec.parse(fetched)
        digest = hashlib.sha256(fetched.body).hexdigest()
        rendered = render(document, {"source": located.source, "fetch": located.fetch, "sha256": digest})
        source = {"source": located.source, "fetch": located.fetch, "sha256": digest, "bytes": len(fetched.body), "content_type": fetched.content_type or None,
                  "fetched_at": observed, "text_version": VERSION, "encoding": document.encoding}
        folder, reused = documents.publish(documents.key(located.source, digest, VERSION, fetched.content_type), {
            "document.txt": rendered.text, "map.json": results.json_text(rendered.map), "source.json": results.json_text(source),
            f"original{extension(located.fetch)}": fetched.body})
    except receipts.Failure as exc:
        return {"target": url, "status": "error", "observed_at": observed, "error": receipts.failure(exc.code, exc, exc.fix)}
    found = rendered.map
    entry = {"target": url, "status": "ok", "source": located.source, "path": str(folder / "document.txt"), "map_path": str(folder / "map.json"),
             "lines": found["lines"], "chars": found["chars"]}
    if found["contents"]:
        entry["contents"] = [{**{k: v for k, v in e.items() if k != "inside"}, **({"inside": [lined(h) for h in e["inside"]]} if e.get("inside") else {})}
                             for e in found["contents"]]
    else:
        entry["headings"] = [lined(h) for h in found["headings"]]
    entry.update(tables=len(found["tables"]), images=len(found["images"]), links=len(found["links"]), limits=found["limits"])
    warned = [{"code": code, "text": text} for code, text in WARNINGS.items() if code in found["limits"]]
    if warned:
        entry["warnings"] = warned
    entry.update(observed_at=observed, reused=reused)
    return entry


def no_inside(document):
    for result in document["results"]:
        for entry in result.get("contents", []):
            entry.pop("inside", None)
    return document


def no_headings(document):
    for result in document["results"]:
        result.pop("headings", None)
    return document


def no_contents(document):
    for result in document["results"]:
        result.pop("contents", None)
    return document


def open_documents(args):
    """(document to print, exit code) for `filing URL...`."""
    ident = results.new_id()
    receipt_path = results.paths(ident)["receipt"]
    receipts.precheck(args.command, args.targets, tuple(WARNINGS), receipt_path, args.max_chars, document_codes=("not_saved",))
    results.prune(args.ttl_days)
    found = [receipts.ordered(one(url, args.timeout), ORDER) for url in args.targets]
    document = {"status": receipts.document_status([r["status"] for r in found]), "command": args.command, "receipt_path": receipt_path,
                "warnings": [], "results": found, "trimmed": False}
    try:
        results.publish(ident, {"id": ident, **document})
    except receipts.LocalIO:
        document.pop("receipt_path")
        document["warnings"] = [NOT_SAVED]
    document = receipts.ordered(document, receipts.DOCUMENT_ORDER)
    printed = receipts.fit(document, args.max_chars, steps=[no_inside, no_headings, no_contents])
    return printed, receipts.exit_code(printed)
