"""Read SEC company, filing and search evidence through one identified transport."""

import argparse
import sqlite3
import sys

from output import SecError, emit


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise SecError("invalid_argument", message, "Run the command with --help and correct its arguments.")


def parser():
    p = Parser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    p.add_argument("--json", action="store_true", help="Return structured JSON (also accepted after the command).")
    p.add_argument(
        "--cache-dir", help="Override the user cache directory; processes sharing this directory share the limiter."
    )
    p.add_argument("--env-file", help="Identity dotenv file; default: Scripts/.env. Identity is never printed.")
    commands = p.add_subparsers(dest="command", required=True, parser_class=Parser)
    descriptions = {
        "company": "Find exact ticker/CIK matches or company-name candidates; select a CIK explicitly for ambiguous names.",
        "filings": "List company filings newest first, keeping submission dates, report dates and amendments distinct.",
        "search": "Search filing and exhibit text since 2001 by default; each document remains a separate hit.",
        "open": "Open a filing index to list exhibits, or save an original document as an immutable reading snapshot.",
        "outline": "List a saved snapshot's contents links, detected headings and tables with their context; --kind selects anchors or link targets instead.",
        "find": "Find a literal string in one saved snapshot; matching ignores case unless --case-sensitive is set.",
        "read": "Read a saved snapshot range using opaque positions; no identity or network access is required.",
        "table": "Read one table as rows of non-empty cells with its context, caption and footnotes; empty layout cells are omitted.",
        "links": "List original links or images and their context in one saved snapshot; no external links are fetched.",
        "doctor": "Check requester configuration without printing its value; optionally test the SEC connection.",
        "schema": "Describe command inputs, output fields, defaults and error recovery without an identity.",
    }
    for name, description in descriptions.items():
        sub = commands.add_parser(
            name, help=description, description=description, formatter_class=argparse.RawTextHelpFormatter
        )
        sub.add_argument(
            "--json",
            action="store_true",
            default=argparse.SUPPRESS,
            help="Return structured JSON instead of readable text.",
        )
        if name in ["company", "filings", "search", "open"]:
            sub.add_argument("query", help="Company name/ticker/CIK, search text, or SEC filing URL/accession.")
            sub.add_argument(
                "--limit", type=int, default=20, help="Returned items, 1–100 (default 20); remote search pages are 100."
            )
            sub.add_argument("--cursor", help="Opaque saved continuation; repeat the original query and filters.")
        if name in ["filings", "search"]:
            sub.add_argument("--form", help="Exact form; amendments of this form are included unless excluded.")
            sub.add_argument(
                "--amendments",
                choices=["include", "exclude", "only"],
                default="include",
                help="Amendments: include originals and amendments (default), exclude amendments, or return amendments only.",
            )
            sub.add_argument("--filed-from", help="Inclusive submission date YYYY-MM-DD.")
            sub.add_argument("--filed-to", help="Inclusive submission date YYYY-MM-DD.")
        if name == "filings":
            sub.add_argument(
                "--report-from", help="Inclusive report date YYYY-MM-DD; missing report dates do not match."
            )
            sub.add_argument(
                "--report-to", help="Inclusive report date YYYY-MM-DD; distinct from dates of individual facts."
            )
        if name == "search":
            sub.add_argument("--company", help="Exact ticker or CIK; resolve ambiguous names with company first.")
            sub.add_argument(
                "--sort",
                choices=["date", "relevance"],
                default="date",
                help="Sort by newest filing date (default) or SEC relevance score.",
            )
        if name == "open":
            sub.add_argument(
                "--company",
                help="CIK/ticker required for a bare accession; never assumes the accession prefix is the issuer.",
            )
        if name in ["outline", "find", "read", "table", "links"]:
            sub.add_argument(
                "snapshot", help="Immutable snapshot_id returned by open; use the same --cache-dir, no identity needed."
            )
            sub.add_argument(
                "--cursor", help="Opaque continuation for this operation; repeat the same snapshot and all options."
            )
        if name in ["open", "outline", "find", "read", "table", "links"]:
            sub.add_argument(
                "--max-chars",
                dest="budget",
                type=int,
                default=12000,
                help="Response budget including its envelope, 1024–24000 characters (default 12000); the only page boundary for reader commands, kept below the host's ~30,000-character tool-output truncation.",
            )
        if name == "outline":
            sub.add_argument(
                "--kind",
                default="toc,heading,table",
                help="Comma-separated kinds from toc, heading, table, anchor, internal_link (default toc,heading,table); anchors are citation targets, not navigation.",
            )
        if name == "find":
            sub.add_argument("query", help="Nonempty literal text to find in snapshot text and table cells.")
            sub.add_argument(
                "--case-sensitive", action="store_true", help="Match letter case exactly; default ignores case."
            )
        if name == "read":
            sub.add_argument(
                "--position",
                help="Inclusive opaque position from find, outline, links context or read; default is document start.",
            )
            sub.add_argument(
                "--end", help="Exclusive opaque end position from this same snapshot; default is document end."
            )
        if name == "table":
            sub.add_argument(
                "table_id", help="Table identifier from open.tables or any outline entry whose kind is table."
            )
            sub.add_argument(
                "--rows",
                help="Original row numbers to return, e.g. 2-5 or 7 (default all rows); context, caption and footnotes always accompany them.",
            )
        if name == "links":
            sub.add_argument(
                "--kind",
                choices=["image", "internal", "external"],
                help="Filter image links, in-document anchors, or external links; default returns all kinds without fetching them.",
            )
        if name == "schema":
            sub.add_argument(
                "command_name",
                nargs="?",
                choices=list(descriptions),
                help="Describe one command instead of every command and output section.",
            )
        if name == "doctor":
            sub.add_argument(
                "--live", action="store_true", help="Check the SEC ticker endpoint through the identified transport."
            )
    return p


