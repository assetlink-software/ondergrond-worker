"""Ondergrond NL worker — FastAPI service that turns address/coordinate + area into a DXF.

POST /generate
  {
    "adres": "Stadhuisplein 2, Lelystad"      (or "x": 161234.5, "y": 500118.1)
    "straal_m": 100                            (or "polygon": [[x,y], ...])
    "lagen": ["bgt_basis", "bag_pand", "brk_perceel"],
    "opties": {"text_height": 1.0, "include_frame": true, "clip_mode": "hard", "hatch": true}
  }
  → { "job_id", "url", "bestand", "objecten", "lagen": {...}, "waarschuwingen": [...], "duur_ms" }

GET /dxf/{name}?q=<token>    → the DXF, rebuilt on request (stateless, works on any instance)
GET /geocode?q=...           → Locatieserver proxy
GET /health
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import zlib
import logging
import os
import time
import uuid
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field

from dxfgen import Options, build_dxf, circle_area, polygon_area
from layers import BGT_MAX_RADIUS_M, LAYER_GROUPS, MAX_AREA_KM2, default_group_ids
from pdok import PdokError, fetch_all, geocode_simple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("ondergrond")

FILES_DIR = Path(os.environ.get("FILES_DIR", "/tmp/ondergrond-files"))
FILE_TTL_HOURS = float(os.environ.get("FILE_TTL_HOURS", "24"))
PUBLIC_BASE = os.environ.get("PUBLIC_BASE", "")          # e.g. https://worker.ondergrond.nl
RATE_LIMIT_PER_HOUR = int(os.environ.get("RATE_LIMIT_PER_HOUR", "30"))
MAX_RADIUS_M = float(os.environ.get("MAX_RADIUS_M", "2000"))

FILES_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Ondergrond NL worker", version="0.1.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_rate: dict[str, list[float]] = {}


def _check_rate(ip: str) -> None:
    now = time.time()
    hits = [t for t in _rate.get(ip, []) if now - t < 3600]
    if len(hits) >= RATE_LIMIT_PER_HOUR:
        raise HTTPException(429, "Te veel aanvragen vanaf dit adres. Probeer het over een uur opnieuw.")
    hits.append(now)
    _rate[ip] = hits


def _cleanup_old_files() -> None:
    cutoff = time.time() - FILE_TTL_HOURS * 3600
    for job_dir in FILES_DIR.iterdir():
        try:
            if job_dir.is_dir() and job_dir.stat().st_mtime < cutoff:
                for f in job_dir.iterdir():
                    f.unlink()
                job_dir.rmdir()
        except OSError:
            pass


class Opties(BaseModel):
    text_height: float = Field(1.0, gt=0, le=20)
    include_frame: bool = True
    clip_mode: str = Field("hard", pattern="^(hard|whole)$")
    hatch: bool = True


class GenerateRequest(BaseModel):
    adres: str | None = None
    x: float | None = None
    y: float | None = None
    straal_m: float | None = Field(None, gt=0)
    polygon: list[list[float]] | None = None
    lagen: list[str] = Field(default_factory=default_group_ids)
    opties: Opties = Opties()


@app.get("/health")
async def health():
    return {"ok": True, "lagen": list(LAYER_GROUPS)}


@app.get("/lagen")
async def lagen():
    return [{"id": g.id, "label": g.label, "default": g.default_on,
             "max_radius_m": g.max_radius_m} for g in LAYER_GROUPS.values()]


@app.get("/geocode")
async def geocode(q: str):
    try:
        r = await geocode_simple(q)
    except PdokError as exc:
        raise HTTPException(404, str(exc)) from exc
    return {"id": r.id, "naam": r.naam, "type": r.type, "x": r.x, "y": r.y}


class _Built:
    def __init__(self, doc, result, area, cx, cy, naam, name):
        self.doc, self.result, self.area, self.cx, self.cy, self.naam, self.name = doc, result, area, cx, cy, naam, name


async def _build(req: GenerateRequest) -> _Built:
    """Geocode → area → layer groups → fetch PDOK → clip + write. Stateless: nothing is stored."""
    warnings: list[str] = []
    if req.adres:
        try:
            g = await geocode_simple(req.adres)
        except PdokError as exc:
            raise HTTPException(404, str(exc)) from exc
        cx, cy, naam = g.x, g.y, g.naam
    elif req.x is not None and req.y is not None:
        cx, cy, naam = req.x, req.y, f"{req.x:.2f}, {req.y:.2f}"
    else:
        raise HTTPException(400, "Geef een adres of een x/y-coördinaat (RD) op.")

    if req.polygon and len(req.polygon) >= 3:
        area = polygon_area(req.polygon)
    else:
        radius = req.straal_m or 100.0
        if radius > MAX_RADIUS_M:
            raise HTTPException(400, f"Straal maximaal {MAX_RADIUS_M:g} m.")
        area = circle_area(cx, cy, radius)
    if area.area_km2 > MAX_AREA_KM2:
        raise HTTPException(400, f"Gebied maximaal {MAX_AREA_KM2:g} km² (nu {area.area_km2:.2f} km²).")

    groups = []
    for gid in req.lagen:
        grp = LAYER_GROUPS.get(gid)
        if not grp:
            warnings.append(f"Onbekende laag '{gid}' overgeslagen.")
            continue
        too_big = grp.max_radius_m and (
            (area.radius_m and area.radius_m > grp.max_radius_m) or area.area_km2 > 0.8)
        if too_big:
            warnings.append(f"{grp.label} is te gedetailleerd voor dit gebied; BRT overzicht gebruikt.")
            grp = LAYER_GROUPS["brt_overzicht"]
        if grp not in groups:
            groups.append(grp)
    collections = [c for g in groups for c in g.collections]
    if not collections:
        raise HTTPException(400, "Kies minstens één laag.")

    try:
        feats = await fetch_all(collections, area.bbox, warnings)
    except PdokError as exc:
        raise HTTPException(502, str(exc)) from exc
    opt = Options(text_height=req.opties.text_height, include_frame=req.opties.include_frame,
                  clip_mode=req.opties.clip_mode, hatch=req.opties.hatch)
    doc, result = await asyncio.to_thread(build_dxf, feats, area, opt, warnings)
    rad = f"{area.radius_m:g}m" if area.radius_m else "polygoon"
    name = f"ondergrond_{int(cx)}_{int(cy)}_{rad}.dxf"
    return _Built(doc, result, area, cx, cy, naam, name)


def _dxf_bytes(doc) -> bytes:
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")


def _encode_req(req: GenerateRequest, cx: float, cy: float) -> str:
    """Compact, URL-safe token that holds the whole request (address already resolved to x/y)."""
    data = {
        "x": round(cx, 2), "y": round(cy, 2),
        "r": req.straal_m,
        "p": [[round(a, 2), round(b, 2)] for a, b in req.polygon] if req.polygon else None,
        "l": req.lagen,
        "o": req.opties.model_dump(),
    }
    raw = zlib.compress(json.dumps(data, separators=(",", ":")).encode(), 9)
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _decode_req(token: str) -> GenerateRequest:
    try:
        raw = zlib.decompress(base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)))
        d = json.loads(raw)
        return GenerateRequest(x=d["x"], y=d["y"], straal_m=d.get("r"), polygon=d.get("p"),
                               lagen=d["l"], opties=Opties(**d.get("o", {})))
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, "Ongeldige downloadlink.") from exc


def _public_base(request: Request) -> str:
    base = PUBLIC_BASE or str(request.base_url).rstrip("/")
    if base.startswith("http://") and not any(h in base for h in ("localhost", "127.0.0.1")):
        base = "https://" + base[len("http://"):]   # Cloud Run terminates TLS in front of us
    return base


@app.post("/generate")
async def generate(req: GenerateRequest, request: Request):
    t0 = time.perf_counter()
    _check_rate(request.client.host if request.client else "?")
    b = await _build(req)
    size = len(await asyncio.to_thread(_dxf_bytes, b.doc))
    duur = int((time.perf_counter() - t0) * 1000)
    token = _encode_req(req, b.cx, b.cy)
    log.info("generate %s: %s objects, %d layers, %d bytes, %d ms", b.name, b.result.objects, len(b.result.counts), size, duur)
    return {
        "job_id": token[:12],
        # stateless link: the file is rebuilt on download, so it works on every Cloud Run instance and never expires
        "url": f"{_public_base(request)}/dxf/{b.name}?q={token}",
        "bestand": b.name,
        "bytes": size,
        "locatie": b.naam,
        "middelpunt": {"x": b.cx, "y": b.cy},
        "gebied": b.area.label,
        "km2": round(b.area.area_km2, 4),
        "objecten": b.result.objects,
        "lagen": dict(b.result.counts.most_common()),
        "waarschuwingen": b.result.warnings,
        "duur_ms": duur,
    }


@app.get("/dxf/{name}")
async def dxf(name: str, q: str, request: Request):
    _check_rate(request.client.host if request.client else "?")
    req = _decode_req(q)
    b = await _build(req)
    data = await asyncio.to_thread(_dxf_bytes, b.doc)
    return Response(content=data, media_type="application/dxf",
                    headers={"Content-Disposition": f'attachment; filename="{b.name}"', "Cache-Control": "public, max-age=600"})


@app.get("/files/{job_id}/{name}")
async def files_legacy(job_id: str, name: str):
    raise HTTPException(410, "Deze downloadlink is verlopen. Genereer het bestand opnieuw.")


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error")
    return JSONResponse(status_code=500, content={"detail": "Er ging iets mis bij het genereren.", "technisch": f"{type(exc).__name__}: {exc}"})
