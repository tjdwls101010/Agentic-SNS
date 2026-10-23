"""Run Facebook's composed page functions in the shared Node snippet harness with the Facebook page model.

The harness loads its page model as page_<model>.mjs beside itself; Facebook's model lives with the Facebook tests
(page_model.mjs, to be reconciled with the other tab platforms' models), so the harness and the model are copied
together into the test's own folder under that name and the shared runner is pointed at that copy.
"""
import shutil
from pathlib import Path

from tests.sns.fakes import snippet_runner as shared

needs_node = shared.needs_node
MODEL = Path(__file__).with_name('page_model.mjs')


def run(tmp_path, calls, page, sources):
    """Run `calls` ({snippet, args, …} — see the harness) against the Facebook page model with `page`'s keys; `sources`
    maps a snippet name to its composed page function text. Returns the harness's one JSON object."""
    folder = tmp_path / 'harness'
    folder.mkdir(exist_ok=True)
    shutil.copy(MODEL, folder / 'page_facebook.mjs')
    (folder / 'snippet_harness.mjs').write_text(with_bodies(shared.HARNESS.read_text()))
    original = shared.HARNESS
    shared.HARNESS = folder / 'snippet_harness.mjs'
    try:
        return shared.run(tmp_path, 'facebook', calls, page, sources)
    finally:
        shared.HARNESS = original


def with_bodies(harness):
    """The shared harness records a fetch's url, method, headers and credentials; Facebook's request is a form POST whose
    fields are the thing to check, so the copy also records the body (nothing else changes)."""
    if 'body: init.body' in harness:
        return harness
    patched = harness.replace('headers: init.headers || {}, credentials:', 'headers: init.headers || {}, body: init.body || null, credentials:')
    assert patched != harness, 'the shared harness no longer records its fetches the way this runner patches'
    return patched
