"""Layer configuration for Ondergrond NL.

One place that decides: which PDOK collections to fetch for a layer group,
which DXF layer each object lands on, and which AutoCAD color / linetype it gets.
Keep this in sync with src/config/layers.ts in the frontend.
"""

from __future__ import annotations

from dataclasses import dataclass, field

PDOK_BGT = "https://api.pdok.nl/lv/bgt/ogc/v1"
PDOK_BAG = "https://api.pdok.nl/lv/bag/ogc/v1"
PDOK_BRT = "https://api.pdok.nl/brt/top10nl/ogc/v1"
PDOK_BRK_WFS = "https://service.pdok.nl/kadaster/kadastralekaart/wfs/v5_0"
PDOK_LOCATIESERVER = "https://api.pdok.nl/bzk/locatieserver/search/v3_1"
CRS_RD = "http://www.opengis.net/def/crs/EPSG/0/28992"

BGT_MAX_RADIUS_M = 500.0
MAX_AREA_KM2 = 4.0

# AutoCAD Color Index
ACI_RED, ACI_YELLOW, ACI_GREEN, ACI_CYAN, ACI_BLUE, ACI_MAGENTA, ACI_WHITE = 1, 2, 3, 4, 5, 6, 7
ACI_DARKGREY, ACI_LIGHTGREY = 8, 9


@dataclass(frozen=True)
class Collection:
    api: str                      # "bgt" | "bag" | "brk" | "brt"
    collection: str               # OGC collection id or WFS typeName
    kind: str                     # "polygon" | "line" | "point"
    dxf_layer: str                # base DXF layer name
    color: int
    linetype: str = "CONTINUOUS"
    subtype_attr: str | None = None   # attribute used for the layer suffix
    label_attr: str | None = None     # attribute written as TEXT
    hatch: str | None = None          # ezdxf pattern name for polygons, e.g. "ANSI31"


@dataclass(frozen=True)
class LayerGroup:
    id: str
    label: str
    default_on: bool
    collections: tuple[Collection, ...]
    max_radius_m: float | None = None


# Maps BGT functie / fysiek_voorkomen → readable layer suffix. Unknown → CamelCase of the value.
BGT_SUBTYPES: dict[str, str] = {
    "rijbaan": "Rijbaan", "rijbaan: autosnelweg": "Rijbaan", "rijbaan: autoweg": "Rijbaan",
    "rijbaan: regionale weg": "Rijbaan", "rijbaan: lokale weg": "Rijbaan",
    "fietspad": "Fietspad", "voetpad": "Voetpad", "voetpad op trap": "Voetpad",
    "voetgangersgebied": "Voetpad", "parkeervlak": "Parkeervlak", "inrit": "Inrit",
    "spoorbaan": "Spoorbaan", "ov-baan": "OVBaan", "overweg": "Overweg", "ruiterpad": "Ruiterpad",
    "woonerf": "Woonerf", "berm": "Berm", "verkeerseiland": "Verkeerseiland",
    "groenvoorziening": "Groen", "grasland": "Gras", "grasland overig": "Gras",
    "grasland agrarisch": "Gras", "bouwland": "Bouwland", "loofbos": "Bos", "naaldbos": "Bos",
    "gemengd bos": "Bos", "struiken": "Struiken", "heide": "Heide", "moeras": "Moeras",
    "rietland": "Riet", "kwelder": "Kwelder", "fruitteelt": "Fruitteelt", "boomteelt": "Boomteelt",
    "houtwal": "Houtwal", "duin": "Duin", "erf": "Erf", "gesloten verharding": "Verharding",
    "open verharding": "Verharding", "half verhard": "HalfVerhard", "onverhard": "Onverhard",
    "zand": "Zand", "waterloop": "Waterloop", "watervlakte": "Watervlakte", "zee": "Zee",
    "greppel": "Greppel", "droge sloot": "DrogeSloot", "transitie": "Transitie",
}

