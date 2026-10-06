"""A read document as the text file Claude reads with Read and grep, and the map of where things are in it.

One paragraph or one table row is one line, so a line number is a stable place to read from, and every position the map gives is a line of this file. The first line names the original document; nothing in the file is the parser's own judgement except what the map labels as such (the contents, the set-apart lines).
"""
from dataclasses import dataclass

from invest.filing.contents import choose

# Raised whenever a line of the file can change for the same bytes, so a saved file is never reused across a change in how it is written.
VERSION = 1
# A wholly bold paragraph: at least four of every five of its letters set bold.
BOLD = (4, 5)
# A contents range larger than this lists the set-apart lines inside it, where a reader needs a finer place to start.
INSIDE = 20000
TITLE = 90


@dataclass
class Rendered:
    text: str
    map: dict


def escape(value):
    return value.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "\\n")


def bold(item):
    return item["kind"] == "emphasis" and "table_id" not in item and item["bold_chars"] * BOLD[1] >= item["chars"] * BOLD[0]


def row_fields(table, row, extra):
    """The row's fields from the canonical text, with `extra` {field index: text} appended where an image sits."""
    entry = table["row_ranges"][row]
    fields = table["text"][entry[1]:entry[2]].split("\t") if entry[2] > entry[1] else []
    fields += [""] * (len(table["kept_columns"]) - len(fields))
    for index, value in extra.items():
        fields[index] = f"{fields[index]} {value}" if fields[index] else value
    while fields and not fields[-1]:
        fields.pop()
    return fields


def frame(name, table):
    kept = table["kept_columns"]
    lines = [f"[{name} | {table['original_rows']} rows x {len(kept)} columns]"]
    if table.get("caption"):
        lines.append(f"caption: {table['caption']['text']}")
    spans = []
    for span in table["spans"]:
        if span["column"] not in kept:
            continue
        first = kept.index(span["column"])
        wide = f" c{first}-{first + span['w'] - 1}" if span["w"] > 1 else ""
        rows = span.get("effective_rows", span["rowspan"])
        tall = f" rows {span['row']}-{span['row'] + rows - 1}" if rows != 1 else ""
        if wide or tall:
            spans.append(f"r{span['row']}c{first}{wide}{tall}")
    if spans:
        lines.append("spans: " + " ".join(spans))
    headers = [f"r{c['row']}c{kept.index(c['column'])}" + (f"={c['scope']}" if c.get("scope") else "")
               for c in table["cells"] if c.get("th") and c["column"] in kept]
    if headers:
        lines.append("th: " + " ".join(headers))
    return lines


def image_text(image):
    return " ".join(f"[image: {image['text'] or 'no alt text'} | {image['url']}]".split())


