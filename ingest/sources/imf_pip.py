"""IMF PIP -- Portfolio Investment Positions by Counterpart Economy (formerly CPIS).

This is the primary source for the bilateral creditor->debtor network.

Facts established by probing the live API (2026-09-23), all of which this module
depends on:

* The legacy ``dataservices.imf.org`` host no longer resolves. The current service is
  SDMX 2.1 at ``api.imf.org``, unauthenticated (``ACCESS_SHARING_LEVEL=PUBLIC_OPEN``).
* Dataflow is ``IMF.STA,PIP,5.0.0``, 7 dimensions in this order:
  ``COUNTRY.ACCOUNTING_ENTRY.INDICATOR.SECTOR.COUNTERPART_SECTOR.COUNTERPART_COUNTRY.FREQUENCY``
  (6 dots; a 7th returns HTTP 400).
* Requesting SDMX-JSON returns **HTTP 500** on this dataflow, so we parse SDMX-ML.
* Country codes are ISO alpha-3 (``USA``, ``JPN``). Using 2-letter codes returns
  HTTP 200 with an empty dataset rather than an error -- the most likely silent-failure
  mode here, hence :func:`fetch_bilateral` asserts non-empty results.
* ``SECTOR`` is the **holder** sector; ``COUNTERPART_SECTOR`` is the **issuer** sector.
* Issuer-sector detail (``COUNTERPART_SECTOR=S13``, general government) is reported by
  only 28 of 85 reporters (derive the current list with
  :func:`government_issuer_reporters` rather than hardcoding it). Major creditors
  including Japan, China, the UK, Luxembourg and Switzerland report only the ``S1``
  total, so a government-only bilateral network is not globally achievable from PIP alone.
* The debtor-side view (``ACCOUNTING_ENTRY=L``) exists only for the derived ``*_SCC_*``
  indicators at total-economy level, with no sector split -- it cannot answer
  "who holds country X's government bonds".
"""

from __future__ import annotations

import logging

import pandas as pd

from ingest import sdmx
from ingest.fetch import fetch

log = logging.getLogger(__name__)

BASE = "https://api.imf.org/external/sdmx/2.1"
DATAFLOW = "IMF.STA,PIP,5.0.0"

#: Total debt securities positions, in USD. The headline indicator.
INDICATOR_DEBT = "P_F3_P_USD"
INDICATOR_DEBT_LONG_TERM = "P_F3_L_P_USD"
INDICATOR_DEBT_SHORT_TERM = "P_F3_S_P_USD"

TOTAL_ECONOMY = "S1"
GENERAL_GOVERNMENT = "S13"

#: Holder-sector codes worth surfacing as a holder-class breakdown.
HOLDER_SECTORS = {
    "S1": "Total economy",
    "S121": "Central bank",
    "S122": "Banks (excl. central bank)",
    "S12R": "Other financial corporations",
    "S13": "General government",
    "S1V": "Non-financial corporations, households and NPISH",
}

#: Codes in ``CL_PIP_COUNTRY`` that are not countries. PIP prefixes these ``TX``/``GX``;
#: they must never be drawn on the map or summed alongside real economies.
AGGREGATE_PREFIXES = ("TX", "GX")


def _key(
    *,
    country: str = "",
    accounting_entry: str = "A",
    indicator: str = INDICATOR_DEBT,
    sector: str = "",
    counterpart_sector: str = "",
    counterpart_country: str = "",
    frequency: str = "A",
) -> str:
    """Build a PIP series key. Empty string wildcards a dimension."""
    return ".".join(
        [
            country,
            accounting_entry,
            indicator,
            sector,
            counterpart_sector,
            counterpart_country,
            frequency,
        ]
    )


def data_url(key: str, *, start: str | None = None, end: str | None = None) -> str:
    params = []
    if start:
        params.append(f"startPeriod={start}")
    if end:
        params.append(f"endPeriod={end}")
    query = f"?{'&'.join(params)}" if params else ""
    return f"{BASE}/data/{DATAFLOW}/{key}{query}"


def structure_url() -> str:
    return f"{BASE}/datastructure/IMF.STA/DSD_PIP/5.0.0?references=all"


def is_aggregate(code: str) -> bool:
    """True for PIP pseudo-economies (International Organizations, SEFER+SSIO, ...)."""
    return code.startswith(AGGREGATE_PREFIXES)


def fetch_bilateral(
    *,
    start: str,
    end: str | None = None,
    holder_sector: str = TOTAL_ECONOMY,
    indicator: str = INDICATOR_DEBT,
    use_cache: bool = True,
) -> pd.DataFrame:
    """Fetch the bilateral holdings matrix for one holder sector.

    Returns a long frame with one row per (creditor, debtor, issuer_sector, period).
    Both issuer-sector variants are returned: ``S1`` (all debt securities, 85 reporters)
    and ``S13`` (government only, 28 reporters). Callers pick per-pair -- see the
    hybrid edge-provenance rule in the project README.
    """
    key = _key(indicator=indicator, sector=holder_sector)
    url = data_url(key, start=start, end=end)
    raw = fetch(url, suffix=".xml", use_cache=use_cache)
    frame = sdmx.to_frame(raw)

    if frame.empty:
        raise ValueError(
            f"PIP returned an empty dataset for key {key!r}. PIP answers HTTP 200 with "
            "zero series for invalid dimension codes -- check country codes are ISO alpha-3."
        )

    frame = frame.rename(
        columns={
            "COUNTRY": "creditor",
            "COUNTERPART_COUNTRY": "debtor",
            "COUNTERPART_SECTOR": "issuer_sector",
            "SECTOR": "holder_sector",
            "TIME_PERIOD": "period",
            "OBS_VALUE": "usd",
        }
    )
    keep = [
        c
        for c in ("creditor", "debtor", "issuer_sector", "holder_sector", "period", "usd")
        if c in frame.columns
    ]
    frame = frame[keep].dropna(subset=["usd"])
    frame["instrument"] = frame["issuer_sector"].map(
        lambda s: "government" if s == GENERAL_GOVERNMENT else "all_debt"
    )
    frame["source"] = "imf_pip"
    return frame.reset_index(drop=True)


def government_issuer_reporters(frame: pd.DataFrame) -> list[str]:
    """Reporters in ``frame`` that break out a general-government issuer sector."""
    gov = frame[frame["issuer_sector"] == GENERAL_GOVERNMENT]
    return sorted(gov["creditor"].unique())
