"""BIS debt securities statistics -- government debt outstanding, and how much is foreign-held.

This supplies the **denominator** the dashboard previously lacked. Without it the site showed
who holds cross-border debt but never how much debt exists, so a $10T foreign-holdings figure
sat next to no context and invited comparison against the ~$40T total public debt headline,
which measures something quite different.

Dataflow ``BIS/WS_NA_SEC_DSS/1.0``, 18 dimensions (17 dots) in this order::

    FREQ.ADJUSTMENT.REF_AREA.COUNTERPART_AREA.REF_SECTOR.COUNTERPART_SECTOR.CONSOLIDATION.
    ACCOUNTING_ENTRY.STO.INSTR_ASSET.MATURITY.EXPENDITURE.UNIT_MEASURE.CURRENCY_DENOM.
    VALUATION.PRICES.TRANSFORMATION.CUST_BREAKDOWN

The dimensions must be pinned tightly or the same country/period returns several different
numbers. Verified live for the US, 2026-Q1:

===================================  ==========  ==================================
key                                  value       meaning
===================================  ==========  ==================================
``COUNTERPART_AREA=XW, VALUATION=N``  $34.23T    total govt debt securities, nominal
``COUNTERPART_AREA=XW, VALUATION=M``  $32.43T    same, at market value
``COUNTERPART_AREA=5Z, VALUATION=M``   $9.42T    held by **non-residents**
``STO=F``                              $0.62T    flows, not stocks -- must be excluded
===================================  ==========  ==================================

That ``5Z`` figure is a genuinely independent check on the bilateral data: BIS says $9.42T of
US government debt is non-resident held, Treasury OFS-2 says $9.36T, IMF PIP bilateral sums
to $10.0T. Three separate collections agreeing is the strongest correctness signal available.

Note BIS counts marketable **debt securities**, so it is legitimately below the US "total
public debt" of ~$40T, which also includes non-marketable savings bonds and intragovernmental
instruments. These are different measures, not a discrepancy.

Requires ``Accept: application/vnd.sdmx.data+json`` (handled by ``ingest.fetch``); the API
otherwise returns SDMX-ML XML.
"""

from __future__ import annotations

import logging

import pandas as pd

from ingest import sdmx
from ingest.fetch import fetch

log = logging.getLogger(__name__)

BASE = "https://stats.bis.org/api/v2"
DATAFLOW = "BIS/WS_NA_SEC_DSS/1.0"

DIMENSIONS = [
    "FREQ",
    "ADJUSTMENT",
    "REF_AREA",
    "COUNTERPART_AREA",
    "REF_SECTOR",
    "COUNTERPART_SECTOR",
    "CONSOLIDATION",
    "ACCOUNTING_ENTRY",
    "STO",
    "INSTR_ASSET",
    "MATURITY",
    "EXPENDITURE",
    "UNIT_MEASURE",
    "CURRENCY_DENOM",
    "VALUATION",
    "PRICES",
    "TRANSFORMATION",
    "CUST_BREAKDOWN",
]

#: All holders, i.e. the total outstanding.
ALL_HOLDERS = "XW"
#: Non-resident holders -- the foreign-held share.
NON_RESIDENT = "5Z"

GENERAL_GOVERNMENT = "S13"

#: BIS reports these in billions of USD (``UNIT_MEASURE=USD`` with no unit multiplier
#: exponent on the observation), so scale to absolute USD for consistency with every other
#: table in this project.
BILLION = 1e9


def build_key(**pinned: str) -> str:
    """Build an 18-dimension series key; unspecified dimensions wildcard to empty."""
    return ".".join(pinned.get(dim, "") for dim in DIMENSIONS)


def data_url(key: str, *, start: str | None = None) -> str:
    query = f"?startPeriod={start}" if start else ""
    return f"{BASE}/data/dataflow/{DATAFLOW}/{key}{query}"


def fetch_government_debt(
    *, start: str = "2015", counterpart: str = ALL_HOLDERS, use_cache: bool = True
) -> pd.DataFrame:
    """Government debt securities outstanding, by country and quarter.

    ``counterpart=ALL_HOLDERS`` gives total outstanding; ``NON_RESIDENT`` gives the
    foreign-held portion. Every other dimension is pinned to keep one number per
    country-period: stocks (not flows), total maturity, nominal valuation, unconsolidated.
    """
    key = build_key(
        FREQ="Q",
        COUNTERPART_AREA=counterpart,
        REF_SECTOR=GENERAL_GOVERNMENT,
        CONSOLIDATION="N",
        ACCOUNTING_ENTRY="L",
        STO="LE",  # levels/stocks; STO=F is flows and must not be mixed in
        INSTR_ASSET="F3",
        MATURITY="T",
        UNIT_MEASURE="USD",
        # Both default to sub-breakdowns that would multiply rows per country: currency of
        # denomination (XDC/X1 as well as the _T total) and BIS's custom breakdown axis.
        CURRENCY_DENOM="_T",
        CUST_BREAKDOWN="_T",
        # Nominal is only published for the all-holders cut; the non-resident cut is
        # market-valued, so valuation is left to the caller's pin below.
        VALUATION="N" if counterpart == ALL_HOLDERS else "M",
        TRANSFORMATION="N",
    )
    raw = fetch(data_url(key, start=start), suffix=".json", use_cache=use_cache)
    frame = sdmx.json_to_frame(raw)
    if frame.empty:
        raise ValueError(f"BIS WS_NA_SEC_DSS returned no observations for key {key!r}")

    frame = frame.rename(
        columns={"REF_AREA": "country", "TIME_PERIOD": "period", "OBS_VALUE": "usd"}
    )
    frame["usd"] = frame["usd"] * BILLION
    frame = frame[["country", "period", "usd"]].dropna(subset=["usd"])
    frame["measure"] = "total" if counterpart == ALL_HOLDERS else "non_resident"
    frame["source"] = "bis_debtsec"

    duplicates = frame.duplicated(subset=["country", "period"]).sum()
    if duplicates:
        raise ValueError(
            f"{duplicates} duplicate country/period rows -- dimensions are under-pinned "
            "and the series is ambiguous"
        )
    return frame.sort_values(["country", "period"]).reset_index(drop=True)


def foreign_share(*, start: str = "2015", use_cache: bool = True) -> pd.DataFrame:
    """Join total and non-resident holdings into a foreign-held share per country/period.

    Note the two cuts use different valuations (nominal for the total, market for the
    non-resident portion), because that is what BIS publishes. The ratio is therefore
    approximate and is labelled as such in the UI rather than presented as exact.
    """
    total = fetch_government_debt(start=start, counterpart=ALL_HOLDERS, use_cache=use_cache)
    foreign = fetch_government_debt(
        start=start, counterpart=NON_RESIDENT, use_cache=use_cache
    )
    merged = total.merge(
        foreign[["country", "period", "usd"]].rename(columns={"usd": "foreign_usd"}),
        on=["country", "period"],
        how="left",
    )
    merged["foreign_share"] = merged["foreign_usd"] / merged["usd"]
    return merged.drop(columns=["measure"])
