"""The ways reading a filing document fails, as the skill's failure codes."""
from invest.receipts import Failure


class Unsupported(Failure):
    """The document is in a form this skill does not turn into text, or cannot lay out faithfully."""

    code = "unsupported"


class EmptyDocument(Failure):
    """The source answered, but there is no text to read in what it sent."""

    code = "empty_document"


class NotFound(Failure):
    code = "not_found"
