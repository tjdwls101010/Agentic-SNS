"""Shared data helpers of the X tests: the synthetic fixtures (fixtures/*.json) and the values the scenarios build on."""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())
