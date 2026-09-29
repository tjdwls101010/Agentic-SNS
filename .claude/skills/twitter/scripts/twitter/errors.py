"""Errors carry actionable recovery without leaking session material."""
import re


def scrub(value):
    if isinstance(value, dict):
        return {k: '[redacted]' if re.search(r'ct0|auth_token|cookie|authorization|csrf|bearer', k, re.I)
                else scrub(v) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v) for v in value]
    if isinstance(value, str):
        value = re.sub(r'https://pbs\.twimg\.com/[^\s"<>]+', lambda m: m[0].split('?')[0], value)
        value = re.sub(r'(?i)(Bearer\s+)\S+', r'\1[redacted]', value)
        return re.sub(r'(?i)((?:ct0|auth_token|cookie|authorization|x-csrf-token)["\s]*[:=]\s*)[^\s;,}]+', r'\1[redacted]', value)
    return value


class TwitterError(Exception):
    def __init__(self, code, message, fix='Run doctor, then follow its recovery advice.', error=None):
        super().__init__(scrub(message))
        self.code, self.message, self.fix = code, scrub(message), scrub(fix)
        self.error = error or {2: 'arguments', 3: 'aside_unavailable', 4: 'session', 5: 'blocked', 6: 'transient', 9: 'unavailable'}.get(code, 'partial')

    def to_dict(self):
        return dict(ok=False, error=self.error, message=self.message, fix=self.fix)
