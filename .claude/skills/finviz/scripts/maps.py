"""Resolve Finviz map data literals from the current page's own assets."""

import re
from urllib.parse import urlencode, urljoin
from uuid import uuid4

from bs4 import BeautifulSoup
import json5

from runtime import Failure, fetch


# Public map identifiers select the loader's named enum cases, never chunk IDs or hashes.
TYPES = {
    "sec": "Sector",
    "geo": "World",
    "sec_all": "SectorFull",
    "cap": "MarketCap",
    "etf": "ETF",
    "crypto": "CryptoUSD",
    "crypto_usdt": "CryptoUSDT",
    "crypto_eur": "CryptoEUR",
    "crypto_btc": "CryptoBTC",
    "futures": "Futures",
    "sec_dji": "Dow",
    "sec_rut": "Russell",
    "sec_ndx": "Nasdaq",
    "sec_ixic": "NasdaqComposite",
    "themes": "Themes",
}


def literal_at(source, start):
    value, error, _ = json5.parse(source, start=start, consume_trailing=False, allow_duplicate_keys=False)
    if error:
        raise Failure("asset_structure", error, "Inspect the saved asset; classification was not guessed.")
    return value


def enrich(performance, args, store):
    if performance["status"] == "error":
        return performance
    result = dict(
        performance,
        id=uuid4().hex,
        data={"performance": performance["data"], "classification": None},
        dependencies=[performance["id"]],
        errors=list(performance["errors"]),
    )

    def source(url):
        def retain(response, raw):
            response["data"] = {"asset_text": raw.decode("utf-8", errors="replace")}

        response = fetch(url, args, store, retain)
        result["dependencies"].append(response["id"])
        if response["status"] == "error":
            raise Failure(
                "map_source_failed",
                "Map dependency failed: " + url,
                "Inspect dependency observation " + response["id"] + " and its recovery instructions.",
            )
        return response, response["data"]["asset_text"]

    try:
        enum = TYPES.get(args.type)
        if enum is None:
            raise Failure(
                "unknown_map_type",
                "No verified loader case for " + args.type,
                "Use catalog map or --performance-only; classification is unavailable for this type.",
            )
        _, html = source("https://finviz.com/map?" + urlencode({"t": args.type}))
        soup = BeautifulSoup(html, "html.parser")
        assets = list(dict.fromkeys(urljoin("https://finviz.com", s["src"]) for s in soup.select("script[src]")))
        entry = next((i for i, a in enumerate(assets) if "/map.v" in a), None)
        runtime = next((a for a in assets if "/runtime.v" in a), None)
        if entry is None or runtime is None:
            raise Failure(
                "asset_structure",
                "Map entry or runtime manifest is missing.",
                "Inspect the saved map page; classification remains unknown.",
            )
        chunk = None
        # 성진: inspect at most ten preceding numeric bundles; revisit if Finviz moves its loader outside this page-local window.
        candidates = [a for a in assets[:entry] if re.search(r"/\d+\.v", a)][-10:]
        for url in reversed(candidates):
            _, loader = source(url)
            if "SectorFull" not in loader and "IZ.World" not in loader:
                continue
            pattern = r"case\s+[\w$.]+\." + enum + r":return[^;]{0,150}?\.e\((\d+)\)"
            match = re.search(pattern, loader)
            if enum == "Sector":
                start = loader.find("case ")
                # The default within the same map-universe switch selects Sector.
                switch = re.search(
                    r"case\s+[\w$.]+\.World:[\s\S]*?default:return[^;]{0,150}?\.e\((\d+)\)", loader[start:]
                )
                match = switch
            if match:
                chunk = match.group(1)
                break
        if chunk is None:
            raise Failure(
                "asset_structure",
                "The selected map case was not found in the current loader.",
                "Inspect saved assets; no other map universe was substituted.",
            )
        _, manifest = source(runtime)
        mappings = re.finditer(r'"\.v1\."\s*\+\s*(\{[^{}]+\})', manifest)
        hashes = [
            json5.loads(re.sub(r"([,{])\s*(\d+)\s*:", r'\1"\2":', m.group(1)), allow_duplicate_keys=False)
            for m in mappings
        ]
        digest = next((mapping[chunk] for mapping in hashes if chunk in mapping), None)
        if not isinstance(digest, str) or not re.fullmatch(r"[\w-]+", digest):
            raise Failure(
                "asset_structure",
                "Selected chunk is missing from the current runtime hash map.",
                "Inspect the saved runtime manifest.",
            )
        url = runtime.rsplit("/", 1)[0] + "/" + chunk + ".v1." + digest + ".js"
        asset, payload = source(url)
        objects = []
        for match in re.finditer(r"\.exports\s*=\s*(\{)", payload):
            obj = literal_at(payload, match.start(1))
            if isinstance(obj, dict) and obj.get("name") == "Root" and isinstance(obj.get("children"), list):
                objects.append(obj)
        if len(objects) != 1:
            raise Failure(
                "asset_structure",
                "Expected one Root classification object for the selected type.",
                "Inspect the saved asset; ambiguous objects are not substituted.",
            )
        result["data"].update(classification=objects[0], classification_source=asset["source"])
    except (Failure, ValueError, TypeError) as exc:
        result["status"] = "partial"
        result["errors"].append(
            exc.detail
            if isinstance(exc, Failure)
            else dict(
                code="asset_structure",
                message=str(exc),
                fix="Inspect dependency observations; classification remains unknown.",
            )
        )
    store.save(result, store.get(performance["id"], raw=True))
    return result
