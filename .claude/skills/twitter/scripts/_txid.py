"""Fresh per-request X transaction signatures.

Algorithm ported from **iSarabjitDhiman/XClientTransaction**::

    MIT License. Copyright (c) 2025 Sarabjit Dhiman

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.

"""
import base64
import hashlib
import math
import random
import re
import time
from functools import reduce
from html.parser import HTMLParser
from ._errors import TwitterError
from ._blocked import read_state, write_state, account_lock


def transaction_error(message):
    return TwitterError(6, message, "Run refresh; --tab replies-only is an ungated alternative.", "transaction_unavailable")

_ADDITIONAL_RANDOM_NUMBER = 3
_DEFAULT_KEYWORD = "obfiowerehiring"
_TOTAL_TIME = 4096
#: X's own epoch offset for the timestamp bytes (2023-05-01T07:00:00Z).
_EPOCH_OFFSET_SECONDS = 1682924400

_ON_DEMAND_FILE_URL = "https://abs.twimg.com/responsive-web/client-web/ondemand.s.{filename}a.js"
_ON_DEMAND_FILE_RE = re.compile(r""",(\d+):["']ondemand\.s["']""")
_ON_DEMAND_HASH_PATTERN = r',{}:"([0-9a-f]+)"'
_INDICES_RE = re.compile(r"""(\(\w{1}\[(\d{1,2})\],\s*16\))+""")
_VERIFICATION_RE = re.compile(
    r"""<meta[^>]+name=["']twitter-site-verification["'][^>]+content=["']([^"']+)["']"""
)


class _FrameParser(HTMLParser):
    """Collect, per ``loading-x-anim-N`` element, the ``d`` attributes of the
    element children of its FIRST element child.

    Upstream reaches the same node with
    ``list(list(frame.children)[0].children)[1].get("d")``; this records that
    whole child list so the caller can index it identically.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.frames: dict[int, list[str]] = {}
        self._active: int | None = None
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if self._active is None:
            match = re.fullmatch(r"loading-x-anim-(\d+)", attributes.get("id") or "")
            if match:
                self._active = int(match.group(1))
                self.frames[self._active] = []
                self._depth = 0
            return
        self._depth += 1
        if self._depth == 2:
            self.frames[self._active].append(attributes.get("d") or "")

    def handle_endtag(self, tag: str) -> None:
        if self._active is None:
            return
        if self._depth == 0:
            self._active = None
            return
        self._depth -= 1


def extract_frame_paths(html: str) -> dict[int, list[str]]:
    """Parse the four loading-animation frames out of x.com's HTML."""
    parser = _FrameParser()
    parser.feed(html)
    return parser.frames


# --- maths, verbatim from upstream (see module docstring) --------------------


def _js_round(num: float) -> float:
    """JavaScript's ``Math.round``, which differs from Python's banker's
    rounding on exact .5 -- the generated key is wrong if this is not matched."""
    x = math.floor(num)
    if (num - x) >= 0.5:
        x = math.ceil(num)
    return math.copysign(x, num)


def _is_odd(num: float) -> float:
    return -1.0 if num % 2 else 0.0


def _float_to_hex(x: float) -> str:
    result: list[str] = []
    quotient = int(x)
    fraction = x - quotient
    while quotient > 0:
        quotient = int(x / 16)
        remainder = int(x - (float(quotient) * 16))
        result.insert(0, chr(remainder + 55) if remainder > 9 else str(remainder))
        x = float(quotient)
    if fraction == 0:
        return "".join(result)
    result.append(".")
    while fraction > 0:
        fraction *= 16
        integer = int(fraction)
        fraction -= float(integer)
        result.append(chr(integer + 55) if integer > 9 else str(integer))
    return "".join(result)


def _cubic_value(curves: list[float], t: float) -> float:
    start_gradient = end_gradient = 0.0
    start, mid, end = 0.0, 0.0, 1.0
    if t <= 0.0:
        if curves[0] > 0.0:
            start_gradient = curves[1] / curves[0]
        elif curves[1] == 0.0 and curves[2] > 0.0:
            start_gradient = curves[3] / curves[2]
        return start_gradient * t
    if t >= 1.0:
        if curves[2] < 1.0:
            end_gradient = (curves[3] - 1.0) / (curves[2] - 1.0)
        elif curves[2] == 1.0 and curves[0] < 1.0:
            end_gradient = (curves[1] - 1.0) / (curves[0] - 1.0)
        return 1.0 + end_gradient * (t - 1.0)

    def calculate(a: float, b: float, m: float) -> float:
        return 3.0 * a * (1 - m) * (1 - m) * m + 3.0 * b * (1 - m) * m * m + m * m * m

    while start < end:
        mid = (start + end) / 2
        x_estimate = calculate(curves[0], curves[2], mid)
        if abs(t - x_estimate) < 0.00001:
            return calculate(curves[1], curves[3], mid)
        if x_estimate < t:
            start = mid
        else:
            end = mid
    return calculate(curves[1], curves[3], mid)


def _interpolate(from_list: list[float], to_list: list[float], f: float) -> list[float]:
    return [a * (1 - f) + b * f for a, b in zip(from_list, to_list, strict=True)]


