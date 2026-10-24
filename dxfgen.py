"""Clip PDOK features to an area and write a clean, CAD-ready DXF (R2018, meters, RD New)."""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

import ezdxf
from ezdxf import units as dxf_units
from shapely.geometry import (GeometryCollection, LineString, MultiLineString, MultiPoint,
                              MultiPolygon, Point, Polygon, shape)
from shapely.ops import unary_union
from shapely.validation import make_valid

from layers import (BLOCK_PUNT, FRAME_LAYER_NOORD, FRAME_LAYER_RAND, FRAME_LAYER_TEKST,
                    Collection, subtype_suffix)

log = logging.getLogger("ondergrond.dxf")


@dataclass
class Area:
    """The selection in RD meters."""
    polygon: Polygon
    center: tuple[float, float]
    radius_m: float | None = None     # set for circles
    label: str = ""                    # "straal 100 m" / "rechthoek 180 × 120 m" / "polygoon"

    @property
    def bbox(self) -> tuple[float, float, float, float]:
        return self.polygon.bounds

    @property
    def area_km2(self) -> float:
        return self.polygon.area / 1_000_000


def circle_area(cx: float, cy: float, radius_m: float, steps: int = 64) -> Area:
    pts = [(cx + radius_m * math.cos(2 * math.pi * i / steps),
            cy + radius_m * math.sin(2 * math.pi * i / steps)) for i in range(steps)]
    return Area(Polygon(pts), (cx, cy), radius_m, f"straal {radius_m:g} m")


def polygon_area(coords: list[list[float]], label: str = "polygoon") -> Area:
    poly = make_valid(Polygon(coords))
    if poly.geom_type == "MultiPolygon":
        poly = max(poly.geoms, key=lambda p: p.area)
    c = poly.centroid
    return Area(poly, (c.x, c.y), None, label)


@dataclass
class Options:
    text_height: float = 1.0
    include_frame: bool = True
    clip_mode: str = "hard"          # "hard" | "whole"
    hatch: bool = True
    author: str = "AssetLink · assetlink-ondergrond.com"


@dataclass
class Result:
    counts: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)
    objects: int = 0


# ---------------------------------------------------------------- geometry helpers

def _clean(geom):
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = make_valid(geom)
    return None if geom.is_empty else geom


def _clip(geom, area: Area, mode: str):
    """Clip geometry to the area. Returns None when nothing is left."""
    geom = _clean(geom)
    if geom is None or not geom.intersects(area.polygon):
        return None
    if mode == "whole":
        return geom
    out = geom.intersection(area.polygon)
    out = _clean(out)
    if out is None:
        return None
    # drop slivers thinner than 1 mm²
    if out.geom_type in ("Polygon", "MultiPolygon") and out.area < 1e-6:
        return None
    return out


def _iter_polygons(geom):
    if isinstance(geom, Polygon):
        yield geom
    elif isinstance(geom, MultiPolygon):
        yield from geom.geoms
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms:
            yield from _iter_polygons(g)


def _iter_lines(geom):
    if isinstance(geom, LineString):
        yield geom
    elif isinstance(geom, MultiLineString):
        yield from geom.geoms
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms:
            yield from _iter_lines(g)


def _iter_points(geom):
    if isinstance(geom, Point):
        yield geom
    elif isinstance(geom, MultiPoint):
        yield from geom.geoms
    elif isinstance(geom, GeometryCollection):
        for g in geom.geoms:
            yield from _iter_points(g)


def _ring_coords(ring) -> list[tuple[float, float]]:
    pts = [(round(x, 3), round(y, 3)) for x, y in ring.coords]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    return pts


# ---------------------------------------------------------------- DXF document

