# finwatch — conventions and hard-won facts

A static dashboard of world government bond markets. Its purpose is to reveal **cross-border
financial dependency — who finances whom**; yields, policy rates and debt outstanding exist to give
that dependency graph context.

- `ingest/` — Python 3.12 ETL (uv). One module per upstream in `ingest/sources/`.
- `web/` — Vite + React + TypeScript static SPA.
- `data/dist/` — published JSON; the **only** contract between the layers. The frontend never calls
  an upstream API.
- Refresh runs **entirely in GitHub Actions**, never locally. Daily tier = rates; monthly tier = holdings.

## Three numbers that must never be conflated

1. **Policy rate** — *set* by the central bank (Fed FOMC, ECB Governing Council, BoJ, BoE MPC). An
   administered, decided number. The Treasury has no role in it.
2. **Bond yield** — *set by the market*. The Treasury/DMO issues at auction; the yield is the
   clearing price and then trades continuously. Nobody "sets" the 10Y.
3. **Coupon** — fixed at issuance, thereafter irrelevant to the yield.

`rates.kind` (`policy` | `yield`) keeps this structural. Render policy rates as **step** lines and
yields as **smooth** lines, on a **shared** percent axis — never a dual axis.

## Canonical data model

ISO **alpha-3** codes are the join key everywhere. Four long-format tables: `holdings`,
`holders_by_class`, `debt_outstanding`, `rates`. Non-countries (`EA20`, `XM`, PIP's `TX*`/`GX*`
pseudo-economies) live in an explicit `aggregates` list and must never be summed alongside real
economies or drawn on the map.

## The hybrid edge rule (decided, not provisional)

No single source gives both broad coverage and government-only precision, so each `holdings` edge
carries `instrument` (`government` | `all_debt`) and `source`, and the UI labels them differently:

| Pair | Source | `instrument` |
|---|---|---|
| any → USA | TIC/CSLT | `government` (Treasuries, monthly) |
| 28 PIP reporters → any | PIP `COUNTERPART_SECTOR=S13` | `government` |
| all other pairs | PIP `COUNTERPART_SECTOR=S1` | `all_debt` |

Never present an `all_debt` edge as a government-bond figure. The legend must distinguish them.

## Per-upstream gotchas (all verified live, 2026-09-23)

**IMF PIP** (ex-CPIS) — see the module docstring in `ingest/sources/imf_pip.py` for the full list.
The critical ones:
- Legacy `dataservices.imf.org` **no longer resolves**. Current service: `api.imf.org`, no auth.
- Country codes are **ISO alpha-3**. A 2-letter code returns **HTTP 200 with zero series**, not an
  error — the worst failure mode in this project. `fetch_bilateral` raises on empty results for
  exactly this reason; never remove that guard.
- SDMX-**JSON returns HTTP 500** on this dataflow. Parse SDMX-ML.
- 7 dimensions, 6 dots. A 7th dot → HTTP 400.
- `SECTOR` = **holder** sector; `COUNTERPART_SECTOR` = **issuer** sector.
- Only **28 of 85** reporters break out a government issuer sector. Japan, China, the UK,
  Luxembourg and Switzerland do not. Derive the list with `government_issuer_reporters()`.
- `ACCOUNTING_ENTRY=L` exists only for derived `*_SCC_*` indicators at total-economy level, so PIP
  **cannot** answer "who holds country X's government bonds" from the debtor side.

**BIS** and **Bundesbank** — return SDMX-ML XML unless you send
`Accept: application/vnd.sdmx.data+json`; Bundesbank needs `;version=1.0.0` or answers **HTTP 406**.
Encoded in `HOST_ACCEPT` in `ingest/fetch.py`.

**OECD** — wildcard a dimension with an **empty string**. The literal `all` returns 404.

**US Treasury yield curve** — `fiscaldata.treasury.gov` does **not** host it; every plausible dataset
name 404s. Only the legacy `home.treasury.gov` CSV/XML endpoint works.

**`www.imf.org` blocks cloud IPs with HTTP 403** — works locally, fails in CI. `BLOCKED_HOSTS` in
`ingest/fetch.py` refuses it outright. Use `api.imf.org` / `data.imf.org`.

## Never ingest

- **FRED** — its terms state API access "does not constitute permission" to redistribute
  third-party series, and the OECD 10Y series are flagged *Copyrighted: Citation Required*. We
  publish a static site, so we are redistributing. OECD SDMX serves identical data with no key.
- **WorldGovernmentBonds.com** — HTML-only and sourced from Investing.com / TradingEconomics with
  all rights reserved. Spot-checks by eye only.
- **AidData / Horn–Reinhart–Trebesch** — excellent China-creditor data, but no explicit open
  license. Pending a deliberate licensing decision, not a silent ingest.

## Coverage ceilings — surface these in the UI, don't paper over them

- No free dataset covers 50+ countries' bond yields. **~44 areas monthly** at the 10Y point is the
  practical maximum (OECD).
- Full multi-tenor yield curves are free for **US, Japan, Germany, UK** and the euro-area AAA block
  **only**. Everyone else gets a single 10Y point, monthly.
- `manifest.json` records per-source `as_of`, row count and status; the UI renders freshness badges
  from it so a stale or failed source is visible in the product rather than silently fresh-looking.

## Conduit jurisdictions

PIP records holdings by **residence of the immediate holder**, so Luxembourg, Ireland, Cayman and
the Netherlands appear as giant creditors because funds are *domiciled* there. Keep them in the
data, tag them `⚠ conduit`, explain the domicile bias in the tooltip. Look-through reallocation to
ultimate holders is out of scope for v1 and must never be mixed with reported data.

## Visualization

Load the **`dataviz` skill** before writing any chart code. Net creditor/debtor → diverging palette;
gross magnitude → sequential; country identity → categorical, fixed order, max 8. Validate with
`scripts/validate_palette.js` for light *and* dark. Arrow width answers "big vs small" only — every
network view needs the ranked table beside it for actual magnitudes.

## Commands

```bash
uv sync --extra dev          # install
uv run pytest -q             # golden-file tests (offline, use fixtures)
uv run ruff check ingest/    # lint
```

Connector tests must run **offline** against fixtures in `ingest/tests/fixtures/`, so they catch
parser regressions and schema drift without depending on upstream availability.
