"""Shared data helpers of the Threads tests: the synthetic fixtures (fixtures/*.json)."""
import json
from pathlib import Path

FIXTURES = Path(__file__).resolve().parent / 'fixtures'


def fixture(name):
    return json.loads((FIXTURES / name).read_text())
