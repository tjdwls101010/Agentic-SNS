"""SEC filing documents from Yahoo's copies, as a text file to read and its map: check refuses a URL before any request, open_documents runs `filing`, render writes one document."""
from invest.filing.open import check, open_documents
from invest.filing.render import render

__all__ = ["check", "open_documents", "render"]
