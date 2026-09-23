"""Japan MOF JGB par yield curve -- 15 tenors (1Y-40Y), daily, back to 1974.

Three quirks, all verified live, all of which silently corrupt the data if ignored:

1. The **English** path (``/english/policy/jgbs/...jgbcme.csv``) serves only the *current
   month*. Full history lives on the Japanese path under ``data/jgbcm_all.csv``.
2. The file is **cp932** (Shift-JIS), not UTF-8. Decoding as UTF-8 raises.
3. Dates use **Japanese imperial era** notation (``S49.9.24``, ``R8.8.31``), not ISO.
   Era letters map to Shōwa / Heisei / Reiwa start years; ``-`` marks a missing tenor.
"""

from __future__ import annotations

import io
import logging

import pandas as pd

from ingest.fetch import fetch

log = logging.getLogger(__name__)

#: Full history (Japanese path). The English path is current-month only.
HISTORY_URL = "https://www.mof.go.jp/jgbs/reference/interest_rate/data/jgbcm_all.csv"

ENCODING = "cp932"

#: Gregorian year of each era's year 1.
ERA_START = {"M": 1868, "T": 1912, "S": 1926, "H": 1989, "R": 2019}


def parse_imperial_date(value: str) -> str | None:
    """Convert ``"R8.8.31"`` to ``"2026-08-31"``. Returns None if unparseable."""
    value = value.strip()
    if len(value) < 2 or value[0] not in ERA_START:
        return None
    try:
        era_year, month, day = (int(p) for p in value[1:].split("."))
    except ValueError:
        return None
    year = ERA_START[value[0]] + era_year - 1
    try:
        return f"{year:04d}-{month:02d}-{day:02d}"
    except (TypeError, ValueError):
        return None


def fetch_curve(*, use_cache: bool = True) -> pd.DataFrame:
    """Return the JGB par yield curve as ``country, date, tenor_months, pct``."""
    raw = fetch(HISTORY_URL, suffix=".csv", use_cache=use_cache)
    text = raw.decode(ENCODING, errors="replace")

    # Row 0 is a title banner, row 1 the header; the tenor labels are Japanese ("10年").
    table = pd.read_csv(io.StringIO(text), skiprows=1, na_values=["-"])
    date_col = table.columns[0]

    tenors = {}
    for column in table.columns[1:]:
        label = column.strip()
        if label.endswith("年") and label[:-1].isdigit():
            tenors[column] = int(label[:-1]) * 12

    if not tenors:
        raise ValueError(f"no JGB tenor columns recognised in {list(table.columns)}")

    long = table.melt(
        id_vars=date_col, value_vars=list(tenors), var_name="tenor_label", value_name="pct"
    )
    long["tenor_months"] = long["tenor_label"].map(tenors)
    long["date"] = long[date_col].astype(str).map(parse_imperial_date)
    long["pct"] = pd.to_numeric(long["pct"], errors="coerce")

    frame = long.dropna(subset=["date", "pct"])[["date", "tenor_months", "pct"]]
    frame["country"] = "JPN"
    frame["kind"] = "yield"
    frame["source"] = "jgb_curve"
    return frame.sort_values(["date", "tenor_months"]).reset_index(drop=True)
