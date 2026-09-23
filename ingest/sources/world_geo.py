"""World map geometry, re-keyed to ISO alpha-3.

The standard TopoJSON world atlas keys countries by **ISO numeric** id (``"840"``), while
every other table in this project joins on alpha-3 (``"USA"``). Rather than push that
mapping into the browser, the build re-keys the geometry here and publishes a single
alpha-3-keyed artifact, so the frontend does no code translation at all.

Licensing: world-atlas is derived from Natural Earth (public domain); the ISO code table
ships with i18n-iso-countries (MIT). Both are safe to redistribute.
"""

from __future__ import annotations

import json
import logging

from ingest.fetch import fetch

log = logging.getLogger(__name__)

TOPOJSON_URL = "https://cdn.jsdelivr.net/npm/world-atlas@2/countries-110m.json"
ISO_CODES_URL = "https://cdn.jsdelivr.net/npm/i18n-iso-countries@7/codes.json"

#: Natural Earth carries a few entities ISO does not, or under different ids. Mapping them
#: explicitly avoids silently dropping real geometry from the map.
EXTRA_NUMERIC_TO_ALPHA3 = {
    "-99": None,  # Natural Earth placeholder for disputed/unrecognised areas
    "728": "SSD",  # South Sudan
}


def numeric_to_alpha3(*, use_cache: bool = True) -> dict[str, str]:
    """Return ``{iso numeric: alpha-3}``, numeric unpadded to match TopoJSON ids."""
    raw = json.loads(fetch(ISO_CODES_URL, suffix=".json", use_cache=use_cache))
    mapping: dict[str, str] = {}
    for entry in raw:
        alpha3, numeric = entry[1], entry[2]
        mapping[numeric] = alpha3
        mapping[numeric.lstrip("0")] = alpha3  # TopoJSON ids are unpadded ("4", not "004")
    for numeric, alpha3 in EXTRA_NUMERIC_TO_ALPHA3.items():
        if alpha3:
            mapping[numeric] = alpha3
    return mapping


def fetch_world_topology(*, use_cache: bool = True) -> dict:
    """Return the world TopoJSON with each country's ``id`` replaced by its alpha-3 code.

    Geometries with no ISO mapping (Natural Earth's ``-99`` disputed areas) are dropped
    rather than rendered with a null key that could never join to data.
    """
    topology = json.loads(fetch(TOPOJSON_URL, suffix=".json", use_cache=use_cache))
    mapping = numeric_to_alpha3(use_cache=use_cache)

    countries = topology["objects"]["countries"]
    kept, dropped = [], []
    for geometry in countries["geometries"]:
        alpha3 = mapping.get(str(geometry.get("id")))
        if not alpha3:
            dropped.append(geometry.get("properties", {}).get("name", geometry.get("id")))
            continue
        geometry["id"] = alpha3
        kept.append(geometry)

    countries["geometries"] = kept
    if dropped:
        log.info("map geometries without an ISO alpha-3 code dropped: %s", dropped)
    log.info("world topology re-keyed to alpha-3: %d countries", len(kept))
    return topology
