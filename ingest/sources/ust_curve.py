"""US Treasury daily par yield curve.

The widest free single-country maturity ladder available anywhere: 13+ tenors, daily.

Gotcha: ``fiscaldata.treasury.gov`` does **not** host this dataset -- every plausible
dataset name there returns 404 and it is absent from the site's own sitemap. Only the
legacy ``home.treasury.gov`` CSV endpoint works.

Gotcha: the tenor columns are **not fixed across years**. The 2026 file added a
"1.5 Month" column, so tenors are parsed from the header rather than hardcoded.

These are *market* yields, not administered rates: ``rates.kind == "yield"``.
"""

from __future__ import annotations

import io
import logging
import re

import pandas as pd

from ingest.fetch import fetch

log = logging.getLogger(__name__)

BASE = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates"

_TENOR = re.compile(r"^\s*([\d.]+)\s*(Mo|Month|Yr|Year)s?\s*$", re.IGNORECASE)


def data_url(year: int) -> str:
    return (
        f"{BASE}/daily-treasury-rates.csv/{year}/all"
        f"?type=daily_treasury_yield_curve&field_tdr_date_value={year}&page&_format=csv"
    )


def parse_tenor_months(label: str) -> float | None:
    """Convert a column label like ``"1.5 Month"`` or ``"10 Yr"`` into months."""
    match = _TENOR.match(label)
    if not match:
        return None
    value, unit = float(match.group(1)), match.group(2).lower()
    return value if unit.startswith("mo") else value * 12.0


def fetch_curve(*, years: list[int], use_cache: bool = True) -> pd.DataFrame:
    """Return the US par yield curve as ``country, date, tenor_months, pct``."""
    frames = []
    for year in years:
        raw = fetch(data_url(year), suffix=".csv", use_cache=use_cache)
        table = pd.read_csv(io.BytesIO(raw))
        tenors = {c: parse_tenor_months(c) for c in table.columns if c != "Date"}
        unknown = [c for c, m in tenors.items() if m is None]
        if unknown:
            log.warning("unrecognised Treasury tenor columns ignored: %s", unknown)

        long = table.melt(
            id_vars="Date",
            value_vars=[c for c, m in tenors.items() if m is not None],
            var_name="tenor_label",
            value_name="pct",
        )
        long["tenor_months"] = long["tenor_label"].map(tenors)
        long["date"] = pd.to_datetime(long["Date"], format="%m/%d/%Y").dt.strftime("%Y-%m-%d")
        frames.append(long[["date", "tenor_months", "pct"]])

    frame = pd.concat(frames, ignore_index=True).dropna(subset=["pct"])
    frame["country"] = "USA"
    frame["kind"] = "yield"
    frame["source"] = "ust_curve"
    return frame.sort_values(["date", "tenor_months"]).reset_index(drop=True)
