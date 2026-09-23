"""Build the published artifacts in ``data/dist/``.

Design rule: **one failing upstream must never blank the site.** Each source runs isolated;
on failure the previously published artifact stays in place and the manifest marks it
``stale``. The build exits 0 so a scheduled CI run still deploys with the rest fresh.

Run with ``uv run python -m ingest.build [--tier daily|monthly|all]``.
"""

from __future__ import annotations

import argparse
import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from ingest import normalize, sustainability
from ingest.sources import (
    bis_cbpol,
    bis_debtsec,
    imf_pip,
    jgb_curve,
    oecd_finmark,
    ust_curve,
    ust_ownership,
    world_geo,
    worldbank,
)

log = logging.getLogger(__name__)

DIST = Path(__file__).resolve().parent.parent / "data" / "dist"

#: PIP is semi-annual with a ~6 month lag, so a few recent years is the useful window.
PIP_START = "2019"
UST_YEARS = list(range(2020, datetime.now(tz=UTC).year + 1))


@dataclass(frozen=True)
class Source:
    name: str
    tier: str  # "daily" | "monthly"
    table: str
    run: Callable[[], pd.DataFrame]


def _sources() -> list[Source]:
    return [
        Source("bis_cbpol", "daily", "rates", lambda: bis_cbpol.fetch_policy_rates()),
        Source("ust_curve", "daily", "rates", lambda: ust_curve.fetch_curve(years=UST_YEARS)),
        Source("jgb_curve", "daily", "rates", lambda: jgb_curve.fetch_curve()),
        Source("ust_debt", "daily", "debt_totals", lambda: ust_ownership.fetch_debt_totals()),
        Source(
            "oecd_finmark",
            "daily",
            "rates",
            lambda: oecd_finmark.fetch_long_term_yields(start="2020-01"),
        ),
        Source(
            "worldbank",
            "monthly",
            "macro",
            lambda: worldbank.nominal_growth(worldbank.fetch_all(start=2010)),
        ),
        Source(
            "imf_pip",
            "monthly",
            "holdings",
            lambda: imf_pip.fetch_bilateral(start=PIP_START),
        ),
        Source(
            "bis_debtsec",
            "monthly",
            "debt_outstanding",
            lambda: bis_debtsec.foreign_share(start="2015"),
        ),
        Source(
            "ust_ownership",
            "monthly",
            "holders_by_class",
            lambda: ust_ownership.fetch_ownership(),
        ),
    ]


def resolve_edges(holdings: pd.DataFrame) -> pd.DataFrame:
    """One row per (creditor, debtor, period), carrying **both** measurement bases.

    An earlier version collapsed the two into a single ``usd`` column, preferring the
    government figure where available. That was wrong in a way worth recording: the
    resulting column mixed government-only values (28 reporters) with all-debt values
    (the rest), so **any total over it summed apples and oranges** -- the UI showed
    $8.99T for foreign holdings of US debt where the coherent all-debt figure is $10.00T.

    So `usd_all_debt` (reported by every reporter) is the comparable basis used for
    thickness, ranking and totals, and `usd_government` is an optional extra detail
    shown alongside it. Neither is ever silently substituted for the other.
    """
    keys = ["creditor", "debtor", "period"]
    all_debt = (
        holdings[holdings["issuer_sector"] == "S1"][[*keys, "usd"]]
        .rename(columns={"usd": "usd_all_debt"})
        .drop_duplicates(subset=keys)
    )
    government = (
        holdings[holdings["issuer_sector"] == "S13"][[*keys, "usd"]]
        .rename(columns={"usd": "usd_government"})
        .drop_duplicates(subset=keys)
    )
    merged = all_debt.merge(government, on=keys, how="outer")

    # Comparable basis. all_debt is near-universally reported; fall back only if absent.
    merged["usd"] = merged["usd_all_debt"].fillna(merged["usd_government"])
    merged["basis"] = merged["usd_all_debt"].notna().map(
        {True: "all_debt", False: "government"}
    )
    merged["has_government"] = merged["usd_government"].notna()
    merged["source"] = "imf_pip"
    return merged.dropna(subset=["usd"]).reset_index(drop=True)


def unattributed_by_debtor(holdings: pd.DataFrame, period: str) -> pd.Series:
    """Holdings of each debtor that no single country can be credited with.

    Dominated by ``TX093`` (SEFER + SSIO): foreign-exchange reserve managers and
    international organisations. For the US this is **$2.31T** -- real foreign financing
    that a bilateral map structurally cannot place, so it must be reported as its own
    line rather than dropped, which is what an earlier version did.
    """
    current = holdings[
        (holdings["issuer_sector"] == "S1") & (holdings["period"] == period)
    ]
    aggregates = current[current["creditor"].map(normalize.is_aggregate)]
    real_debtors = aggregates[~aggregates["debtor"].map(normalize.is_aggregate)]
    return real_debtors.groupby("debtor")["usd"].sum()