def _rotation_matrix(rotation: float) -> list[float]:
    rad = math.radians(rotation)
    return [math.cos(rad), -math.sin(rad), math.sin(rad), math.cos(rad)]


def _solve(value: float, min_val: float, max_val: float, rounding: bool) -> float:
    result = value * (max_val - min_val) / 255 + min_val
    return math.floor(result) if rounding else round(result, 2)


def _animate(frame_row: list[int], target_time: float) -> str:
    from_color = [float(item) for item in [*frame_row[:3], 1]]
    to_color = [float(item) for item in [*frame_row[3:6], 1]]
    to_rotation = [_solve(float(frame_row[6]), 60.0, 360.0, True)]
    curves = [
        _solve(float(item), _is_odd(counter), 1.0, False)
        for counter, item in enumerate(frame_row[7:])
    ]
    value = _cubic_value(curves, target_time)
    color = [max(0, min(255, item)) for item in _interpolate(from_color, to_color, value)]
    rotation = _interpolate([0.0], to_rotation, value)
    matrix = _rotation_matrix(rotation[0])

    parts = [format(round(item), "x") for item in color[:-1]]
    for item in matrix:
        rounded = abs(round(item, 2))
        hex_value = _float_to_hex(rounded)
        if hex_value.startswith("."):
            parts.append(f"0{hex_value}".lower())
        else:
            parts.append(hex_value or "0")
    parts.extend(["0", "0"])
    return re.sub(r"[.-]", "", "".join(parts))


def compute_animation_key(
    key_bytes: list[int], frames: dict[int, list[str]], row_index_key: int, byte_indices: list[int]
) -> str:
    """Derive the animation key from the page's four SVG frames.

    Split out from :class:`ClientTransaction` so it can be unit-tested against a
    synthetic page without any network.
    """
    frame_paths = frames.get(key_bytes[5] % 4) or []
    if len(frame_paths) < 2:
        raise transaction_error(
            f"loading-x-anim frame {key_bytes[5] % 4} has {len(frame_paths)} paths, expected >= 2"
        )
    rows = [
        [int(number) for number in re.sub(r"[^\d]+", " ", segment).strip().split()]
        for segment in frame_paths[1][9:].split("C")
    ]
    row_index = key_bytes[row_index_key] % 16
    frame_time = reduce(lambda a, b: a * b, [key_bytes[i] % 16 for i in byte_indices])
    frame_time = _js_round(frame_time / 10) * 10
    return _animate(rows[row_index], float(frame_time) / _TOTAL_TIME)


def ondemand_url(html):
    chunk = _ON_DEMAND_FILE_RE.search(html)
    match = re.search(_ON_DEMAND_HASH_PATTERN.format(chunk[1]), html) if chunk else None
    if not match:
        raise transaction_error('Missing ondemand.s chunk reference or hash.')
    return _ON_DEMAND_FILE_URL.format(filename=match[1])


def derive(html, ondemand, url=None):
    verification = _VERIFICATION_RE.search(html)
    if not verification:
        raise transaction_error('Missing twitter-site-verification meta tag.')
    try:
        key = list(base64.b64decode(verification[1], validate=True))
        indices = [int(match[2]) for match in _INDICES_RE.finditer(ondemand)]
        if len(indices) < 2:
            raise transaction_error('Missing ondemand key-byte indices.')
        frames = extract_frame_paths(html)
        if len(frames) != 4:
            raise transaction_error('Missing loading-x-anim SVG frames.')
        animation = compute_animation_key(key, frames, indices[0], indices[1:])
    except (ValueError, IndexError, TypeError) as error:
        raise transaction_error('Invalid verification/SVG/index ingredients: ' + str(error)) from None
    return dict(key_bytes=key, animation_key=animation, indices=indices, fetched_at=time.time(), ondemand_url=url)


def load_material(transport, force=False):
    material = read_state('txid.json')
    if not force and material.get('animation_key') and time.time() - material.get('fetched_at', 0) < 86400:
        return material
    html = transport.auxiliary('page', {'url': 'https://x.com/'})['body']
    url = ondemand_url(html)
    ondemand = transport.auxiliary('page', {'url': url})['body']
    material = derive(html, ondemand, url)
    with account_lock():
        write_state('txid.json', material)
    return material


def generate(method, path, *, material=None, now=None, rng=None):
    material = material or read_state('txid.json')
    if not material.get('key_bytes') or not material.get('animation_key'):
        raise transaction_error('Missing cached transaction ingredients.')
    time_now = math.floor((time.time() if now is None else now) - _EPOCH_OFFSET_SECONDS)
    time_bytes = [(time_now >> (i * 8)) & 0xFF for i in range(4)]
    digest = hashlib.sha256(f'{method}!{path}!{time_now}{_DEFAULT_KEYWORD}{material["animation_key"]}'.encode()).digest()
    payload = [*material['key_bytes'], *time_bytes, *list(digest)[:16], _ADDITIONAL_RANDOM_NUMBER]
    noise = (rng or random.randint)(0, 255)
    return base64.b64encode(bytearray([noise, *[item ^ noise for item in payload]])).decode().strip('=')
