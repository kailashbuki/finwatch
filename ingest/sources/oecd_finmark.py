"""OECD long-term (10-year) government bond yields -- the broadest free coverage there is.

This is load-bearing for the `r - g` sustainability condition: without it, `r` exists only for
the handful of countries with a full national yield curve (US, Japan, Germany, UK), so the
compounding condition could not be computed for anyone else.

Endpoint notes, verified live:

* The legacy ``stats.oecd.org`` API is retired. Current base is ``sdmx.oecd.org/public/rest``.
* Dataflow ``OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0`` with **9 dimensions** (8 dots):
  ``REF_AREA.FREQ.MEASURE.UNIT_MEASURE.ACTIVITY.ADJUSTMENT.TRANSFORMATION.TIME_HORIZ.METHODOLOGY``
* ``MEASURE=IRLT`` is the long-term (10-year) government bond yield.
* Wildcard a dimension with an **empty string**. The literal ``all`` returns HTTP 404.
* Coverage is 46 areas (including the EA20 aggregate), monthly, 2-4 week lag.
* **History in this dataflow is short.** A request from 2020 returns only ~380 observations
  across 46 series -- roughly the most recent 8 months each, not six years. That is the
  source's own sparsity, not a parsing fault (the raw JSON contains exactly 380 observations).
  It is sufficient for `r` in the sustainability calculation, which needs the latest value, but
  long-yield *history* has to come from the national curves (US, Japan) or ECB instead.

We use OECD directly rather than FRED, which republishes the same OECD series: FRED needs an API
key and its terms state that API access "does not constitute permission" to redistribute
third-party series, while these are flagged *Copyrighted: Citation Required*. Since we publish a
static site we are redistributing, so FRED would add licence risk for identical data.
"""

from __future__ import annotations

import logging

import pandas as pd

from ingest import sdmx
from ingest.fetch import fetch

log = logging.getLogger(__name__)

BASE = "https://sdmx.oecd.org/public/rest"
DATAFLOW = "OECD.SDD.STES,DSD_STES@DF_FINMARK,4.0"

DIMENSIONS = [
    "REF_AREA",
    "FREQ",
    "MEASURE",
    "UNIT_MEASURE",
    "ACTIVITY",
    "ADJUSTMENT",
    "TRANSFORMATION",
    "TIME_HORIZ",
    "METHODOLOGY",
]

#: Long-term (10-year) government bond yield.
LONG_TERM = "IRLT"
#: Short-term / 3-month interbank rate, useful as a policy-rate proxy where BIS lacks coverage.
SHORT_TERM = "IR3TIB"


def build_key(**pinned: str) -> str:
    """Build a 9-dimension key; unspecified dimensions wildcard to an empty segment."""
    return ".".join(pinned.get(dim, "") for dim in DIMENSIONS)


def data_url(key: str, *, start: str) -> str:
    return f"{BASE}/data/{DATAFLOW}/{key}?startPeriod={start}"


def fetch_long_term_yields(
    *, start: str = "2015-01", use_cache: bool = True
) -> pd.DataFrame:
    """Monthly 10-year government bond yields across all reporting areas."""
    key = build_key(FREQ="M", MEASURE=LONG_TERM)
    # OECD rejects `;version=1.0.0` with HTTP 406 (unlike Bundesbank, which *requires* it) and
    # serves GenericData XML for `*/*`, which this project's parser does not read. So the
    # unversioned SDMX-JSON media type is the one that works here.
    raw = fetch(
        data_url(key, start=start),
        accept="application/vnd.sdmx.data+json",
        suffix=".json",
        use_cache=use_cache,
    )
    frame = sdmx.json_to_frame(raw)
    if frame.empty:
        raise ValueError(f"OECD DF_FINMARK returned no observations for key {key!r}")

    frame = frame.rename(
        columns={"REF_AREA": "country", "TIME_PERIOD": "date", "OBS_VALUE": "pct"}
    )
    frame = frame[["country", "date", "pct"]].dropna(subset=["pct"])
    # Monthly periods arrive as YYYY-MM; normalise to a date for a single ordering rule.
    frame["date"] = frame["date"].astype(str).str.slice(0, 7) + "-01"
    frame["kind"] = "yield"
    frame["tenor_months"] = 120
    frame["source"] = "oecd_finmark"
    return frame.sort_values(["country", "date"]).reset_index(drop=True)