def _write(name: str, payload: object) -> int:
    path = DIST / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(payload, separators=(",", ":"), allow_nan=False)
    path.write_text(text, encoding="utf-8")
    return len(text)


def _records(frame: pd.DataFrame) -> list[dict]:
    """Frame -> JSON-safe records, with NaN replaced by None."""
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _columnar(frame: pd.DataFrame, columns: list[str]) -> dict:
    """Encode a frame column-wise rather than as records.

    A row-per-object layout repeats every key on every row; for the rates history that is
    ~60% of the payload. The frontend zips these arrays back together.
    """
    return {c: json.loads(frame[c].to_json(orient="values")) for c in columns}


def downsample_history(frame: pd.DataFrame, *, daily_years: int = 3) -> pd.DataFrame:
    """Keep daily observations for recent years, month-end before that.

    A chart a few hundred pixels wide cannot render 50 years of daily points, so shipping
    them only costs download size. Recent history stays daily because that is what users
    zoom into.
    """
    if frame.empty or "date" not in frame.columns:
        return frame
    dates = pd.to_datetime(frame["date"], errors="coerce")
    cutoff = pd.Timestamp.now(tz=None).normalize() - pd.DateOffset(years=daily_years)

    recent = frame[dates >= cutoff]
    old = frame[dates < cutoff].copy()
    if not old.empty:
        old["_period"] = pd.to_datetime(old["date"]).dt.to_period("M")
        group = ["country", "_period"] + (["tenor_months"] if "tenor_months" in old else [])
        old = old.sort_values("date").groupby(group, dropna=False).tail(1).drop(columns="_period")
    return pd.concat([old, recent], ignore_index=True).sort_values("date")


def _emit_rates(combined: pd.DataFrame) -> None:
    """Write the rates artifacts: a small latest snapshot plus lazy per-country series."""
    # BIS ships alpha-2; everything else is already alpha-3.
    is_bis = combined["source"] == "bis_cbpol"
    combined.loc[is_bis, "country"] = normalize.bis_to_alpha3(
        combined.loc[is_bis, "country"], strict=False
    )
    combined = combined.dropna(subset=["country"])

    # Latest snapshot: one row per country/kind/tenor. Powers the default cross-section view.
    latest = (
        combined.sort_values("date")
        .groupby(["country", "kind", "tenor_months"], dropna=False)
        .tail(1)
    )
    _write("rates_latest", _records(latest[["country", "kind", "tenor_months", "pct", "date"]]))

    # Per-country series, downsampled and columnar, fetched on demand by the UI.
    slim = downsample_history(combined)
    index: dict[str, dict] = {}
    for country, group in slim.groupby("country"):
        payload = {
            "country": country,
            "policy": _columnar(
                group[group["kind"] == "policy"].sort_values("date"), ["date", "pct"]
            ),
            "yields": _columnar(
                group[group["kind"] == "yield"].sort_values("date"),
                ["date", "tenor_months", "pct"],
            ),
        }
        size = _write(f"series/{country}", payload)
        index[country] = {
            "bytes": size,
            "has_policy": bool((group["kind"] == "policy").any()),
            "tenors": sorted(
                {int(t) for t in group.loc[group["kind"] == "yield", "tenor_months"].dropna()}
            ),
            "as_of": str(group["date"].max()),
        }
    _write("series_index", index)
    log.info("wrote rates_latest.json and %d per-country series files", len(index))


