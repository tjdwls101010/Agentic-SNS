"""Preserve SEC response fields while resolving companies and paging filing evidence."""

import re
from datetime import UTC, date, datetime

from output import SecError
from store import Store
from transport import TICKERS, Transport

EFTS = "https://efts.sec.gov/LATEST/search-index"


def cik(value):
    if not re.fullmatch(r"\d{1,10}", str(value)) or int(value) == 0:
        raise SecError(
            "invalid_company",
            "CIK must be a positive number of at most ten digits.",
            "Use company to find an exact CIK.",
        )
    return str(int(value)).zfill(10)


def company(query, transport, offset=0, names_only=False):
    if query.isdecimal():
        value, source = transport.json(f"https://data.sec.gov/submissions/CIK{cik(query)}.json")
        if cik(value["cik"]) != cik(query):
            raise SecError("invalid_response", "SEC returned a different CIK.", "Verify the company identifier.")
        return (
            [
                {
                    "cik": cik(value["cik"]),
                    "name": value["name"],
                    "tickers": value.get("tickers", []),
                    "match": "exact_cik",
                }
            ],
            [source],
            {"exhausted": True},
        )
    # 성진: 짧은 단어는 티커와 이름이 겹칠 수 있어 티커 조회 실패 후 이름 후보를 반환한다, 별도 기업 검색 API가 제공되면 교체한다.
    sources = []
    if not names_only and re.fullmatch(r"[A-Za-z0-9.-]{1,10}", query):
        value, source = transport.json(TICKERS)
        sources.append(source)
        rows = [dict(zip(value["fields"], row, strict=True)) for row in value["data"]]
        matches = [
            dict(row, cik=cik(row["cik"]), match="exact_ticker")
            for row in rows
            if row["ticker"].casefold() == query.casefold()
        ]
        if matches:
            return matches, sources, {"exhausted": True}
    value, source = transport.json(EFTS, {"entityName": query, "from": offset, "size": 100})
    sources.append(source)
    candidates = {}
    for hit in value["hits"]["hits"]:
        src = hit["_source"]
        for identifier, name in zip(src.get("ciks", []), src.get("display_names", []), strict=True):
            if query.casefold() not in name.casefold():
                continue
            candidates[cik(identifier)] = {"cik": cik(identifier), "name": name, "match": "name_candidate"}
    offset += len(value["hits"]["hits"])
    total = value["hits"]["total"]
    return (
        list(candidates.values()),
        sources,
        {
            "offset": offset,
            "total": total,
            "timed_out": bool(value.get("timed_out")),
            "shards_failed": value.get("_shards", {}).get("failed", 0),
            "limit_reached": offset >= 10000 and (total["relation"] == "gte" or total["value"] > 10000),
            "exhausted": len(value["hits"]["hits"]) < 100
            or offset >= 10000
            or total["relation"] == "eq"
            and offset >= total["value"],
        },
    )


def resolve(query, transport):
    if query.isdecimal():
        return cik(query), []
    items, sources, _ = company(query, transport)
    exact = [item for item in items if item["match"] == "exact_ticker"]
    if len(exact) != 1:
        raise SecError(
            "ambiguous_company" if items else "company_not_found",
            "An exact company selection is required.",
            "Run company, then use a returned CIK or exact ticker.",
        )
    return exact[0]["cik"], sources


def query_options(args):
    return {key: value for key, value in vars(args).items() if key not in ("json", "cursor", "cache_dir", "env_file")}


