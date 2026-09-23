"""BIS central bank policy rates (``WS_CBPOL``).

The broadest free policy-rate dataset: 49 reporting areas, daily. Note BIS's own
marketing says "~38 central banks" -- the live API dimension list is larger because it
enumerates euro-area member states individually alongside ``XM`` for the euro area.

Gotcha: this API returns SDMX-ML **XML** unless ``Accept: application/vnd.sdmx.data+json``
is sent. That header is applied automatically via ``HOST_ACCEPT`` in ``ingest.fetch``.

These are *administered* rates, decided by a committee -- not market yields. They belong
to ``rates.kind == "policy"`` and must render as step lines.
"""

from __future__ import annotations

import logging

import pandas as pd

from ingest import sdmx
from ingest.fetch import fetch

log = logging.getLogger(__name__)

BASE = "https://stats.bis.org/api/v2"
DATAFLOW = "BIS/WS_CBPOL/1.0"

#: BIS uses ``XM`` for the euro area; it is an aggregate, not a country.
EURO_AREA = "XM"


def data_url(frequency: str = "D", *, start: str | None = None) -> str:
    query = f"?startPeriod={start}" if start else ""
    return f"{BASE}/data/dataflow/{DATAFLOW}/{frequency}{query}"


def fetch_policy_rates(*, start: str = "2000-01-01", use_cache: bool = True) -> pd.DataFrame:
    """Return daily policy rates as ``country, date, pct``."""
    raw = fetch(data_url("D", start=start), suffix=".json", use_cache=use_cache)
    frame = sdmx.json_to_frame(raw)
    if frame.empty:
        raise ValueError("BIS WS_CBPOL returned no observations")

    frame = frame.rename(
        columns={"REF_AREA": "country", "TIME_PERIOD": "date", "OBS_VALUE": "pct"}
    )
    frame = frame[["country", "date", "pct"]].dropna(subset=["pct"])
    frame["kind"] = "policy"
    frame["tenor"] = None
    frame["source"] = "bis_cbpol"
    return frame.sort_values(["country", "date"]).reset_index(drop=True)