def _emit_holdings(holdings: pd.DataFrame) -> None:
    """Write the network artifacts: latest-period edges plus per-country focal detail."""
    edges = resolve_edges(holdings)
    edges = normalize.annotate_conduits(edges, "creditor", "debtor")
    edges = normalize.drop_aggregates(edges, "creditor", "debtor")

    latest = edges["period"].max()
    current = edges[edges["period"] == latest].copy()
    previous = edges[edges["period"] < latest]

    # Unattributable foreign holdings, reported per debtor so totals can be honest.
    unattributed = unattributed_by_debtor(holdings, latest)

    _write("net_positions", _records(normalize.net_positions(current)))

    # One file per focal country: its inbound and outbound edges, ranked, with deltas.
    prior = (
        previous.sort_values("period")
        .groupby(["creditor", "debtor"])
        .tail(1)
        .set_index(["creditor", "debtor"])["usd"]
    )
    countries = sorted(set(current["creditor"]) | set(current["debtor"]))
    index: dict[str, dict] = {}
    for country in countries:
        holds = current[current["creditor"] == country].copy()
        held_by = current[current["debtor"] == country].copy()
        for frame in (holds, held_by):
            keys = list(zip(frame["creditor"], frame["debtor"], strict=False))
            frame["prev_usd"] = [prior.get(k) for k in keys]
            frame.sort_values("usd", ascending=False, inplace=True)
        cols = [
            "creditor",
            "debtor",
            "usd",
            "usd_government",
            "prev_usd",
            "basis",
            "has_government",
            "conduit",
            "source",
        ]
        _write(
            f"network/{country}",
            {
                "country": country,
                "period": latest,
                # Foreign holdings that no single country can be credited with, chiefly
                # reserve managers (SEFER) and international organisations (SSIO).
                "unattributed_held_by": float(unattributed.get(country, 0.0)),
                "holds": _records(holds[cols]),
                "held_by": _records(held_by[cols]),
            },
        )
        index[country] = {
            "holds": int(len(holds)),
            "held_by": int(len(held_by)),
            # Totals are on the all-debt basis only, so they are coherent to sum.
            "total_holds": float(holds["usd"].sum()),
            "total_held_by": float(held_by["usd"].sum()),
            "unattributed_held_by": float(unattributed.get(country, 0.0)),
            "conduit": normalize.is_conduit(country),
            # Share of this country's outbound edges that carry government-issuer detail.
            "government_detail": (
                float(holds["has_government"].mean()) if len(holds) else 0.0
            ),
        }
    _write("network_index", index)
    _write("periods", sorted(edges["period"].unique().tolist()))
    log.info(
        "wrote net_positions.json, %d per-country network files (period %s)", len(index), latest
    )


def _emit_debt(tables: dict[str, pd.DataFrame]) -> None:
    """Write the debt-outstanding artifacts: the denominator plus holder breakdowns.

    This is what lets the site state *how much debt exists* rather than only who holds the
    cross-border slice. Without it a $10T foreign-holdings figure sat with no context and
    invited comparison against the ~$40T total public debt headline -- a different measure.
    """
    outstanding = tables.get("debt_outstanding")
    if outstanding is not None and not outstanding.empty:
        frame = outstanding.copy()
        frame["country"] = normalize.bis_to_alpha3(frame["country"], strict=False)
        frame = frame.dropna(subset=["country"])

        latest = frame["period"].max()
        current = frame[frame["period"] == latest]
        _write(
            "debt_outstanding",
            {
                "period": latest,
                "note": (
                    "General government debt securities outstanding (BIS). Marketable "
                    "securities only, so below headline gross debt, which also includes "
                    "non-marketable and intragovernmental instruments. The foreign-held "
                    "cut is market-valued while the total is nominal, so the share is "
                    "approximate."
                ),
                "rows": _records(
                    current[["country", "usd", "foreign_usd", "foreign_share"]]
                ),
            },
        )
        # Per-country history for the drill-down.
        for country, group in frame.groupby("country"):
            _write(
                f"debt/{country}",
                _columnar(
                    group.sort_values("period"),
                    ["period", "usd", "foreign_usd", "foreign_share"],
                ),
            )
        log.info(
            "wrote debt_outstanding.json (%d countries, %s) and per-country history",
            current["country"].nunique(),
            latest,
        )

    totals = tables.get("debt_totals")
    if totals is not None and not totals.empty:
        recent = totals.tail(400)
        _write("debt_totals_usa", _columnar(recent, ["date", "total", "held_by_public",
                                                     "intragovernmental"]))

    macro = tables.get("macro")
    if outstanding is not None and macro is not None and not macro.empty:
        _emit_sustainability(outstanding, macro)

    ownership = tables.get("holders_by_class")
    if ownership is not None and not ownership.empty:
        breakdown = ust_ownership.holder_breakdown(ownership)
        _write("holders_usa", breakdown)
        log.info(
            "wrote holders_usa.json: total %.2fT across %d categories (%s)",
            breakdown["total"] / 1e12,
            len(breakdown["categories"]),
            breakdown["period"],
        )


