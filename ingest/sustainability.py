"""Debt sustainability indicators.

Turns stocks into something interpretable. A debt level alone says nothing -- Japan carries the
developed world's heaviest debt burden and has been stable for thirty years, while far smaller
euro-area debts became crises in 2010-12. What separates them is structure, so this module
computes the four things that actually distinguish them:

1. **debt / GDP** -- scale relative to the economy, the standard (if overused) yardstick.
2. **interest / revenue** -- the cash-flow burden. A better distress signal than the stock,
   because it is what a government must actually find each year.
3. **r - g** -- long-term yield minus nominal GDP growth. When positive, debt compounds faster
   than the economy can outgrow it and the ratio rises without new borrowing. This is the
   single most important dynamic in sovereign debt and it is absent from debt/GDP alone.
4. **foreign share + monetary sovereignty** -- who holds it, and whether the issuer can create
   the currency it owes. Euro-area members cannot; that is the structural fault line the
   2010-12 crisis exposed, and it is invisible to any purely quantitative ratio.

Deliberately NOT computed: any aggregate "crisis probability". Crisis timing is driven by
politics and liquidity on timescales no annual or semi-annual dataset can observe, so a single
score would imply predictive power this data does not have. These are vulnerability
*indicators*, and the UI must present them as such.
"""

from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)

#: Euro-area members: they issue debt in a currency no national authority controls, so they
#: lack a national lender of last resort. Empirically the decisive risk factor -- Belgium at
#: 61% foreign-held is structurally more exposed than Japan at 12% despite far less debt.
EURO_AREA_MEMBERS: frozenset[str] = frozenset(
    {
        "AUT", "BEL", "CYP", "DEU", "ESP", "EST", "FIN", "FRA", "GRC", "HRV", "IRL",
        "ITA", "LTU", "LUX", "LVA", "MLT", "NLD", "PRT", "SVK", "SVN",
    }
)

#: Issuers of major reserve currencies. Foreign demand for these is structurally different:
#: much of it is official reserve management that is relatively price-insensitive, so a rising
#: foreign share is far less threatening than for a non-reserve issuer.
RESERVE_CURRENCY_ISSUERS: frozenset[str] = frozenset({"USA", "JPN", "GBR", "CHE"})


def monetary_sovereignty(country: str) -> str:
    """Can this issuer create the currency its debt is denominated in?"""
    if country in RESERVE_CURRENCY_ISSUERS:
        return "reserve_currency"
    if country in EURO_AREA_MEMBERS:
        return "none"  # currency controlled by the ECB, not the member state
    return "own_currency"


def build(
    debt: pd.DataFrame,
    macro: pd.DataFrame,
    rates: pd.DataFrame,
) -> pd.DataFrame:
    """Join debt stocks, macro indicators and yields into per-country vulnerability rows.

    ``debt`` is the BIS government debt-securities frame (country, period, usd, foreign_usd,
    foreign_share); ``macro`` the World Bank wide frame; ``rates`` the combined rates frame.
    """
    # Latest quarter per country, reduced to a calendar year for joining to annual macro data.
    latest_debt = (
        debt.sort_values("period").groupby("country", as_index=False).tail(1).copy()
    )
    latest_debt["year"] = (
        latest_debt["period"].astype(str).str.slice(0, 4).astype(int)
    )

    # Take the latest non-null value PER INDICATOR, not the latest row.
    #
    # Coverage differs sharply between indicators (GDP 247 economies, interest/revenue 105), so
    # picking one "latest row" per country silently discarded every indicator that happened to
    # be missing in that particular year -- it left interest/revenue entirely null even though
    # 105 countries report it.
    indicator_columns = [
        c for c in macro.columns if c not in ("country", "year", "source")
    ]
    latest_macro = pd.DataFrame({"country": sorted(macro["country"].unique())})
    for column in indicator_columns:
        available = macro.dropna(subset=[column])
        newest = (
            available.sort_values("year")
            .groupby("country", as_index=False)
            .tail(1)[["country", column, "year"]]
            .rename(columns={"year": f"{column}_year"})
        )
        latest_macro = latest_macro.merge(newest, on="country", how="left")

    merged = latest_debt.merge(latest_macro, on="country", how="left", suffixes=("", "_macro"))

    # r: the long-term (10Y) yield, the marginal cost of new borrowing.
    long_rates = rates[(rates["kind"] == "yield") & (rates["tenor_months"] == 120)]
    latest_yield = (
        long_rates.sort_values("date").groupby("country", as_index=False).tail(1)[
            ["country", "pct"]
        ]
    ).rename(columns={"pct": "long_yield_pct"})
    merged = merged.merge(latest_yield, on="country", how="left")

    policy = rates[rates["kind"] == "policy"]
    latest_policy = (
        policy.sort_values("date").groupby("country", as_index=False).tail(1)[
            ["country", "pct"]
        ]
    ).rename(columns={"pct": "policy_rate_pct"})
    merged = merged.merge(latest_policy, on="country", how="left")

    merged["debt_pct_gdp"] = merged["usd"] / merged["gdp_usd"] * 100

    # r - g on the 3-year nominal growth mean; a single year is too noisy to read as a trend.
    if "nominal_growth_3y_pct" in merged.columns:
        merged["r_minus_g"] = merged["long_yield_pct"] - merged["nominal_growth_3y_pct"]
    else:
        merged["r_minus_g"] = pd.NA

    merged["monetary_sovereignty"] = merged["country"].map(monetary_sovereignty)

    if "reserves_usd" in merged.columns and "short_term_external_debt_usd" in merged.columns:
        # Short-term external debt vs reserves: the classic emerging-market crisis predictor.
        # Below 1 means reserves cannot cover a year of external refinancing.
        merged["reserve_cover"] = merged["reserves_usd"] / merged[
            "short_term_external_debt_usd"
        ]

    return merged


#: Thresholds are conventional reference points, NOT predictions. They exist so the UI can say
#: "above the level usually treated as elevated" rather than implying a cliff edge. Japan sits
#: far beyond every debt threshold and is stable, which is exactly why no single flag is scored.
FLAGS: dict[str, tuple[str, float, str]] = {
    "debt_pct_gdp": ("Debt above 90% of GDP", 90.0, "above"),
    "interest_pct_revenue": ("Interest above 10% of revenue", 10.0, "above"),
    "r_minus_g": ("Yield above nominal growth (debt compounds)", 0.0, "above"),
    "foreign_share": ("Over half held by non-residents", 0.5, "above"),
    "reserve_cover": ("Reserves below one year of external refinancing", 1.0, "below"),
}


def flags(row: pd.Series) -> list[str]:
    """Reference-point breaches for one country. Descriptive, never a score."""
    out = []
    for column, (label, threshold, direction) in FLAGS.items():
        value = row.get(column)
        if value is None or pd.isna(value):
            continue
        if (direction == "above" and value > threshold) or (
            direction == "below" and value < threshold
        ):
            out.append(label)
    if row.get("monetary_sovereignty") == "none":
        out.append("No national lender of last resort (euro area)")
    return out
