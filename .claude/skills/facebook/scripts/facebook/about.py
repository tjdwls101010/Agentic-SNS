"""about: the visible About fields of a profile or page, read tab by tab."""
from datetime import datetime

from facebook import connect, graphql
from facebook.errors import FacebookError


def about(options):
    target = graphql.normalize_profile(options['target'])
    wanted = options.get('section')
    identity = {'section': wanted}

    def read(connection, state, out):
        client = connection.client
        profile_id = client.resolve('profile', target)
        before = connection.guard.used
        overview = client.about(profile_id, None, url=target)
        tabs = graphql.about_collections(overview)
        bodies, names, failed, failure = [overview], [None], [], None

        def fields():
            found, issues = graphql.about_fields(bodies, profile_id=profile_id, collection_names=names,
                                                 captured_at=datetime.now().astimezone())
            return [f for f in found if not wanted or f['section'] == wanted], issues

        for tab in tabs:
            if wanted and fields()[0]:
                break
            try:
                bodies.append(client.about(profile_id, tab['id'], url=target))
                names.append(tab['name'])
            except FacebookError as error:
                failed.append({'collection': tab['name'], 'code': error.code, 'message': error.message})
                failure = error
                if error.code in (4, 5, 8):
                    break
        records, issues = fields()
        coverage = [f'collection {f["collection"]} failed — '
                    + ('the section may be there' if wanted else 'its fields are missing') for f in failed]
        if wanted and not records and not failed and not issues:
            coverage.append(f"section {wanted} is not in this profile's visible About")
        reading = {'results': records, 'stop_reason': 'exhausted', 'issues': issues, 'coverage': coverage}
        if failed:
            reading['details'] = {'failed_sections': failed}
            reading['failure'] = failure
            if failure.code == 8:
                needed = before + 1 + len(tabs)
                reading['failure'] = FacebookError(
                    8, f'The request budget ran out after {len(bodies) - 1} of {len(tabs)} About tabs; this profile '
                       f'needs {"up to " if wanted else ""}{needed} requests.', 'Rerun with a larger --max-requests.')
        return reading

    return connect.run(options, command='about', target=target, identity=identity, reader=read)