def new_doc() -> ezdxf.document.Drawing:
    doc = ezdxf.new("R2018", setup=True)   # setup=True loads standard linetypes (DASHED etc.)
    doc.units = dxf_units.M
    doc.header["$INSUNITS"] = 6
    doc.header["$MEASUREMENT"] = 1
    doc.header["$LTSCALE"] = 1.0
    doc.header["$PDMODE"] = 35
    doc.header["$PDSIZE"] = 0.3
    # point block: small circle Ø 0.3 m with a cross
    blk = doc.blocks.new(BLOCK_PUNT)
    blk.add_circle((0, 0), 0.15)
    blk.add_line((-0.2, 0), (0.2, 0))
    blk.add_line((0, -0.2), (0, 0.2))
    doc.styles.new("ONDERGROND", dxfattribs={"font": "isocp.shx"})
    return doc


def _layer(doc, name: str, color: int, linetype: str = "CONTINUOUS"):
    if name not in doc.layers:
        doc.layers.add(name, color=color, linetype=linetype)
    return name


def _label_text(props: dict, attr: str) -> str | None:
    v = props.get(attr)
    if v is None or v == "":
        return None
    text = str(v)
    # BAG: huisnummer + huisletter + toevoeging
    if attr == "huisnummer":
        text += str(props.get("huisletter") or "")
        toev = props.get("toevoeging") or props.get("huisnummertoevoeging")
        if toev:
            text += f"-{toev}"
    return text


def write_collection(doc, msp, col: Collection, features: list[dict], area: Area,
                     opt: Options, result: Result) -> None:
    for f in features:
        props = f.get("properties") or {}
        try:
            geom = shape(f["geometry"]) if f.get("geometry") else None
        except Exception:  # noqa: BLE001
            continue
        geom = _clip(geom, area, opt.clip_mode)
        if geom is None:
            continue

        suffix = subtype_suffix(props.get(col.subtype_attr)) if col.subtype_attr else None
        layer_name = f"{col.dxf_layer}_{suffix}" if suffix else col.dxf_layer
        layer = _layer(doc, layer_name, col.color, col.linetype)
        attribs = {"layer": layer}
        wrote = 0

        if col.kind == "polygon":
            for poly in _iter_polygons(geom):
                ext = _ring_coords(poly.exterior)
                if len(ext) < 3:
                    continue
                msp.add_lwpolyline(ext, close=True, dxfattribs=attribs)
                for hole in poly.interiors:
                    pts = _ring_coords(hole)
                    if len(pts) >= 3:
                        msp.add_lwpolyline(pts, close=True, dxfattribs=attribs)
                if opt.hatch and col.hatch:
                    hl = _layer(doc, f"{layer_name}_Arcering", col.color)
                    h = msp.add_hatch(color=col.color, dxfattribs={"layer": hl})
                    h.set_pattern_fill(col.hatch, scale=0.5, angle=0)
                    h.paths.add_polyline_path(ext, is_closed=True)
                    for hole in poly.interiors:
                        pts = _ring_coords(hole)
                        if len(pts) >= 3:
                            h.paths.add_polyline_path(pts, is_closed=True)
                wrote += 1
            if col.label_attr and wrote:
                self_label(doc, msp, col, props, geom, opt)

        elif col.kind == "line":
            for line in _iter_lines(geom):
                pts = [(round(x, 3), round(y, 3)) for x, y in line.coords]
                if len(pts) >= 2:
                    msp.add_lwpolyline(pts, dxfattribs=attribs)
                    wrote += 1

        elif col.kind == "point":
            for pt in _iter_points(geom):
                if col.label_attr:
                    text = _label_text(props, col.label_attr)
                    if text:
                        msp.add_text(text, height=opt.text_height,
                                     dxfattribs={"layer": layer, "style": "ONDERGROND"}
                                     ).set_placement((pt.x, pt.y), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)
                        wrote += 1
                else:
                    msp.add_blockref(BLOCK_PUNT, (pt.x, pt.y), dxfattribs=attribs)
                    wrote += 1

        if wrote:
            result.counts[layer_name] += wrote
            result.objects += wrote


