"""US Treasury debt outstanding and its holder breakdown.

This is what turns the dashboard from "who holds cross-border debt" into a full picture:
the denominator (total debt) plus every holder category, not just foreign ones.

Two datasets, both on the open Fiscal Data API (no auth, redistribution unrestricted):

* **Debt to the Penny** -- daily total public debt, split into debt held by the public and
  intragovernmental holdings (Social Security and other federal trust funds).
* **OFS-2, Estimated Ownership of U.S. Treasury Securities** -- quarterly holder classes.

Critical gotcha: ``record_date`` is the **publication** date, and several observation
periods share one. The real observation date is ``end_of_month``. Keying on ``record_date``
silently mixes quarters -- it produced a "total public debt" of $30.6T instead of $39.1T
during development. Always group by ``end_of_month``.

Second gotcha: the most recent published quarter has the totals filled but the detailed
categories ``null``; the breakdown lags by a quarter. :func:`latest_complete_period` finds
the newest period where the detail is actually present.

Values are reported in **billions** of USD and converted to absolute USD here.
"""

from __future__ import annotations

import json
import logging

import pandas as pd

from ingest.fetch import fetch

log = logging.getLogger(__name__)

BASE = "https://api.fiscaldata.treasury.gov/services/api/fiscal_service"
OWNERSHIP = f"{BASE}/v1/accounting/tb/ofs2_estimated_ownership_treasury_securities"
DEBT_TO_PENNY = f"{BASE}/v2/accounting/od/debt_to_penny"

BILLION = 1e9

#: Rows that are subtotals rather than holder categories. Keeping them in a breakdown chart
#: would double-count, so they are separated out as context values.
TOTAL_ROWS = {"Total Public Debt", "Total Privately Held"}
FEDERAL_ROW = "Federal Reserve And Government Accounts"

#: Presentation grouping. "Other Investors" is genuinely residual in the source -- it is
#: where hedge funds, brokers, corporations and individuals land, and Treasury does not
#: break it down further. It must never be labelled as any one of those.
HOLDER_GROUPS: dict[str, str] = {
    FEDERAL_ROW: "Central bank & government accounts",
    "Foreign And International": "Foreign & international",
    "Mutual Funds": "Mutual funds",
    "Depository Institutions": "Banks",
    "State And Local Governments": "State & local government",
    "Pension Funds - Private": "Pension funds",
    "Pension Funds - State And Local Governments": "Pension funds",
    "Insurance Companies": "Insurance",
    "U.S. Savings Bonds": "Savings bonds (households)",
    "Other Investors": "Other investors (incl. hedge funds, brokers, individuals)",
}


def _get(url: str, *, params: str = "", use_cache: bool = True) -> list[dict]:
    payload = fetch(f"{url}?{params}" if params else url, suffix=".json", use_cache=use_cache)
    return json.loads(payload).get("data", [])


def fetch_debt_totals(*, use_cache: bool = True) -> pd.DataFrame:
    """Daily total public debt: total, held by the public, intragovernmental."""
    rows = _get(
        DEBT_TO_PENNY,
        params="sort=-record_date&page%5Bsize%5D=400",
        use_cache=use_cache,
    )
    if not rows:
        raise ValueError("debt_to_penny returned no rows")

    frame = pd.DataFrame(rows)
    numeric = {
        "tot_pub_debt_out_amt": "total",
        "debt_held_public_amt": "held_by_public",
        "intragov_hold_amt": "intragovernmental",
    }
    for source_col in numeric:
        frame[source_col] = pd.to_numeric(frame[source_col], errors="coerce")

    out = frame.rename(columns={"record_date": "date", **numeric})[
        ["date", "total", "held_by_public", "intragovernmental"]
    ].dropna(subset=["total"])
    out["country"] = "USA"
    out["source"] = "ust_debt_to_penny"
    return out.sort_values("date").reset_index(drop=True)


def fetch_ownership(*, use_cache: bool = True) -> pd.DataFrame:
    """Quarterly holder breakdown of US Treasury securities, by observation period."""
    rows = _get(
        OWNERSHIP,
        params="sort=-record_date&page%5Bsize%5D=2000",
        use_cache=use_cache,
    )
    if not rows:
        raise ValueError("OFS-2 returned no rows")

    frame = pd.DataFrame(rows)
    frame["usd"] = pd.to_numeric(frame["securities_bil_amt"], errors="coerce") * BILLION
    frame = frame.rename(columns={"end_of_month": "period", "securities_owner": "holder"})
    # Deliberately drop record_date: it is the publication date and mixes periods.
    frame = frame[["period", "holder", "usd"]].dropna(subset=["usd"])
    frame["country"] = "USA"
    frame["group"] = frame["holder"].map(HOLDER_GROUPS)
    frame["source"] = "ust_ofs2"
    return frame.drop_duplicates(subset=["period", "holder"]).sort_values("period")


def latest_complete_period(ownership: pd.DataFrame) -> str:
    """Newest period whose detailed categories are populated, not just the totals.

    The most recent published quarter carries totals with ``null`` detail, so naively
    taking ``max(period)`` yields a breakdown that is almost entirely empty.
    """
    detail = ownership[~ownership["holder"].isin(TOTAL_ROWS | {FEDERAL_ROW})]
    counts = detail.groupby("period")["usd"].count()
    complete = counts[counts >= 8]
    if complete.empty:
        raise ValueError("no OFS-2 period has a complete holder breakdown")
    return str(complete.index.max())


def holder_breakdown(ownership: pd.DataFrame, period: str | None = None) -> dict:
    """Assemble one period into a chart-ready breakdown with reconciliation checks."""
    period = period or latest_complete_period(ownership)
    rows = ownership[ownership["period"] == period]
    by_holder = rows.set_index("holder")["usd"]

    total = float(by_holder.get("Total Public Debt", float("nan")))
    privately_held = float(by_holder.get("Total Privately Held", float("nan")))
    federal = float(by_holder.get(FEDERAL_ROW, float("nan")))

    categories = (
        rows[~rows["holder"].isin(TOTAL_ROWS)]
        .groupby("group", as_index=False)["usd"]
        .sum()
        .sort_values("usd", ascending=False)
    )

    # The categories must reconcile to the published total; a mismatch means the source
    # changed shape and the breakdown would be quietly wrong.
    residual = total - float(categories["usd"].sum())
    if pd.notna(total) and abs(residual) > 0.01 * total:
        log.warning(
            "OFS-2 %s categories do not reconcile: total %.1fB vs sum %.1fB",
            period,
            total / 1e9,
            categories["usd"].sum() / 1e9,
        )

    return {
        "country": "USA",
        "period": period,
        "total": total,
        "federal_and_government_accounts": federal,
        "privately_held": privately_held,
        "categories": [
            {"group": r.group, "usd": float(r.usd), "share": float(r.usd / total)}
            for r in categories.itertuples()
            if pd.notna(total) and total > 0
        ],
    }
