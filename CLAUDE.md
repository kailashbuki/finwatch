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

## Edges carry BOTH measurement bases — never collapse them

Each `holdings` edge has:

- `usd` — **all debt securities** (government + corporate + bank), PIP `COUNTERPART_SECTOR=S1`.
  Reported by essentially every reporter, so this is the comparable basis for width, ranking
  and **totals**.
- `usd_government` — the government-only subset, PIP `COUNTERPART_SECTOR=S13`. Available for
  only **28 of 85** reporters (not Japan, China, the UK, Luxembourg, Switzerland).

**Do not collapse these into one column.** An earlier version preferred `government` where
available and fell back to `all_debt`, which made any total a sum of apples and oranges: the UI
showed $8.99T for foreign holdings of US debt where the coherent all-debt figure is $10.00T.

## Never drop the unattributable bucket

PIP's `TX093` (SEFER + SSIO) holds foreign-exchange reserve managers' and international
organisations' holdings, which cannot be attributed to any one country. For the US that is
**$2.31T** — real foreign financing. Excluding aggregates is correct for a *bilateral map*, but
the total must add it back, so `network/<country>.json` carries `unattributed_held_by` and the
UI shows it as its own row. Total foreign holdings of US debt securities = $10.00T + $2.31T.

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

**Different quantities that must never be conflated.** All verified live:

| Quantity | Value | Source |
|---|---|---|
| US total public debt | $40.11T | Treasury Debt to the Penny |
| — held by the public / intragovernmental | $32.40T / $7.71T | same |
| US govt **debt securities** (marketable) | $34.23T | BIS `WS_NA_SEC_DSS` |
| Foreign holdings of US **Treasuries** | $9.36T | Treasury OFS-2 |
| Non-resident held US govt debt securities | $9.42T | BIS, `COUNTERPART_AREA=5Z` |
| Foreign holdings of **all** US debt securities | $12.31T | IMF PIP (incl. $2.31T unattributable) |

The three foreign figures agreeing across independent collections ($9.36T / $9.42T / $10.00T
attributable) is the strongest correctness signal available; use it as a regression check.

**Treasury Fiscal Data OFS-2** — `record_date` is the **publication** date and several
observation periods share one; the real observation date is `end_of_month`. Grouping by
`record_date` silently mixes quarters and produced a $30.6T total instead of $39.1T. Also, the
newest published quarter has totals filled but detail `null` — use `latest_complete_period()`.

**BIS `WS_NA_SEC_DSS`** — 18 dimensions (17 dots). Under-pinning returns several different
numbers for the same country/period. Must pin `STO=LE` (stocks, not flows `F`), `MATURITY=T`,
`CURRENCY_DENOM=_T`, `CUST_BREAKDOWN=_T`, `CONSOLIDATION=N`. `COUNTERPART_AREA` is `XW` for all
holders and `5Z` for non-residents — that pair gives the foreign-held share for 45 areas. BIS
uses `U2` for the euro area here and `XM` in policy rates; both are aggregates and `U2` must be
excluded from country rankings or it double-counts France, Germany, Italy and Spain.

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

## Sustainability indicators (added)

`ingest/sustainability.py` computes debt/GDP, interest/revenue, **r − g**, reserve cover and
monetary sovereignty. Two rules:

- **`r − g` uses local-currency nominal growth**, never USD. `r` is a nominal local-currency
  rate; using USD growth injects exchange-rate moves into a domestic compounding condition and
  makes any depreciating currency look like it has negative nominal growth.
- **Never emit an aggregate crisis score.** Crisis timing turns on politics and liquidity that
  annual data cannot observe. Thresholds in `FLAGS` are conventional reference points; Japan
  breaches nearly all of them and has been stable for decades, which is the whole point.

Ranked output sorts by `r − g`, not debt level, because sorting by debt puts Japan (179% of GDP,
stable) top and buries South Africa (+4.1pp) and Brazil (30% of revenue on interest).

**World Bank**: latest non-null value **per indicator**, not the latest row per country.
Coverage differs sharply (GDP 247 economies, interest/revenue 105), so a single "latest row"
silently dropped every indicator missing in that year.

**OECD** rejects `Accept: ...;version=1.0.0` with HTTP 406 (Bundesbank *requires* it) and serves
GenericData XML for `*/*`. It also uses **SDMX-JSON 2.0** (`data.structures`, a list) where BIS
uses 1.0 (`data.structure`); `sdmx.json_to_frame` handles both. Its v4.0 history is only ~8
months deep, so long-yield history must come from national curves.

## Map interaction contract

- **Pinch = wheel + ctrlKey** (browsers set this synthetically). Plain wheel is a two-finger
  scroll and must pan/rotate, not zoom — treating every wheel event as zoom made trackpads
  unusable.
- Globe shading sits **on top of** the geography, so any opacity there is paid for in colour
  fidelity. Keep it subtle; at 0.95 it washed the choropleth out entirely.
- A pointer that moves >3px must not select a country on release, or panning reselects.