def validate_options(args):
    if hasattr(args, "budget") and not 1024 <= args.budget <= 12000:
        raise SecError("invalid_budget", "max-chars must be 1024..12000.", "Use a budget within this range.")
    if hasattr(args, "limit") and not 1 <= args.limit <= 100:
        raise SecError("invalid_argument", "limit must be between 1 and 100.", "Choose a limit from 1 to 100.")
    if hasattr(args, "query") and not args.query.strip():
        raise SecError("invalid_argument", "The query cannot be empty.", "Supply a company, search text or SEC URL.")
    for prefix in ("filed", "report"):
        low, high = getattr(args, prefix + "_from", None), getattr(args, prefix + "_to", None)
        for value in (low, high):
            try:
                if value and (
                    not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or date.fromisoformat(value).isoformat() != value
                ):
                    raise ValueError
            except ValueError:
                raise SecError(
                    "invalid_argument", "Dates must use YYYY-MM-DD.", "Supply an actual calendar date."
                ) from None
        if low and high and low > high:
            raise SecError(
                "invalid_argument", "The start date is after the end date.", "Use an ascending inclusive date range."
            )


def listing(args, store, state, extra=None):
    items = state["pending"][: args.limit]
    state["pending"] = state["pending"][args.limit :]
    cursor = (
        store.save({"query": query_options(args), "state": state})
        if state["pending"] or not state["exhausted"]
        else None
    )
    return {
        "items": items,
        "returned": len(items),
        "remaining_saved": len(state["pending"]),
        "next_cursor": cursor,
        "remote_complete": state["exhausted"],
        "sources": state["sources"],
        **(extra or {}),
    }


def matches(row, args):
    form = row.get("form", "")
    amendment = form.endswith("/A")
    if args.amendments == "exclude" and amendment or args.amendments == "only" and not amendment:
        return False
    if args.form and form not in {args.form, args.form + "/A"}:
        return False
    for prefix, field in [("filed", "filingDate"), ("report", "reportDate")]:
        low, high = getattr(args, prefix + "_from", None), getattr(args, prefix + "_to", None)
        value = row.get(field, "")
        if (low or high) and (not value or low and value < low or high and value > high):
            return False
    return True


def accession(value):
    if not re.fullmatch(r"\d{10}-\d{2}-\d{6}", value):
        raise SecError(
            "invalid_accession",
            "Accession must have the form ##########-##-######.",
            "Copy the exact accession from a SEC filing.",
        )
    return value


def archive_url(identifier, number, filename):
    from transport import validate_url

    if (
        not filename
        or filename.startswith("/")
        or any(part in ("", ".", "..") for part in filename.split("/"))
        or "\\" in filename
        or "%" in filename
        or "?" in filename
        or "#" in filename
    ):
        raise SecError(
            "invalid_response",
            "SEC returned an unsafe document filename.",
            "Use the filing index to verify the source link.",
        )
    return validate_url(
        f"https://www.sec.gov/Archives/edgar/data/{int(identifier)}/{accession(number).replace('-', '')}/{filename}"
    )


def filing_rows(columns, identifier, args):
    if not isinstance(columns, dict) or "accessionNumber" not in columns:
        raise SecError("invalid_response", "SEC filing columns are missing.", "Verify the submissions endpoint.")
    keys = list(columns)
    rows = [dict(zip(keys, values)) for values in zip(*(columns[k] for k in keys), strict=True)]
    result = []
    for row in rows:
        accession(row["accessionNumber"])
        if not matches(row, args):
            continue
        row["cik"] = identifier
        row["index_url"] = archive_url(identifier, row["accessionNumber"], row["accessionNumber"] + "-index.html")
        if row.get("primaryDocument"):
            row["document_url"] = archive_url(identifier, row["accessionNumber"], row["primaryDocument"])
        result.append(row)
    return sorted(result, key=lambda row: (row["filingDate"], row["accessionNumber"]), reverse=True)


