"""World Bank indicators: the denominators and debt-dynamics inputs.

Without these the dashboard can state debt *stocks* but nothing about sustainability --
$34.23T and $0.73T are not comparable without GDP, and a debt level says nothing on its own.

Indicators (all verified live, 2024 coverage in brackets):

============================  =======================================  ==========
indicator                     meaning                                  economies
============================  =======================================  ==========
``NY.GDP.MKTP.CD``            GDP, current US$ -- debt/GDP denominator  247
``NY.GDP.MKTP.CN``            GDP, current local currency -- for `g`    247
``GC.XPN.INTP.RV.ZS``         interest payments, % of revenue           105
``FI.RES.TOTL.CD``            total reserves, US$                       165
``DT.DOD.DSTC.CD``            short-term external debt, US$             (LMICs)
============================  =======================================  ==========

Why two GDP series: the debt/GDP ratio must compare USD debt against USD GDP, while nominal
growth for the `r - g` condition must be measured in **local currency**, because `r` is a
nominal local-currency interest rate. Using USD growth would inject exchange-rate moves into
what is meant to be a domestic compounding condition and would, for example, make any country
whose currency depreciated look like it had negative nominal growth.

Licensing: World Bank data is CC BY 4.0 -- redistribution is explicitly permitted with
attribution, which matters because we publish a static site.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from ingest.fetch import fetch

log = logging.getLogger(__name__)

BASE = "https://api.worldbank.org/v2"

INDICATORS: dict[str, str] = {
    "NY.GDP.MKTP.CD": "gdp_usd",
    "NY.GDP.MKTP.CN": "gdp_lcu",
    "GC.XPN.INTP.RV.ZS": "interest_pct_revenue",
    "FI.RES.TOTL.CD": "reserves_usd",
    "DT.DOD.DSTC.CD": "short_term_external_debt_usd",
}


def indicator_url(indicator: str, *, start: int, end: int) -> str:
    return (
        f"{BASE}/country/all/indicator/{indicator}"
        f"?format=json&date={start}:{end}&per_page=20000"
    )


def fetch_indicator(
    indicator: str, *, start: int = 2000, end: int = 2026, use_cache: bool = True
) -> pd.DataFrame:
    """Fetch one indicator as ``country, year, value``.

    The World Bank wraps data in a two-element array: ``[metadata, rows]``. An invalid
    indicator still returns HTTP 200 with an error object in the first slot rather than a
    non-200, so the shape is checked explicitly.
    """
    payload = json.loads(
        fetch(indicator_url(indicator, start=start, end=end), suffix=".json", use_cache=use_cache)
    )
    if not isinstance(payload, list) or len(payload) < 2 or payload[1] is None:
        raise ValueError(f"World Bank returned no rows for {indicator}: {str(payload)[:200]}")

    frame = pd.DataFrame(payload[1])
    frame["country"] = frame["countryiso3code"]
    frame["year"] = pd.to_numeric(frame["date"], errors="coerce").astype("Int64")
    frame["value"] = pd.to_numeric(frame["value"], errors="coerce")
    # Blank iso3 marks the World Bank's own regional aggregates.
    frame = frame[frame["country"].astype(str).str.len() == 3]
    return frame[["country", "year", "value"]].dropna(subset=["value", "year"])


def fetch_all(*, start: int = 2000, end: int = 2026, use_cache: bool = True) -> pd.DataFrame:
    """Fetch every indicator, returning one wide row per country/year."""
    frames = []
    for indicator, column in INDICATORS.items():
        try:
            frame = fetch_indicator(indicator, start=start, end=end, use_cache=use_cache)
        except Exception as exc:  # noqa: BLE001 -- one sparse indicator must not sink the rest
            log.warning("World Bank indicator %s unavailable: %s", indicator, exc)
            continue
        frames.append(frame.rename(columns={"value": column}).set_index(["country", "year"]))

    if not frames:
        raise ValueError("no World Bank indicators could be fetched")

    wide = pd.concat(frames, axis=1).reset_index()
    wide["source"] = "worldbank"
    return wide.sort_values(["country", "year"]).reset_index(drop=True)


def nominal_growth(wide: pd.DataFrame) -> pd.DataFrame:
    """Add ``nominal_growth_pct``: year-over-year growth of local-currency GDP.

    Local currency, deliberately -- see the module docstring. A 3-year mean is also produced
    because single-year nominal growth is noisy and the `r - g` condition is about the
    medium-term trend, not one print.
    """
    frame = wide.sort_values(["country", "year"]).copy()
    if "gdp_lcu" not in frame.columns:
        frame["nominal_growth_pct"] = pd.NA
        frame["nominal_growth_3y_pct"] = pd.NA
        return frame

    grouped = frame.groupby("country")["gdp_lcu"]
    frame["nominal_growth_pct"] = grouped.pct_change() * 100
    frame["nominal_growth_3y_pct"] = (
        frame.groupby("country")["nominal_growth_pct"]
        .transform(lambda s: s.rolling(3, min_periods=2).mean())
    )
    return frame
