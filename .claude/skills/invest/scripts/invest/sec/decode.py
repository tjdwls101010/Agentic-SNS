"""Received bytes to text, and which form that text is in: HTML, plain text, or a form this skill does not read."""
import codecs
import re
from urllib.parse import urlsplit

# Formats recognised by their first bytes, whatever the server called them: PDF, PNG, JPEG, GIF, and the ZIP container an XLSX is.
BINARY_SIGNATURES = (b"%PDF-", b"\x89PNG", b"\xff\xd8", b"GIF87a", b"GIF89a", b"PK\x03\x04")


def media_of(content_type):
    return (content_type or "").split(";", 1)[0].strip().lower()


def binary_kind(body, content_type, url):
    """The name of the binary format these bytes are, or None when they are text."""
    media = media_of(content_type)
    path = urlsplit(url).path.lower()
    if body.startswith(b"%PDF-") or media == "application/pdf":
        return "PDF"
    if body.startswith(b"PK\x03\x04") or "spreadsheet" in media or media in ("application/zip", "application/vnd.ms-excel") or path.endswith((".xlsx", ".xls", ".zip")):
        return "spreadsheet or ZIP archive"
    # A CDN may call any file application/octet-stream, so that name alone decides nothing; the bytes do.
    if body.startswith(BINARY_SIGNATURES) or media.startswith("image/"):
        return "image"
    return None


def normalized(value):
    try:
        return codecs.lookup(value).name
    except LookupError:
        return value.lower()


def known(value):
    try:
        codecs.lookup(value)
        return True
    except LookupError:
        return False


def decode(body, content_type):
    """Return (text, encoding): the text, and which encoding was chosen, what was declared, and whether any bytes were lost."""
    from bs4 import UnicodeDammit

    header = re.search(r"charset=[\"']?([^;\"'\s]+)", content_type or "", re.IGNORECASE)
    header_encoding = header.group(1) if header else None
    decoded = UnicodeDammit(body, is_html=True)
    if not decoded.declared_html_encoding:
        # Bytes that decode as strict UTF-8 are almost never another encoding, while the guesser called a short UTF-8 page windows-1252 and turned U+200B into three letters; it is consulted only when UTF-8 fails.
        definite = [header_encoding, "utf-8"] if header_encoding else ["utf-8"]
        decoded = UnicodeDammit(body, known_definite_encodings=definite, is_html=True)
    text = decoded.unicode_markup or ""
    declarations = [value for value in (header_encoding, decoded.declared_html_encoding) if value]

    selected = decoded.original_encoding or "utf-8"
    declared = decoded.declared_html_encoding or header_encoding
    if declared and normalized(selected) not in (normalized(declared), "utf-8") and known(declared):
        # Neither the declared encoding nor UTF-8 fits every byte. Reading the declared one and marking what did not fit loses those bytes; the guesser's choice instead fit all of them by reading every non-ASCII character as something else (café became cafť).
        text, selected = body.decode(declared, errors="replace"), declared
    encoding = {"selected": selected, "declared": declarations, "inferred": not declarations,
                "conflict": any(normalized(v) != normalized(selected) for v in declarations),
                "loss": bool(decoded.contains_replacement_characters or "�" in text)}
    return text, encoding


def form(text, content_type, url):
    """'html', 'text', 'xml' or 'sgml' for a multi-document submission."""
    media = media_of(content_type)
    head = text[:10000]
    is_html = bool(re.search(r"<(?:html|body|div|p|table|h[1-6]|img|a|span|pre|ul|ol)(?:\s|>)", head, re.IGNORECASE))
    html_document = bool(re.search(r"<html(?:\s|>)", head, re.IGNORECASE))
    # A single <DOCUMENT> wrapper around ordinary HTML is one filing's markup, not a multi-document submission; treating it as SGML loses the images and tables inside it.
    if re.search(r"<DOCUMENT>", text, re.IGNORECASE) and (
        not is_html or re.search(r"<SEC-HEADER>", text, re.IGNORECASE) or len(re.findall(r"<DOCUMENT>", text, re.IGNORECASE)) > 1
    ):
        return "sgml"
    if (("xml" in media and media != "application/xhtml+xml")
            or (urlsplit(url).path.lower().endswith(".xml") and media != "text/html")
            or (text.lstrip().startswith("<?xml") and not html_document)):
        return "xml"
    return "html" if is_html else "text"