def filings(args, store, transport):
    if args.cursor:
        state = store.resume(args.cursor, query_options(args))
    else:
        identifier, sources = resolve(args.query, transport)
        value, source = transport.json(f"https://data.sec.gov/submissions/CIK{identifier}.json")
        if cik(value["cik"]) != identifier:
            raise SecError("invalid_response", "SEC returned a different CIK.", "Verify the company identifier.")
        files = [
            file
            for file in value["filings"]["files"]
            if not (
                args.filed_from
                and file.get("filingTo")
                and file["filingTo"] < args.filed_from
                or args.filed_to
                and file.get("filingFrom")
                and file["filingFrom"] > args.filed_to
            )
        ]
        files.sort(key=lambda file: file.get("filingTo", ""), reverse=True)
        state = {
            "cik": identifier,
            "pending": filing_rows(value["filings"]["recent"], identifier, args),
            "files": files,
            "sources": sources + [source],
            "exhausted": not files,
            "seen": [],
        }
    while len(state["pending"]) < args.limit and state["files"]:
        file = state["files"].pop(0)["name"]
        if not re.fullmatch(r"CIK" + state["cik"] + r"-submissions-\d+\.json", file):
            raise SecError(
                "unsafe_url", "SEC supplied an invalid historical filename.", "Verify the company submissions response."
            )
        value, source = transport.json("https://data.sec.gov/submissions/" + file)
        state["sources"].append(source)
        state["pending"].extend(filing_rows(value, state["cik"], args))
    state["exhausted"] = not state["files"]
    seen = set(state["seen"])
    state["pending"] = [row for row in state["pending"] if row["accessionNumber"] not in seen]
    state["seen"].extend(row["accessionNumber"] for row in state["pending"][: args.limit])
    return listing(args, store, state)


def search_status(state, has_more):
    incomplete = state["exhausted"] and (
        state["total"]["relation"] == "gte" or state["offset"] < state["total"]["value"]
    )
    partial = state["timed_out"] or state["shards_failed"] > 0 or state["limit_reached"] or incomplete
    result = {key: state[key] for key in ("total", "timed_out", "limit_reached", "shards_failed")}
    result["remote_complete"] = state["exhausted"] and not partial
    result["unreturned_reason"] = (
        "remote_timeout"
        if state["timed_out"]
        else "shard_failure"
        if state["shards_failed"]
        else "search_window_limit"
        if state["limit_reached"]
        else "incomplete_remote_page"
        if incomplete
        else "more_results"
        if has_more
        else None
    )
    return result


def search(args, store, transport):
    if args.cursor:
        state = store.resume(args.cursor, query_options(args))
    else:
        identifier, sources = resolve(args.company, transport) if args.company else (None, [])
        state = {
            "cik": identifier,
            "pending": [],
            "sources": sources,
            "exhausted": False,
            "seen": [],
            "offset": 0,
            "total": None,
            "timed_out": False,
            "limit_reached": False,
            "shards_failed": 0,
            "startdt": args.filed_from or "2001-01-01",
            "enddt": args.filed_to or datetime.now(UTC).date().isoformat(),
        }
    while len(state["pending"]) < args.limit and not state["exhausted"]:
        params = {
            "q": args.query,
            "from": state["offset"],
            "size": 100,
            "dateRange": "custom",
            "startdt": state["startdt"],
            "enddt": state["enddt"],
        }
        if args.sort == "date":
            params["sort"] = "desc"
        if state["cik"]:
            params["ciks"] = state["cik"]
        if args.form:
            params["forms"] = args.form
        value, source = transport.json(EFTS, params)
        state["sources"].append(source)
        total = value["hits"]["total"]
        if (
            not isinstance(total, dict)
            or total.get("relation") not in ("eq", "gte")
            or not isinstance(total.get("value"), int)
        ):
            raise SecError(
                "invalid_response", "SEC search totals have an unknown shape.", "Retry later or narrow the query."
            )
        state["total"] = total
        state["timed_out"] |= bool(value.get("timed_out"))
        state["shards_failed"] += value.get("_shards", {}).get("failed", 0)
        hits = value["hits"]["hits"]
        seen = set(state["seen"])
        for hit in hits:
            if hit["_id"] in seen:
                continue
            seen.add(hit["_id"])
            state["seen"].append(hit["_id"])
            src = hit["_source"]
            if matches({"form": src.get("form", ""), "filingDate": src.get("file_date", "")}, args):
                number, separator, filename = hit["_id"].partition(":")
                if not separator or src.get("adsh") != number:
                    raise SecError(
                        "invalid_response",
                        "SEC search document identity is inconsistent.",
                        "Open the filing index to verify this result.",
                    )
                hit["document_urls"] = [
                    archive_url(cik(identifier), number, filename) for identifier in src.get("ciks", [])
                ]
                state["pending"].append(hit)
        state["offset"] += len(hits)
        state["limit_reached"] = state["offset"] >= 10000 and (total["relation"] == "gte" or total["value"] > 10000)
        state["exhausted"] = (
            len(hits) < 100
            or state["offset"] >= 10000
            or total["relation"] == "eq"
            and state["offset"] >= total["value"]
        )
    result = listing(args, store, state)
    result.update(search_status(state, bool(result["next_cursor"])))
    result["snapshot_scope"] = (
        "Only fetched pages are fixed; new remote pages are timestamped and document IDs deduplicated."
    )
    return result