# Each command's output fields live in one section; a scoped request carries only that command's own contract.
SECTIONS = {"company": ("company", "listing"), "filings": ("listing",), "search": ("search", "listing"),
            "open": ("documents", "listing"), "outline": ("reading",), "find": ("reading",), "read": ("reading",),
            "table": ("reading",), "links": ("reading",), "doctor": (), "schema": ()}


def schema(command=None):
    p = parser()
    subs = next(a for a in p._actions if isinstance(a, argparse._SubParsersAction))

    def describe(action):
        return {
            "names": action.option_strings or [action.dest],
            "required": action.required,
            "default": action.default,
            "choices": action.choices,
            "help": action.help,
        }

    full = {
        "version": 1,
        "global_options": [describe(action) for action in p._actions if action.option_strings],
        "defaults": {
            "limit": 20,
            "max_chars": 12000,
            "max_chars_ceiling": 24000,
            "max_chars_reason": "the host truncates tool output around 30,000 characters; 12000 keeps several reads in one context window",
            "requests_per_second": 2,
            "search_from": "2001-01-01",
            "sort": "date",
        },
        "commands": {
            name: {
                "description": sub.description,
                "options": [describe(action) for action in sub._actions],
                "supported": True,
            }
            for name, sub in subs.choices.items()
        },
        "error": {"error": {"code": "stable machine code", "message": "reason", "fix": "recovery instruction"}},
        "listing": {
            "items": "source fields plus identifiers; filing and report dates are distinct; attachment rows retain sequence, filename, description, type, size and URL",
            "next_cursor": "opaque immutable continuation or null",
            "returned": "number returned",
            "remaining_saved": "already fetched items not returned",
            "remote_complete": "all relevant remote pages visited with no reported timeout, failed shards or search-window limit",
            "sources": "URL, sha256, fetched_at and content-type headers for each fetched page; raw bytes are immutable",
        },
        "company": {
            "match": "exact_ticker or exact_cik identifies an exact selection; name_candidate requires choosing a CIK",
            "selection_required": "true for ambiguous, name-based or empty candidates; never silently selects a name match",
            "total": "for name lookup, SEC filing-hit total and relation, not a count of unique company candidates",
        },
        "search": {
            "document_urls": "one original document URL per _source.ciks entry; multiple filers are retained, never inferred from accession prefix",
            "_id": "SEC accession:filename document identity; different exhibits remain distinct hits",
            "_source": "original SEC fields, including ciks/display_names, form/file_type, file_date and period_ending; a report date does not date every fact",
            "shards_failed": "sum of failed SEC search shards across fetched pages; any failure makes remote_complete false (also applies to company name lookup)",
            "total": "SEC value and relation (eq or gte)",
            "timed_out": "SEC partial-search flag",
            "limit_reached": "10,000 remote-hit window reached with more possible hits",
            "unreturned_reason": "remote_timeout, shard_failure, search_window_limit, incomplete_remote_page, more_results or null",
            "snapshot_scope": "only fetched pages are fixed; new pages are timestamped and document IDs deduplicated",
        },
        "documents": {
            "status": "parsed or unsupported; malformed supported content is a parse_failed error",
            "snapshot_id": "immutable content-addressed saved reading snapshot; all reader commands use this ID and the same cache",
            "source": "original SEC URL, raw-byte sha256, fetched_at and response content-type; never a fabricated fragment",
            "format": "html, xml, sgml, text, pdf or image; PDF/image open succeeds with unsupported status and original access path",
            "encoding": "selected encoding, original declarations, inferred/conflict/loss flags",
            "blocks": "number of saved reading blocks",
            "tables": "first table entries {table_id, rows, position, context, header}; context is the caption or nearest preceding prose and header the first row; table_count is the total, tables_has_more marks omitted entries and outline lists them all",
            "warnings": "extraction limitations: encoding_loss, inline_xbrl_metadata_excluded, external_entities_not_expanded, unsupported_format or image_content_not_extracted",
            "extraction_complete": "document extraction completeness; distinct from finishing the selected output range",
            "returned_chars": "actual emitted character count including the trailing newline; document summary obeys --max-chars",
        },
        "reading": {
            "snapshot_id": "same immutable snapshot for outline/find/read/table/links; no identity, fetch or reparsing is required",
            "position": "<snapshot fingerprint>:<block>:<offset>; repeat it unchanged, it is refused against another snapshot, and it is not a SEC URL fragment",
            "items": "outline: {kind, text, position} plus anchor when the original DOM had one, and table_id/rows/context/header (first 200 characters each) for tables; find: match text with position and match_end; read: prose in text once with {kind, position} items, or XML items carrying path, parent and attributes; table: rows of non-empty cells with column/spans/links and one position per row, with context/caption/footnotes leading the record stream; links: kind/url/text/position/context_position",
            "context_position": "when present, a saved internal location for surrounding evidence",
            "url": "links carry the original source URL; outline and find entries carry anchor instead, and only when that anchor was observed in the original DOM",
            "next_position": "read continuation position, or null at selected range end; --end remains exclusive",
            "next_cursor": "immutable continuation bound to operation, snapshot and all query/limit/budget options; repeat those options",
            "has_more": "more content remains within the selected operation or range",
            "scope_complete": "selected range/output returned completely; does not imply extraction_complete",
            "remaining_items": "unreturned operation items, including an item whose text is only partially returned",
            "text_complete": "false on an item whose text continues through next_cursor",
            "returned_chars": "actual emitted characters including envelope and trailing newline; --max-chars 1024..24000 is the only page boundary",
            "extraction_complete": "whether extraction is complete independently of output pagination",
            "warnings": "the snapshot's extraction limitations, repeated on every excerpt and omitted when there are none",
        },
        "recovery": {
            "identity_required": "configure the user-supplied email in Scripts/.env or --env-file; cached readers, help and schema need no identity",
            "cursor_mismatch": "repeat original command/options/snapshot or start a new query; do not reinterpret a cursor",
            "cache_corrupt": "use a fresh cache directory and reopen original sources; never trust corrupted bytes",
            "missing_snapshot": "use the original --cache-dir or open the source again",
            "filing_mismatch": "verify the exact accession and a declared filer CIK; never substitute the latest filing",
            "access_denied/rate_limited": "check identity and pause before retrying; 403/429 are never automatically retried",
            "parse_failed": "inspect the original source; parsing failures are errors rather than empty documents",
            "budget_too_small": "increase --max-chars within 1024..24000 or follow the original URL",
            "invalid_table": "follow outline continuations for every table_id in this snapshot",
            "invalid_position": "use a position returned for this same snapshot",
        },
    }
    if command is None:
        return full
    scoped = {"version": full["version"], "defaults": full["defaults"], "commands": {command: full["commands"][command]},
              "error": full["error"]}
    scoped.update({section: full[section] for section in SECTIONS[command]})
    return scoped


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in argv
    try:
        args = parser().parse_args(argv)
        if args.command == "schema":
            result = schema(args.command_name)
        else:
            from filings import dispatch

            result = dispatch(args)
        emit(result, args.json)
        return 0
    except SystemExit as exc:
        return int(exc.code)
    except SecError as exc:
        emit({"error": {"code": exc.code, "message": exc.message, "fix": exc.fix}}, as_json)
        return 2
    except sqlite3.Error:
        emit(
            {
                "error": {
                    "code": "cache_corrupt",
                    "message": "The shared cache database could not be read or updated.",
                    "fix": "Use a fresh --cache-dir; if the database is busy, wait for other SEC commands to finish.",
                }
            },
            as_json,
        )
        return 2
    except (OSError, ValueError, KeyError, TypeError) as exc:
        emit(
            {
                "error": {
                    "code": "invalid_data",
                    "message": f"Unable to process local or SEC data ({type(exc).__name__}).",
                    "fix": "Check inputs; use a fresh cache directory if saved data is damaged.",
                }
            },
            as_json,
        )
        return 2
    except Exception:  # noqa: BLE001 -- The CLI must return a structured error without exposing exception data or identity.
        emit(
            {
                "error": {
                    "code": "processing_failed",
                    "message": "The response could not be processed safely.",
                    "fix": "Verify the input and original SEC URL, or retry with a fresh cache directory.",
                }
            },
            as_json,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
