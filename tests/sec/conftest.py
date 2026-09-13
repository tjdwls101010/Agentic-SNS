import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".claude/skills/sec/Scripts"))

import json

import httpx
import pytest

from sec import main


@pytest.fixture
def cli(tmp_path, capsys, monkeypatch):
    identity = tmp_path / "identity.env"
    identity.write_text('EDGAR_IDENTITY="SEC fixture tests tests@example.org"\n')
    calls = []
    replies = []

    def handle(self, request):
        calls.append(request)
        assert request.headers["user-agent"] == "SEC fixture tests tests@example.org"
        assert replies, f"Unexpected request: {request.url}"
        expected, status, body, headers = replies.pop(0)
        assert expected in str(request.url)
        if isinstance(body, Exception):
            raise body
        return (
            httpx.Response(status, json=body, headers=headers)
            if isinstance(body, (dict, list))
            else httpx.Response(status, content=body, headers=headers)
        )

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", handle)

    def run(*args):
        code = main(["--env-file", str(identity), "--cache-dir", str(tmp_path / "cache"), *args, "--json"])
        output = capsys.readouterr().out
        run.last_output = output
        assert "tests@example.org" not in output
        return code, json.loads(output)

    run.calls, run.replies, run.identity, run.cache = calls, replies, identity, tmp_path / "cache"
    return run
