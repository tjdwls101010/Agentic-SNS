"""Extract fresh tokens from an already classified homepage; never persist them."""
import json
import re

from _errors import FacebookError


def extract_tokens(html):
    user = re.search(r'"USER_ID"\s*:\s*"(\d+)"', html)
    if not user or user[1] == '0':
        raise FacebookError(4, 'Facebook login is required.', 'Log in to Facebook in Aside, then run doctor.')
    tokens = {'user_id': user[1]}
    for key, pattern in (
        ('fb_dtsg', r'"DTSGInitialData"\s*,\s*\[\]\s*,\s*\{\s*"token"\s*:\s*("(?:\\.|[^"\\])*")'),
        ('lsd', r'"LSD"\s*,\s*\[\]\s*,\s*\{\s*"token"\s*:\s*("(?:\\.|[^"\\])*")'),
        ('__spin_r', r'"__spin_r"\s*:\s*(\d+)'),
    ):
        match = re.search(pattern, html)
        if not match:
            raise FacebookError(6, 'Facebook session tokens are missing.', 'Run doctor after checking Facebook in Aside.')
        try:
            tokens[key] = str(json.loads(match[1])) if key != '__spin_r' else match[1]
            if not tokens[key]:
                raise ValueError
        except ValueError:
            raise FacebookError(6, 'Facebook session tokens are invalid.', 'Check Facebook in Aside, then run doctor.') from None
    tokens['__rev'] = tokens['__spin_r']
    tokens['jazoest'] = '2' + str(sum(map(ord, tokens['fb_dtsg'])))
    return tokens