def render(document, identity):
    """Rendered(text, map) for a parsed Document; `identity` names the original (`source`), the copy fetched (`fetch`) and the bytes' `sha256`."""
    tables = {t["table_id"]: t for t in document.tables}
    names = {table_id: "t" + table_id.split("-")[1] for table_id in tables}
    chosen, candidates = choose(document)
    in_contents = {id(link) for link, _, _ in (chosen or {}).get("pairs", [])}
    starred = {item["block"] for item in document.outline if bold(item)}
    images = {}
    for link in document.links:
        if link["kind"] == "image":
            images.setdefault((link["block"], link.get("table_id"), link.get("row"), link.get("column")), []).append(link)

    lines = [f"SOURCE {identity['source']} | Yahoo copy {identity['fetch']} | sha256 {identity['sha256'][:16]} | text v{VERSION}"]
    block_line, row_line, image_line = {}, {}, {}
    for index, block in enumerate(document.blocks):
        block_line[index] = len(lines) + 1
        if block["kind"] == "grid":
            table = tables[block["table_id"]]
            name = names[table["table_id"]]
            lines += frame(name, table)
            for image in images.get((index, table["table_id"], None, None), []):  # an image in the caption, right after it
                image_line[image["id"]] = len(lines) + 1
                lines.append(image_text(image))
            for row, _, _ in table["row_ranges"]:
                extra = {}
                for field, column in enumerate(table["kept_columns"]):
                    for image in images.get((index, table["table_id"], row, column), []):
                        extra[field] = " ".join(filter(None, [extra.get(field), image_text(image)]))
                        image_line[image["id"]] = len(lines) + 1
                row_line[(table["table_id"], row)] = len(lines) + 1
                lines.append("|".join([f"{name}.{row}"] + [escape(field) for field in row_fields(table, row, extra)]))
        elif block["text"]:
            lines.append(f"**{block['text']}**" if index in starred else block["text"])
        for image in images.get((index, None, None, None), []):
            image_line[image["id"]] = len(lines) + 1
            lines.append(image_text(image))
    total = len(lines)

    def place(block, table_id=None, row=None):
        """The line a position is on: a table row's own line, else its block's first line; a block that wrote no line gives the next line."""
        found = row_line.get((table_id, row)) if table_id and row is not None else block_line.get(block)
        return min(found or total, total)

    def landing(link):
        """Where a link lands: its target's line, or the next line when the target sits after the last character of its paragraph."""
        block, text = link["target_block"], document.blocks[link["target_block"]]["text"] if link["target_block"] < len(document.blocks) else ""
        if not link.get("target_table_id") and text and link["target_offset"] >= len(text):
            return place(block + 1)
        return place(block, link.get("target_table_id"), link.get("target_row"))

    marks, links = {}, []
    for link in document.links:
        if link["kind"] == "image":
            continue
        at = place(link["block"], link.get("table_id"), link.get("row"))
        entry = {"line": at, "kind": link["kind"], "text": link["text"], "url": link["url"]}
        if "target_block" in link:
            entry["target_line"] = landing(link)
            if id(link) not in in_contents:
                marks.setdefault(at, []).append(entry["target_line"])
        links.append(entry)
    for at, targets in marks.items():
        lines[at - 1] += " " + " ".join(f"[→L{target}]" for target in dict.fromkeys(targets))

    text = "\n".join(lines) + "\n"
    sizes = [len(line) + 1 for line in lines]
    headings = set_apart(document, place)
    return Rendered(text, {
        "version": VERSION, "source": identity["source"], "fetch": identity["fetch"], "sha256": identity["sha256"],
        "lines": total, "chars": len(text),
        "contents": entries(chosen, landing, sizes, headings) if chosen else None,
        "candidates": [{"group": c["group"], "line": place(c["block"]), "targets": c["targets"], "ordered": c["ordered"], "before": c["before"],
                        "chosen": c["chosen"]} for c in candidates],
        "headings": headings,
        "tables": [{"id": names[t["table_id"]], "line": block_line[t["block"]], "rows": t["original_rows"], "columns": len(t["kept_columns"]),
                    "context": t["context"][:200]} for t in document.tables],
        "images": [{"line": image_line[i["id"]], "alt": i["text"], "url": i["url"]} for i in document.links if i["kind"] == "image"],
        "links": links,
        "limits": document.limits,
    })


def set_apart(document, place):
    """Every line the document set apart, each place it occurs: navigation emphasis, wholly bold paragraphs, and the emphasized row of a one-row table."""
    one_row = {t["table_id"] for t in document.tables if t["original_rows"] == 1}
    found = {}
    for item in document.outline:
        if item["kind"] != "emphasis":
            continue
        if item["navigation"] or bold(item) or item.get("table_id") in one_row:
            found.setdefault(place(item["block"], item.get("table_id"), item.get("row")), item["text"][:TITLE])
    return [{"line": at, "text": text} for at, text in sorted(found.items())]


def entries(chosen, landing, sizes, headings):
    """One entry per target line, in file order: its title, its line range up to the next entry, and the characters in that range."""
    titles = {}
    for link, _, _ in chosen["pairs"]:
        at = landing(link)
        titles.setdefault(at, [])
        if link["text"]:
            titles[at].append(link["text"])
    starts = sorted(titles)
    found = []
    for n, start in enumerate(starts):
        end = starts[n + 1] - 1 if n + 1 < len(starts) else len(sizes)
        entry = {"title": " ".join(dict.fromkeys(titles[start])), "lines": f"{start}-{end}", "chars": sum(sizes[start - 1:end])}
        if entry["chars"] > INSIDE:
            inside = [h for h in headings if start < h["line"] <= end]
            if inside:
                entry["inside"] = inside
        found.append(entry)
    return found
