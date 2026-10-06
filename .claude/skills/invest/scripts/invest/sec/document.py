"""One received document read into blocks, outline, links and tables: decode, recognise the form, read the markup, and refuse what cannot be read."""
from dataclasses import dataclass, field

from invest.sec import decode, markup
from invest.sec.failures import EmptyDocument, Unsupported
from invest.sec.text import blank, collapse

READS = "This skill turns HTML and plain-text filing documents into text."
FIXES = {"binary": "Open the filing's HTML document (the main form or an exhibit in `company filings` exhibits) instead; Yahoo's copy of this file is not converted.",
         "xml": "Read the HTML rendering of this record if the filing has one, or the record's values from another source; the XML is not converted.",
         "sgml": "Open the individual HTML document from the filing's exhibits instead of the whole submission.",
         "markup": "Open the original URL in a browser; nothing was guessed to fill the gap."}


@dataclass
class Fetched:
    body: bytes
    url: str
    content_type: str = ""


@dataclass
class Document:
    format: str
    blocks: list = field(default_factory=list)
    outline: list = field(default_factory=list)
    links: list = field(default_factory=list)
    tables: list = field(default_factory=list)
    encoding: dict = field(default_factory=dict)
    limits: list = field(default_factory=list)


def parse(fetched):
    """Read the received bytes; an unreadable form raises Unsupported and a document with no text raises EmptyDocument."""
    from lxml import etree

    kind = decode.binary_kind(fetched.body, fetched.content_type, fetched.url)
    if kind:
        raise Unsupported(f"This document is a {kind}. {READS}", fix=FIXES["binary"])
    text, encoding = decode.decode(fetched.body, fetched.content_type)
    if blank(text):
        raise EmptyDocument("The source answered with no text to read.", fix="Check that the URL names the document itself and not an index page; the response was empty.")
    name = decode.form(text, fetched.content_type, fetched.url)
    if name == "xml":
        raise Unsupported(f"This document is an XML record. {READS}", fix=FIXES["xml"])
    if name == "sgml":
        raise Unsupported(f"This is a multi-document SGML submission. {READS}", fix=FIXES["sgml"])
    limits = ["encoding_loss"] if encoding["loss"] else []
    blocks, outline, links, tables = [], [], [], []
    if name == "html":
        try:
            blocks, outline, links, tables, excluded = markup.read(text, fetched.url)
        except (ValueError, etree.LxmlError, RecursionError) as error:
            raise Unsupported(f"The HTML could not be read ({type(error).__name__}).", fix=FIXES["markup"]) from None
        if excluded:
            limits.append("inline_xbrl_metadata_excluded")
    else:
        blocks = [{"kind": "text", "text": line, "url": fetched.url} for line in map(collapse, text.splitlines()) if not blank(line)]
    if not any(not blank(block["text"]) for block in blocks):
        raise EmptyDocument("The document has no readable text.", fix="Open the original URL; it may hold only images or layout, which are not converted.")
    if any(item["kind"] == "image" for item in links):
        limits.append("image_content_not_extracted")
    return Document(name, blocks, outline, links, tables, encoding, limits)
