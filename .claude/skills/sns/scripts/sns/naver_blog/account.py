"""Which account a Naver Blog reading is read as: a hint stamped on a public reading's handle, and the viewer a post page
names for free."""


def binds(options, display):
    """Whether a public listing is tied to the account: it goes on past one screen (a --limit above `display`, or a
    window), so it may run until the time limit, and could not then afford the request that lets it leave a more: line.
    A one-screen read is not: it asks only if its handle needs it, and the hint answers."""
    limit = options.get('limit')
    return bool((limit and limit > display) or options.get('since') or options.get('until'))


def adopt_hint(connection, state):
    """A public reading that may leave a handle stamps it with the account seen within the last 12 hours rather than
    ask who is logged in (one request): a hint, never proof. Continuing a handle checks the account for real, so a
    login that changed meanwhile is exit 4, not a silent read as another account."""
    if state is None and connection.known_viewer is None and connection.observed is None:
        hint = connection.session.viewer_hint()
        if hint:
            connection.observed = hint['viewer']


def note_viewer(connection, doc):
    """A post page names the logged-in viewer for free: it must be the account this command started with, and it
    refreshes the hint."""
    if doc.viewer_id:
        connection.seen(doc.viewer_id)
        connection.session.remember_viewer(doc.viewer_id)
