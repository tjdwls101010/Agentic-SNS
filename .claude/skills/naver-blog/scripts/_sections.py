"""A composite command answers in sections, and a failed section is still an answer.

Reading a blog is four requests. If the notice list fails, the card, the categories and
the popular posts are still what was asked for, and throwing them away to report one
failure would make the command less useful exactly when Naver is least reliable.
"""
from ._errors import NaverBlogError

# Which failure a caller most needs to know about when several sections failed at once.
PRIORITY = {4: 5, 5: 4, 9: 3, 6: 2, 8: 1, 2: 1, 3: 5, 7: 0}


class Sections:
    def __init__(self):
        self.entries = []
        self.warnings = []

    def add(self, name, produce, *, primary=False, prefix='s'):
        """Run one section. A primary section's failure is the command's failure."""
        try:
            data = produce()
        except NaverBlogError as error:
            self.entries.append({'name': name, 'ok': False, 'primary': primary, 'prefix': prefix,
                                 'error': {'code': error.code, 'error': error.error,
                                           'message': error.message, 'fix': error.fix}})
            if primary:
                raise
            return None
        self.entries.append({'name': name, 'ok': True, 'primary': primary, 'prefix': prefix, 'data': data})
        return data

    def exit_code(self):
        """0 when every section answered; otherwise the most serious failure, as partial."""
        failures = [entry['error']['code'] for entry in self.entries if not entry['ok']]
        if not failures:
            return 0
        worst = max(failures, key=lambda code: PRIORITY.get(code, 1))
        # A blocked or logged-out account is not "partial"; the next command will fail too.
        return worst if worst in (4, 5) else 8

    def as_list(self):
        return [{key: value for key, value in entry.items() if key != 'primary'} for entry in self.entries]