def self_label(doc, msp, col: Collection, props: dict, geom, opt: Options) -> None:
    """Perceelnummer at the Kadaster's own label position/rotation, else at the centroid."""
    text = _label_text(props, col.label_attr)
    if not text:
        return
    lx = props.get("perceelnummerPlaatscoordinaatX")
    ly = props.get("perceelnummerPlaatscoordinaatY")
    rot = float(props.get("perceelnummerRotatie") or 0)
    if lx is None or ly is None:
        c = geom.representative_point()
        lx, ly = c.x, c.y
    # keep the label only if it falls inside the clipped piece (or hard clip is off)
    if opt.clip_mode == "hard" and not geom.buffer(0.5).contains(Point(lx, ly)):
        return
    layer = _layer(doc, f"{col.dxf_layer}nummer", col.color)
    msp.add_text(text, height=opt.text_height, rotation=rot,
                 dxfattribs={"layer": layer, "style": "ONDERGROND"}
                 ).set_placement((float(lx), float(ly)), align=ezdxf.enums.TextEntityAlignment.MIDDLE_CENTER)


def write_frame(doc, msp, area: Area, opt: Options, counts: Counter) -> None:
    rand = _layer(doc, *FRAME_LAYER_RAND)
    tekst = _layer(doc, *FRAME_LAYER_TEKST)
    noord = _layer(doc, *FRAME_LAYER_NOORD)
    # boundary
    msp.add_lwpolyline(_ring_coords(area.polygon.exterior), close=True,
                       dxfattribs={"layer": rand, "lineweight": 35})
    minx, miny, maxx, maxy = area.bbox
    w = maxx - minx
    h = maxy - miny
    th = max(opt.text_height, w / 120)        # scale text to the drawing
    # title block, lower-left outside the boundary
    bx, by = minx, miny - 2 * th
    lines = [
        f"ONDERGROND NL  ·  {opt.author}",
        "Bron: PDOK (BGT/BAG/BRK), Kadaster en bronhouders — data zoals gepubliceerd",
        "Stelsel: RD New (EPSG:28992)  ·  eenheid: meter",
        f"Middelpunt: X {area.center[0]:,.2f}  Y {area.center[1]:,.2f}".replace(",", "."),
        f"Gebied: {area.label}  ·  {area.area_km2:.3f} km²",
        f"Gegenereerd: {datetime.now():%d-%m-%Y %H:%M}  ·  {sum(counts.values())} objecten, {len(counts)} lagen",
    ]
    for i, line in enumerate(lines):
        msp.add_text(line, height=th * (1.3 if i == 0 else 1.0),
                     dxfattribs={"layer": tekst, "style": "ONDERGROND"}
                     ).set_placement((bx, by - i * th * 1.8), align=ezdxf.enums.TextEntityAlignment.TOP_LEFT)
    # north arrow, upper-right outside the boundary
    nx, ny = maxx + 3 * th, maxy
    L = 8 * th
    msp.add_line((nx, ny - L), (nx, ny), dxfattribs={"layer": noord})
    msp.add_lwpolyline([(nx - 0.15 * L, ny - 0.3 * L), (nx, ny), (nx + 0.15 * L, ny - 0.3 * L)],
                       dxfattribs={"layer": noord})
    msp.add_text("N", height=th * 1.5, dxfattribs={"layer": noord, "style": "ONDERGROND"}
                 ).set_placement((nx, ny + th), align=ezdxf.enums.TextEntityAlignment.BOTTOM_CENTER)


def build_dxf(features_by_collection: dict[Collection, list[dict]], area: Area,
              opt: Options, warnings: list[str] | None = None) -> tuple[ezdxf.document.Drawing, Result]:
    doc = new_doc()
    msp = doc.modelspace()
    result = Result(warnings=list(warnings or []))
    for col, feats in features_by_collection.items():
        write_collection(doc, msp, col, feats, area, opt, result)
    if opt.include_frame:
        write_frame(doc, msp, area, opt, result.counts)
    # zoom extents on open
    minx, miny, maxx, maxy = area.bbox
    pad = (maxx - minx) * 0.15
    doc.set_modelspace_vport(height=(maxy - miny) + 2 * pad,
                             center=((minx + maxx) / 2, (miny + maxy) / 2))
    return doc, result