def _emit_sustainability(outstanding: pd.DataFrame, macro: pd.DataFrame) -> None:
    """Write per-country debt sustainability indicators.

    Deliberately emits indicators and reference-point breaches, never an aggregate crisis
    score: crisis timing turns on politics and liquidity that annual data cannot observe, and a
    single number would imply predictive power this data does not have.
    """
    rates_path = DIST / "rates.json"
    rates_source = DIST / "rates_latest.json"
    if not rates_source.exists() and not rates_path.exists():
        log.warning("no rates artifact yet; skipping sustainability")
        return

    rates = pd.DataFrame(
        json.loads((rates_source if rates_source.exists() else rates_path).read_text())
    )

    debt = outstanding.copy()
    debt["country"] = normalize.bis_to_alpha3(debt["country"], strict=False)
    debt = debt.dropna(subset=["country"])

    table = sustainability.build(debt, macro, rates)
    table = table[~table["country"].map(normalize.is_aggregate)]
    table["flags"] = [sustainability.flags(row) for _, row in table.iterrows()]

    columns = [
        "country",
        "period",
        "usd",
        "foreign_usd",
        "foreign_share",
        "gdp_usd",
        "debt_pct_gdp",
        "interest_pct_revenue",
        "long_yield_pct",
        "policy_rate_pct",
        "nominal_growth_3y_pct",
        "r_minus_g",
        "reserve_cover",
        "monetary_sovereignty",
        "flags",
    ]
    present = [c for c in columns if c in table.columns]

    _write(
        "sustainability",
        {
            "note": (
                "Vulnerability indicators, not a forecast. Debt levels alone do not predict "
                "crises -- Japan carries the heaviest burden in the developed world and has "
                "been stable for decades, while smaller euro-area debts became crises in "
                "2010-12. What differs is structure: currency denomination, who holds the "
                "debt, and whether yields exceed nominal growth. Thresholds are conventional "
                "reference points, not cliff edges."
            ),
            "thresholds": {k: v[1] for k, v in sustainability.FLAGS.items()},
            "rows": _records(table[present].sort_values("debt_pct_gdp", ascending=False)),
        },
    )
    covered = int(table["debt_pct_gdp"].notna().sum())
    log.info("wrote sustainability.json (%d countries with debt/GDP)", covered)


def build(tier: str = "all") -> dict:
    """Run the requested tier and write artifacts. Returns the manifest."""
    manifest_path = DIST / "manifest.json"
    previous: dict = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8")).get("sources", {})

    manifest: dict[str, dict] = {}
    rates: list[pd.DataFrame] = []
    holdings: pd.DataFrame | None = None
    tables: dict[str, pd.DataFrame] = {}

    for source in _sources():
        if tier != "all" and source.tier != tier:
            # Not scheduled this run: carry the previous status forward untouched.
            if source.name in previous:
                manifest[source.name] = previous[source.name]
            continue

        started = time.monotonic()
        try:
            frame = source.run()
        except Exception as exc:  # noqa: BLE001 -- isolation is the point
            log.error("source %s failed: %s", source.name, exc)
            stale = dict(previous.get(source.name, {}))
            stale.update({"status": "stale", "error": str(exc)[:300]})
            stale.setdefault("rows", 0)
            manifest[source.name] = stale
            continue

        if source.table == "rates":
            rates.append(frame)
        elif source.table == "holdings":
            holdings = frame
        else:
            tables[source.table] = frame

        as_of = None
        for column in ("date", "period"):
            if column in frame.columns and len(frame):
                as_of = str(frame[column].max())
                break

        manifest[source.name] = {
            "status": "ok",
            "rows": int(len(frame)),
            "as_of": as_of,
            "fetched_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
            "duration_s": round(time.monotonic() - started, 1),
            "tier": source.tier,
        }
        log.info("source %s ok: %d rows, as_of=%s", source.name, len(frame), as_of)

    if rates:
        _emit_rates(pd.concat(rates, ignore_index=True))

    if holdings is not None and not holdings.empty:
        _emit_holdings(holdings)

    _emit_debt(tables)

    # Map geometry rarely changes, so emit it whenever it is missing rather than per tier.
    if not (DIST / "world.topo.json").exists():
        try:
            size = _write("world.topo", world_geo.fetch_world_topology())
            manifest["world_geo"] = {"status": "ok", "bytes": size, "tier": "static"}
        except Exception as exc:  # noqa: BLE001
            log.error("world geometry failed: %s", exc)
            manifest["world_geo"] = {"status": "stale", "error": str(exc)[:300]}

    payload = {
        "generated_at": datetime.now(tz=UTC).isoformat(timespec="seconds"),
        "tier": tier,
        "sources": manifest,
    }
    DIST.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tier", choices=("daily", "monthly", "all"), default="all")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)-7s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)

    manifest = build(args.tier)
    failed = [n for n, s in manifest["sources"].items() if s.get("status") != "ok"]
    if failed:
        log.warning("stale sources (previous artifacts retained): %s", ", ".join(failed))
    # Always exit 0: partial freshness still deploys.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
