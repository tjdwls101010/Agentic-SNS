"""notifications: the viewer's own notification list in the server's order, read without marking anything seen."""
from sns import reading
from sns.facebook.listing import NOTES, issue_notes, paged


def notifications(platform, invocation):
    def read(connection, state, out):
        issues = []

        def fetch(cursor):
            batch = connection.client.notifications(cursor)
            issues.extend(batch.issues)
            return paged(batch)

        # Facebook has no date filter here and lists newest first in buckets; the page size is Facebook's (15 asked for first, 10 for each older page, as the screen asks)
        result = reading.read_list(connection, state, out, order='server', command='me', target=None,
                                   identity={}, words=['notifications'], extra=None, notes=NOTES, fetch=fetch)
        result['coverage'] = [*result.get('coverage', []), *issue_notes(issues)]
        return result

    return reading.run(platform, invocation, command='me', target=None, identity={}, reader=read)
