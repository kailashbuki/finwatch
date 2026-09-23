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

from ingest import normalize
from ingest.sources import bis_cbpol, imf_pip, jgb_curve, ust_curve, world_geo

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
        Source(
            "imf_pip",
            "monthly",
            "holdings",
            lambda: imf_pip.fetch_bilateral(start=PIP_START),
        ),
    ]


def resolve_edges(holdings: pd.DataFrame) -> pd.DataFrame:
    """Apply the hybrid edge rule: one row per (creditor, debtor, period).

    Prefers the government-issuer figure where the reporter provides it, and falls back to
    the all-debt-securities total otherwise. The surviving row keeps ``instrument`` so the
    UI can label what each edge actually measures -- an ``all_debt`` edge must never be
    presented as a government-bond number.
    """
    relevant = holdings[holdings["issuer_sector"].isin(["S1", "S13"])].copy()
    # government (S13) sorts before all_debt (S1) so the first row per group wins.
    relevant["_rank"] = (relevant["instrument"] != "government").astype(int)
    relevant = relevant.sort_values("_rank")
    deduped = relevant.drop_duplicates(subset=["creditor", "debtor", "period"], keep="first")
    return deduped.drop(columns=["_rank", "issuer_sector", "holder_sector"], errors="ignore")


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
        cols = ["creditor", "debtor", "usd", "prev_usd", "instrument", "conduit", "source"]
        _write(
            f"network/{country}",
            {
                "country": country,
                "period": latest,
                "holds": _records(holds[cols]),
                "held_by": _records(held_by[cols]),
            },
        )
        index[country] = {
            "holds": int(len(holds)),
            "held_by": int(len(held_by)),
            "total_holds": float(holds["usd"].sum()),
            "total_held_by": float(held_by["usd"].sum()),
            "conduit": normalize.is_conduit(country),
            # True only if every edge is government-specific; mixed definitions must be visible.
            "government_only": bool(len(holds))
            and bool((holds["instrument"] == "government").all()),
        }
    _write("network_index", index)
    _write("periods", sorted(edges["period"].unique().tolist()))
    log.info(
        "wrote net_positions.json, %d per-country network files (period %s)", len(index), latest
    )


def build(tier: str = "all") -> dict:
    """Run the requested tier and write artifacts. Returns the manifest."""
    manifest_path = DIST / "manifest.json"
    previous: dict = {}
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8")).get("sources", {})

    manifest: dict[str, dict] = {}
    rates: list[pd.DataFrame] = []
    holdings: pd.DataFrame | None = None

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
