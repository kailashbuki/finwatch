"""SDMX-ML parsing helpers.

Only the ``StructureSpecificData`` message flavour is handled, because that is what
every SDMX source in this project returns. Parsing is streamed via ``iterparse``:
a single PIP year is ~46 MB and holding the whole tree costs far more memory than
the resulting frame.
"""

from __future__ import annotations

import io
import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import IO

import pandas as pd
from lxml import etree

log = logging.getLogger(__name__)

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_NS = {
    "s": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/structure",
    "c": "http://www.sdmx.org/resources/sdmxml/schemas/v2_1/common",
}


def iter_observations(source: bytes | str | Path | IO[bytes]) -> Iterator[dict[str, str]]:
    """Yield one dict per observation, merging its parent ``Series`` attributes.

    Series-level dimensions (COUNTRY, SECTOR, ...) are flattened onto each
    observation alongside ``TIME_PERIOD`` and ``OBS_VALUE``.
    """
    if isinstance(source, bytes):
        source = io.BytesIO(source)

    context = etree.iterparse(source, events=("end",), tag="{*}Series", recover=True)
    for _, series in context:
        base = dict(series.attrib)
        for obs in series.iter("{*}Obs"):
            yield {**base, **dict(obs.attrib)}
        # Free the parsed subtree and any preceding siblings.
        series.clear()
        parent = series.getparent()
        if parent is not None:
            while series.getprevious() is not None:
                del parent[0]
    del context


def to_frame(source: bytes | str | Path | IO[bytes]) -> pd.DataFrame:
    """Parse an SDMX-ML data message into a long-format DataFrame."""
    rows = list(iter_observations(source))
    if not rows:
        return pd.DataFrame()
    frame = pd.DataFrame(rows)
    if "OBS_VALUE" in frame:
        frame["OBS_VALUE"] = pd.to_numeric(frame["OBS_VALUE"], errors="coerce")
    return frame


def json_to_frame(payload: bytes | dict) -> pd.DataFrame:
    """Parse an SDMX-JSON data message into a long-format DataFrame.

    SDMX-JSON encodes series keys as colon-joined *indices* into the dimension value
    lists (``"0:12"``), and observation keys as indices into the observation dimension,
    so both have to be resolved back to codes.

    Handles both message versions in use here, which differ in a way that is easy to miss:
    BIS serves **SDMX-JSON 1.0** with a single ``data.structure`` object, while OECD serves
    **2.0** with a ``data.structures`` *list* that each dataSet indexes into.
    """
    doc = json.loads(payload) if isinstance(payload, bytes | str) else payload
    data = doc["data"]

    structures = data.get("structures")
    if structures is None:
        structures = [data["structure"]]

    def dimensions_for(dataset: dict) -> tuple[list, list]:
        index = dataset.get("structure", 0)
        structure = structures[index] if index < len(structures) else structures[0]
        dims = structure.get("dimensions", {})
        return dims.get("series", []), dims.get("observation", [])

    rows: list[dict[str, object]] = []
    for dataset in data.get("dataSets", []):
        series_dims, obs_dims = dimensions_for(dataset)
        for key, series in dataset.get("series", {}).items():
            indices = [int(i) for i in key.split(":")]
            base = {
                dim["id"]: dim["values"][idx]["id"]
                for dim, idx in zip(series_dims, indices, strict=False)
            }
            for obs_key, obs in series.get("observations", {}).items():
                row = dict(base)
                for dim, idx in zip(obs_dims, obs_key.split(":"), strict=False):
                    row[dim["id"]] = dim["values"][int(idx)]["id"]
                row["OBS_VALUE"] = pd.to_numeric(obs[0], errors="coerce") if obs else None
                rows.append(row)

    frame = pd.DataFrame(rows)
    if "OBS_VALUE" in frame:
        frame["OBS_VALUE"] = pd.to_numeric(frame["OBS_VALUE"], errors="coerce")
    return frame


def english_name(code: etree._Element) -> str:
    """Return a code's English name.

    IMF codelists carry names in several languages and Arabic often comes first,
    so taking the first ``Name`` child yields the wrong string.
    """
    for name in code.iterfind("c:Name", _NS):
        if name.get(XML_LANG) == "en":
            return name.text or ""
    first = code.find("c:Name", _NS)
    return (first.text or "") if first is not None else ""


def codelist(source: bytes | str | Path, codelist_id: str) -> dict[str, str]:
    """Extract ``{code: english name}`` for one codelist out of a structure message."""
    tree = etree.parse(io.BytesIO(source) if isinstance(source, bytes) else source)
    for candidate in tree.iterfind(".//s:Codelist", _NS):
        if candidate.get("id") == codelist_id:
            return {c.get("id"): english_name(c) for c in candidate.iterfind("s:Code", _NS)}
    raise KeyError(f"codelist {codelist_id!r} not found")
