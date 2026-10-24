"""PDOK clients: Locatieserver (geocoding), OGC API Features (BGT/BAG/BRT) and WFS (BRK).

All geometry comes back in RD New (EPSG:28992) as GeoJSON dicts.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass

import httpx

from layers import CRS_RD, PDOK_BAG, PDOK_BGT, PDOK_BRK_WFS, PDOK_BRT, PDOK_LOCATIESERVER, Collection

log = logging.getLogger("ondergrond.pdok")

OGC_BASE = {"bgt": PDOK_BGT, "bag": PDOK_BAG, "brt": PDOK_BRT}
PAGE_SIZE = 1000
CONCURRENCY = 4
TIMEOUT = httpx.Timeout(30.0, connect=10.0)
HEADERS = {"User-Agent": "OndergrondNL/0.1 (+https://assetlink.nl)"}


class PdokError(RuntimeError):
    pass


def _is_current(feature: dict) -> bool:
    """BGT/BAG OGC APIs also return superseded versions; keep only the current one."""
    p = feature.get("properties") or {}
    return not (p.get("eind_registratie") or p.get("termination_date") or p.get("eindGeldigheid"))


@dataclass
class GeocodeResult:
    id: str
    naam: str
    type: str
    x: float
    y: float


def _parse_point(wkt: str | None) -> tuple[float, float] | None:
    if not wkt:
        return None
    m = re.match(r"POINT\(\s*([-\d.]+)\s+([-\d.]+)\s*\)", wkt)
    return (float(m.group(1)), float(m.group(2))) if m else None


async def geocode(client: httpx.AsyncClient, query: str) -> GeocodeResult:
    """Free-text address → RD point via Locatieserver (suggest + lookup)."""
    r = await client.get(
        f"{PDOK_LOCATIESERVER}/free",
        params={"q": query, "fq": "type:(adres OR postcode OR woonplaats)", "rows": 1,
                "fl": "id,weergavenaam,type,centroide_rd"},
    )
    r.raise_for_status()
    docs = r.json().get("response", {}).get("docs", [])
    if not docs:
        raise PdokError(f"Adres niet gevonden: {query!r}")
    d = docs[0]
    pt = _parse_point(d.get("centroide_rd"))
    if not pt:
        raise PdokError("Locatieserver gaf geen RD-coördinaat terug.")
    return GeocodeResult(d["id"], d["weergavenaam"], d["type"], pt[0], pt[1])


async def available_collections(client: httpx.AsyncClient, api: str) -> set[str]:
    base = OGC_BASE[api]
    r = await client.get(f"{base}/collections", params={"f": "json"})
    r.raise_for_status()
    return {c["id"] for c in r.json().get("collections", [])}


async def fetch_ogc(client: httpx.AsyncClient, api: str, collection: str,
                    bbox: tuple[float, float, float, float]) -> list[dict]:
    """Fetch every feature of one OGC API Features collection inside bbox, following `next` links."""
    base = OGC_BASE[api]
    url = f"{base}/collections/{collection}/items"
    params = {
        "bbox": ",".join(f"{v:.3f}" for v in bbox),
        "bbox-crs": CRS_RD,
        "crs": CRS_RD,
        "f": "json",
        "limit": PAGE_SIZE,
    }
    features: list[dict] = []
    next_url: str | None = url
    next_params: dict | None = params
    pages = 0
    while next_url:
        r = await client.get(next_url, params=next_params)
        if r.status_code != 200:
            raise PdokError(f"PDOK {api}/{collection} gaf {r.status_code}: {r.text[:200]}")
        data = r.json()
        features.extend(f for f in data.get("features", []) if _is_current(f))
        pages += 1
        next_url = None
        next_params = None  # `next` links carry their own query string
        for link in data.get("links", []):
            if link.get("rel") == "next":
                next_url = link["href"]
                break
        if pages > 200:  # hard safety stop (200k features)
            raise PdokError(f"Te veel objecten in {collection}; verklein het gebied.")
    log.info("%s/%s: %d features in %d page(s)", api, collection, len(features), pages)
    return features


async def fetch_wfs(client: httpx.AsyncClient, type_name: str,
                    bbox: tuple[float, float, float, float]) -> list[dict]:
    """Fetch every feature of a BRK WFS type inside bbox, paginating with startIndex."""
    features: list[dict] = []
    start = 0
    while True:
        params = {
            "service": "WFS", "version": "2.0.0", "request": "GetFeature",
            "typeNames": type_name, "outputFormat": "application/json",
            "srsName": "EPSG:28992",
            "bbox": ",".join(f"{v:.3f}" for v in bbox) + ",EPSG:28992",
            "count": PAGE_SIZE, "startIndex": start,
        }
        r = await client.get(PDOK_BRK_WFS, params=params)
        if r.status_code != 200:
            raise PdokError(f"PDOK WFS {type_name} gaf {r.status_code}: {r.text[:200]}")
        page = r.json().get("features", [])
        features.extend(page)
        if len(page) < PAGE_SIZE:
            break
        start += PAGE_SIZE
        if start > 200_000:
            raise PdokError(f"Te veel objecten in {type_name}; verklein het gebied.")
    log.info("brk/%s: %d features", type_name, len(features))
    return features


async def fetch_all(collections: list[Collection], bbox: tuple[float, float, float, float],
                    warnings: list[str]) -> dict[Collection, list[dict]]:
    """Fetch all collections concurrently (limited), skipping ids the API doesn't expose."""
    sem = asyncio.Semaphore(CONCURRENCY)
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS, http2=False) as client:
        known: dict[str, set[str]] = {}
        for api in {c.api for c in collections if c.api in OGC_BASE}:
            try:
                known[api] = await available_collections(client, api)
            except Exception as exc:  # noqa: BLE001
                log.warning("collections list for %s failed: %s", api, exc)
                known[api] = set()

        async def one(c: Collection) -> tuple[Collection, list[dict]]:
            async with sem:
                if c.api != "brk" and known.get(c.api) and c.collection not in known[c.api]:
                    log.info("skip %s/%s: not offered by PDOK", c.api, c.collection)
                    return c, []
                try:
                    if c.api == "brk":
                        return c, await fetch_wfs(client, c.collection, bbox)
                    return c, await fetch_ogc(client, c.api, c.collection, bbox)
                except Exception as exc:  # one failing layer must not kill the whole job
                    log.warning("fetch %s/%s failed: %s", c.api, c.collection, exc)
                    warnings.append(f"Laag {c.dxf_layer} kon niet worden opgehaald bij PDOK en ontbreekt in dit bestand.")
                    return c, []

        results = await asyncio.gather(*(one(c) for c in collections))
    return dict(results)


async def geocode_simple(query: str) -> GeocodeResult:
    async with httpx.AsyncClient(timeout=TIMEOUT, headers=HEADERS) as client:
        return await geocode(client, query)