def open_filing(args, store, transport):
    from urllib.parse import parse_qs, urljoin, urlsplit

    from bs4 import UnicodeDammit
    from edgar.attachments import Attachments
    from lxml import html
    from transport import filing_location, validate_url

    if args.cursor:
        return listing(args, store, store.resume(args.cursor, query_options(args)))
    if "://" in args.query:
        url = validate_url(args.query)
    else:
        number = accession(args.query)
        if not args.company:
            raise SecError(
                "company_required",
                "A bare accession requires its filing company.",
                "Supply --company with the CIK or ticker; the accession prefix may identify a filing agent.",
            )
        identifier, _ = resolve(args.company, transport)
        url = archive_url(identifier, number, number + "-index.html")
    if filing_location(url) is None:
        raise SecError(
            "unsafe_url",
            "Open requires a SEC filing document or index URL.",
            "Use a document URL under /Archives/edgar/data/.",
        )
    body, source = transport.get(url)
    if not urlsplit(url).path.endswith(("-index.html", "-index.htm")):
        import json

        from document import SourceDocument, parse_document

        snapshot = parse_document(SourceDocument(body, source, source["headers"]), store)
        summary = snapshot.summary()
        summary["source"] = source
        summary["tables"] = summary["tables"][: args.limit]
        summary["table_discovery"] = (
            "Run outline with this snapshot_id and follow next_cursor; kind=table entries contain every table_id."
        )
        summary["returned_chars"] = args.budget
        while len(json.dumps(summary, ensure_ascii=False, indent=2)) + 1 > args.budget and summary["tables"]:
            summary["tables"].pop()
        summary["tables_has_more"] = len(summary["tables"]) < summary["table_count"]
        summary["returned_chars"] = len(json.dumps(summary, ensure_ascii=False, indent=2)) + 1
        if summary["returned_chars"] > args.budget:
            raise SecError(
                "budget_too_small",
                "The snapshot summary metadata exceeds this budget.",
                "Increase --max-chars or inspect the original source URL.",
            )
        return summary
    text = UnicodeDammit(body).unicode_markup
    if text is None:
        raise SecError(
            "parse_failed", "The filing index encoding could not be decoded.", "Read the original SEC filing index."
        )
    root = html.fromstring(text)
    if not root.xpath('//table[contains(concat(" ", normalize-space(@class), " "), " tableFile ")]'):
        raise SecError(
            "parse_failed",
            "The response does not contain a SEC filing document table.",
            "Verify the exact filing index URL.",
        )
    expected_cik, expected_accession = filing_location(url)
    actual_accessions = re.findall(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", root.xpath('string(//*[@id="secNum"])'))
    filers = set()
    for href in root.xpath('//div[contains(@class,"companyInfo")]//a/@href'):
        for value in parse_qs(urlsplit(href).query).get("CIK", []):
            filers.add(cik(value))
    if (
        actual_accessions != [expected_accession[:10] + "-" + expected_accession[10:12] + "-" + expected_accession[12:]]
        or expected_cik not in filers
    ):
        raise SecError(
            "filing_mismatch",
            "The index does not confirm the requested accession and filer CIK.",
            "Verify the exact SEC filing URL and company CIK.",
        )
    try:
        attachments = Attachments.load(root)
        items = []
        for attachment in attachments:
            path = attachment.path
            link = validate_url(urljoin(url, path))
            location = filing_location(link)
            if location is None or location[1] != expected_accession or location[0] not in filers:
                raise SecError(
                    "filing_mismatch",
                    "An attachment belongs to a different filing or undeclared filer.",
                    "Verify the source filing index and attachment link.",
                )
            items.append(
                {
                    "sequence_number": attachment.sequence_number,
                    "document": attachment.document,
                    "description": attachment.description,
                    "document_type": attachment.document_type,
                    "size": attachment.size,
                    "url": link,
                }
            )
    except (IndexError, AttributeError, ValueError, TypeError):
        raise SecError(
            "parse_failed",
            "The SEC attachment table could not be parsed completely.",
            "Read the original index and verify its attachment rows.",
        ) from None
    return listing(args, store, {"pending": items, "sources": [source], "exhausted": True})


def dispatch(args):
    validate_options(args)
    store = Store(args.cache_dir)
    cursor = getattr(args, "cursor", None) if args.command in ("company", "filings", "search", "open") else None
    if cursor:
        replay = store.replay(cursor, query_options(args))
        if replay is not None:
            return replay
    result = execute(args, store)
    return store.complete_cursor(cursor, query_options(args), result) if cursor else result


def execute(args, store):
    if args.command in ("outline", "find", "read", "table", "links"):
        import reader
        from document import load_snapshot

        snapshot = load_snapshot(store, args.snapshot)
        options = {"cursor": args.cursor, "limit": args.limit, "budget": args.budget}
        if args.command == "find":
            options.update(query=args.query, case_sensitive=args.case_sensitive)
        elif args.command == "read":
            options.update(position=args.position, end=args.end)
        elif args.command == "table":
            options["table_id"] = args.table_id
        elif args.command == "links":
            options["kind"] = args.kind
        return getattr(reader, args.command)(snapshot, store, **options)
    transport = Transport(store, args.env_file)
    if args.command == "open":
        return open_filing(args, store, transport)
    if args.command == "search":
        return search(args, store, transport)
    if args.command == "filings":
        return filings(args, store, transport)
    if args.command == "doctor":
        if args.live:
            transport.json(TICKERS)
        return {
            "identity_configured": True,
            "connection": "ok" if args.live else "not_checked",
            "requests_per_second": 2,
        }
    if args.cursor:
        state = store.resume(args.cursor, query_options(args))
        if not state["pending"] and not state["exhausted"]:
            items, sources, metadata = company(args.query, transport, state["offset"], names_only=True)
            metadata["timed_out"] |= state["timed_out"]
            metadata["shards_failed"] += state["shards_failed"]
            state.update(metadata)
            state["sources"].extend(sources)
            state["pending"] = [item for item in items if item["cik"] not in state["seen"]]
            state["seen"].extend(item["cik"] for item in state["pending"])
    else:
        items, sources, metadata = company(args.query, transport)
        state = {
            "pending": items,
            "sources": sources,
            "selection_required": len(items) != 1 or any(i["match"] == "name_candidate" for i in items),
            "seen": [item["cik"] for item in items],
            **metadata,
        }
    result = listing(args, store, state, {"selection_required": state["selection_required"]})
    if "total" in state:
        result.update(search_status(state, bool(result["next_cursor"])))
    return result