LAYER_GROUPS: dict[str, LayerGroup] = {
    "bgt_basis": LayerGroup(
        id="bgt_basis", label="BGT basis", default_on=True, max_radius_m=BGT_MAX_RADIUS_M,
        collections=(
            Collection("bgt", "wegdeel", "polygon", "BGT_Wegdeel", ACI_DARKGREY, subtype_attr="functie"),
            Collection("bgt", "ondersteunendwegdeel", "polygon", "BGT_OndWegdeel", ACI_LIGHTGREY, subtype_attr="functie"),
            Collection("bgt", "onbegroeidterreindeel", "polygon", "BGT_Onbegroeid", ACI_LIGHTGREY, subtype_attr="fysiek_voorkomen"),
            Collection("bgt", "begroeidterreindeel", "polygon", "BGT_Begroeid", ACI_GREEN, subtype_attr="fysiek_voorkomen", hatch="ANSI31"),
            Collection("bgt", "waterdeel", "polygon", "BGT_Waterdeel", ACI_BLUE, subtype_attr="type", hatch="ANSI37"),
            Collection("bgt", "ondersteunendwaterdeel", "polygon", "BGT_OndWaterdeel", ACI_BLUE, subtype_attr="type"),
            Collection("bgt", "pand", "polygon", "BGT_Pand", ACI_RED),
            Collection("bgt", "overigbouwwerk", "polygon", "BGT_Bouwwerk", ACI_RED, subtype_attr="type"),
            Collection("bgt", "kunstwerkdeel_vlak", "polygon", "BGT_Kunstwerk", 30, subtype_attr="type"),
            Collection("bgt", "kunstwerkdeel_lijn", "line", "BGT_Kunstwerk", 30, subtype_attr="type"),
            Collection("bgt", "overbruggingsdeel", "polygon", "BGT_Overbrugging", 30, subtype_attr="type_overbruggingsdeel"),
            Collection("bgt", "scheiding_lijn", "line", "BGT_Scheiding", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "scheiding_vlak", "polygon", "BGT_Scheiding", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "openbareruimtelabel", "point", "BGT_Straatnaam", ACI_WHITE, label_attr="tekst"),
        ),
    ),
    "bgt_inrichting": LayerGroup(
        id="bgt_inrichting", label="BGT inrichting", default_on=False, max_radius_m=BGT_MAX_RADIUS_M,
        collections=(
            Collection("bgt", "vegetatieobject_punt", "point", "BGT_Boom", ACI_GREEN, subtype_attr="type"),
            Collection("bgt", "vegetatieobject_lijn", "line", "BGT_Haag", ACI_GREEN, subtype_attr="type"),
            Collection("bgt", "paal", "point", "BGT_Paal", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "mast", "point", "BGT_Mast", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "put", "point", "BGT_Put", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "kast", "point", "BGT_Kast", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "bord", "point", "BGT_Bord", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "bak", "point", "BGT_Bak", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "straatmeubilair", "point", "BGT_Meubilair", ACI_WHITE, subtype_attr="type"),
            Collection("bgt", "weginrichtingselement_punt", "point", "BGT_Weginrichting", ACI_LIGHTGREY, subtype_attr="type"),
            Collection("bgt", "weginrichtingselement_lijn", "line", "BGT_Weginrichting", ACI_LIGHTGREY, subtype_attr="type"),
            Collection("bgt", "weginrichtingselement_vlak", "polygon", "BGT_Weginrichting", ACI_LIGHTGREY, subtype_attr="type"),
        ),
    ),
    "bag_pand": LayerGroup(
        id="bag_pand", label="BAG panden", default_on=True,
        collections=(Collection("bag", "pand", "polygon", "BAG_Pand", ACI_RED),),
    ),
    "bag_adres": LayerGroup(
        id="bag_adres", label="BAG adressen", default_on=False,
        collections=(Collection("bag", "verblijfsobject", "point", "BAG_Adres_Tekst", ACI_WHITE, label_attr="huisnummer"),),
    ),
    "brk_perceel": LayerGroup(
        id="brk_perceel", label="Kadastrale percelen", default_on=True,
        collections=(Collection("brk", "kadastralekaart:Perceel", "polygon", "BRK_Perceel", ACI_MAGENTA, label_attr="perceelnummer"),),
    ),
    "brk_grens": LayerGroup(
        id="brk_grens", label="Kadastrale grenzen", default_on=False,
        collections=(Collection("brk", "kadastralekaart:KadastraleGrens", "line", "BRK_Grens", ACI_MAGENTA, "DASHED", subtype_attr="typeGrensWaarde"),),
    ),
    "brt_overzicht": LayerGroup(
        id="brt_overzicht", label="BRT overzicht", default_on=False,
        collections=(
            Collection("brt", "wegdeel_vlak", "polygon", "BRT_Weg", ACI_DARKGREY, subtype_attr="typeweg"),
            Collection("brt", "wegdeel_lijn", "line", "BRT_Weg", ACI_DARKGREY, subtype_attr="typeweg"),
            Collection("brt", "waterdeel_vlak", "polygon", "BRT_Water", ACI_BLUE, subtype_attr="typewater"),
            Collection("brt", "waterdeel_lijn", "line", "BRT_Water", ACI_BLUE, subtype_attr="typewater"),
            Collection("brt", "gebouw_vlak", "polygon", "BRT_Gebouw", ACI_RED, subtype_attr="typegebouw"),
            Collection("brt", "terrein_vlak", "polygon", "BRT_Terrein", ACI_GREEN, subtype_attr="typelandgebruik"),
        ),
    ),
}

FRAME_LAYER_RAND = ("KADER_Rand", ACI_WHITE)
FRAME_LAYER_TEKST = ("KADER_Tekst", ACI_WHITE)
FRAME_LAYER_NOORD = ("KADER_Noordpijl", ACI_WHITE)
BLOCK_PUNT = "PUNT"


def default_group_ids() -> list[str]:
    return [g.id for g in LAYER_GROUPS.values() if g.default_on]


def subtype_suffix(value) -> str:
    """Attribute value → safe DXF layer suffix ('Rijbaan', 'HalfVerhard', ...)."""
    if not isinstance(value, str) or not value.strip():
        return "Overig"
    key = value.strip().lower()
    if key in BGT_SUBTYPES:
        return BGT_SUBTYPES[key]
    import re
    import unicodedata
    plain = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    words = re.split(r"[^A-Za-z0-9]+", plain)
    out = "".join(w[:1].upper() + w[1:].lower() for w in words if w)
    return out or "Overig"
