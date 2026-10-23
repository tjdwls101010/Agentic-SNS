"""about: the visible About fields of a profile or page, read tab by tab; a group's card for a group URL."""
from datetime import datetime

from sns import reading
from sns.errors import SnsError
from sns.facebook import web
from sns.facebook.listing import issue_notes


def about(platform, invocation):
    options = invocation.options
    if web.is_group_url(options['target']):
        return _group(platform, invocation)
    target = web.normalize_profile(options['target'])
    wanted = options.get('section')
    identity = {'section': wanted}

    def read(connection, state, out):
        client = connection.client
        profile_id = client.resolve('profile', target)
        overview = client.about(profile_id, None, url=target)
        tabs = web.about_collections(overview)
        bodies, names, failed, failure = [overview], [None], [], None

        def fields():
            found, issues = web.about_fields(bodies, profile_id=profile_id, collection_names=names,
                                             captured_at=datetime.now().astimezone())
            return [f for f in found if not wanted or f['section'] == wanted], issues

        for tab in tabs:
            if wanted and fields()[0]:
                break
            try:
                bodies.append(client.about(profile_id, tab['id'], url=target))
                names.append(tab['name'])
            except SnsError as error:
                failed.append({'collection': tab['name'], 'kind': error.kind, 'message': error.message})
                failure = error
                # a login wall, a block, a rate limit or the time limit stops the rest; a tab that merely failed does not
                if reading.stops_continuing(error) or error.reason in ('time_limit', 'rate_limited'):
                    break
        records, issues = fields()
        coverage = [f'collection {f["collection"]} failed — '
                    + ('the section may be there' if wanted else 'its fields are missing') for f in failed]
        if wanted and not records and not failed and not issues:
            coverage.append(f"section {wanted} is not in this profile's visible About")
        result = {'results': records, 'stop_reason': 'exhausted', 'coverage': [*coverage, *issue_notes(issues)]}
        if failed:
            result['details'] = {'failed_sections': failed}
            result['failure'] = failure
        return result

    return reading.run(platform, invocation, command='about', target=target, identity=identity, reader=read)


def _group(platform, invocation):
    """A group's card: its header as the group page shows it to this account."""
    options = invocation.options
    target = web.normalize_group(options['target'])
    if options.get('section'):
        raise SnsError('argument', '--section is for profiles and pages; a group has one card.', 'Drop --section.')

    def read(connection, state, out):
        group_id = connection.client.resolve('group', target)
        record, issues = connection.client.group(group_id, url=target)
        return {'results': [record], 'stop_reason': 'exhausted', 'coverage': issue_notes(issues)}

    return reading.run(platform, invocation, command='about', target=target, identity={'section': None}, reader=read)
