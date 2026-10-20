"""notifications: the viewer's own notification list in the server's order, read without marking anything seen."""
from sns import reading
from sns.facebook.listing import surface


def notifications(platform, invocation):
    def read(connection, state, out):
        # Facebook has no date filter here and lists newest first in buckets; the page size is Facebook's (15 asked for)
        return surface(connection, state, out, order='server', command='notifications', target=None, identity={},
                       fetch=connection.client.notifications)

    return reading.run(platform, invocation, command='notifications', target=None, identity={}, reader=read)
