"""The SEC originals the filing tests read are the exact bytes SEC served: each file's sha256, after its gzip storage is undone, matches provenance.json."""
import gzip
import hashlib
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
MANIFESTS = [FIXTURES / "documents" / "provenance.json", FIXTURES / "holdout" / "provenance.json"]
ENTRIES = [(m, name) for m in MANIFESTS for name in json.loads(m.read_text()) if not name.startswith("_")]


@pytest.mark.parametrize("manifest,name", ENTRIES, ids=[f"{m.parent.name}/{n}" for m, n in ENTRIES])
def test_an_original_is_the_bytes_its_provenance_names(manifest, name):
    meta = json.loads(manifest.read_text())[name]
    stored = manifest.parent / meta.get("storage", name)
    raw = stored.read_bytes()
    if meta.get("compression") == "gzip":
        assert hashlib.sha256(raw).hexdigest() == meta["stored_sha256"]
        raw = gzip.decompress(raw)
    assert hashlib.sha256(raw).hexdigest() == meta["sha256"]
    assert meta["url"].startswith("https://www.sec.gov/Archives/edgar/data/")


def test_the_expected_map_names_only_documents_that_exist():
    expected = json.loads((FIXTURES / "documents" / "expected-map.json").read_text())
    provenance = json.loads(MANIFESTS[0].read_text())
    assert set(expected["contents"]) <= set(provenance) and set(expected["elements"]) <= set(provenance)
