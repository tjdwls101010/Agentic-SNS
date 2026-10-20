"""notifications: the viewer's own notification list in the server's order, read without marking anything seen."""
from sns import reading
from sns.facebook.listing import NOTES, issue_notes, paged

# Asked for the page after the first (CometNotificationsListPaginationQuery with its end cursor), Facebook answered no
# rows although the first page said more follow (observed 2026-10-21): the first page is all there is to read.
# 성진: 화면의 '이전 알림 보기'가 보내는 요청을 (읽음 처리 없이) 관찰하면 다음 쪽을 다시 열 것
OLDER = ('Facebook says older notifications follow (its "see previous" button); asking for them returned nothing when '
         'this was measured, so only this first page is read')


def notifications(platform, invocation):
    def read(connection, state, out):
        issues, capped = [], []

        def fetch(cursor):
            batch = connection.client.notifications()
            issues.extend(batch.issues)
            page = paged(batch)
            if page.next is not None:
                page.next, page.stop = None, 'server_capped'
                capped.append(True)
            return page

        # Facebook has no date filter here and lists newest first in buckets; the page size is Facebook's (15 asked for)
        result = reading.read_list(connection, state, out, order='server', command='notifications', target=None,
                                   identity={}, words=(), extra=None, notes=NOTES, fetch=fetch)
        result['coverage'] = [*result.get('coverage', []), *issue_notes(issues), *([OLDER] if capped else [])]
        return result

    return reading.run(platform, invocation, command='notifications', target=None, identity={}, reader=read)
