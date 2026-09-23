# finwatch

An interactive dashboard of world government bond markets, built to answer one question:
**who is financing whom.** Yields, policy rates and debt outstanding are there to give that
dependency graph context.

Static site, no backend. Ingest runs in GitHub Actions on a schedule and publishes JSON that
the frontend reads; nothing runs on a developer machine.

## Quick start

```bash
uv sync --extra dev                    # Python ingest deps
uv run python -m ingest.build          # fetch upstreams -> data/dist/*.json
cd web && npm install && npm run dev   # http://localhost:5173
```

`web/public/data` is a symlink to `data/dist`, so a rebuild is picked up on reload.

```bash
uv run pytest -q             # connector tests -- offline, fixture-backed
uv run ruff check ingest/
cd web && npx tsc --noEmit
```

## Three numbers this dashboard keeps separate

A common way these dashboards mislead is by blurring these together:

| | Who sets it | How it behaves |
|---|---|---|
| **Policy rate** | The **central bank** decides it (Fed FOMC, ECB Governing Council, BoJ, BoE MPC). The Treasury has no role. | Administered; a step function |
| **Bond yield** | **Nobody.** The Treasury/DMO *issues* at auction; the yield is the clearing price and then trades continuously | Market price; continuous |
| **Coupon** | Fixed by the issuer at issuance | Irrelevant to the yield thereafter |

`rates.kind` (`policy` \| `yield`) makes this structural, and the two never share an axis.

## What an edge actually measures

No free source gives both broad coverage and government-only precision, so each edge is
labelled with what it measures and the UI distinguishes them (solid vs dashed):

| Pair | Source | Measures |
|---|---|---|
| 28 IMF PIP reporters → any | PIP `COUNTERPART_SECTOR=S13` | government bonds only |
| all other pairs | PIP `COUNTERPART_SECTOR=S1` | **all** debt securities (govt + corporate + bank) |

Only **28 of 85** PIP reporters break out issuer sector. Japan, China, the UK, Luxembourg and
Switzerland do not, so a government-only network is not globally achievable. An `all_debt`
edge is never presented as a government-bond figure.

## Two things that will mislead you if unflagged

**Conduit jurisdictions.** PIP records holdings by *residence of the immediate holder*, so
Luxembourg, Ireland, Cayman and Bermuda appear among the world's largest creditors because
funds are *domiciled* there. In the 2024 data, Cayman is the single largest apparent financier
of the United States at \$2.38T — a legal artifact, not Caymanians financing America. These
are kept in the data and flagged `⚠ conduit`, never silently dropped, because real flows do
route through them.

**Off-map financial centres.** Cayman, Bermuda, Hong Kong, Singapore, BVI and Jersey are
absent from the 110m world atlas yet hold some of the largest positions in the dataset. The
map alone would hide the biggest flows, so they get an explicit panel.

## Coverage ceilings

These are limits of the free data, surfaced in the UI rather than papered over:

- **No free dataset covers 50+ countries' bond yields.** ~44 areas monthly at the 10Y point
  (OECD) is the practical maximum.
- **Full yield curves** are free for the **US, Japan, Germany, UK** and the euro-area AAA
  block only. Everyone else gets a single 10Y point, monthly.
- **Policy rates** reach 49 areas daily (BIS) — the broadest thing here.
- Holdings data lags: PIP is semi-annual with a ~6 month lag.

`manifest.json` records per-source status and `as_of`; the UI renders freshness badges from it
so a stale or failed source is visible in the product.

## Layout

```
ingest/            Python 3.12 ETL (uv)
  sources/         one module per upstream; each raises on empty results
  sdmx.py          SDMX-ML and SDMX-JSON parsers
  normalize.py     alpha-3 codes, aggregates, conduits, net positions
  build.py         writes data/dist/ + manifest.json; per-source failure isolation
data/dist/         published artifacts -- the only contract with the frontend
web/               Vite + React + TypeScript
.github/workflows/ scheduled refresh -> hash-gated commit -> Pages deploy
```

Artifacts are split for the browser: ~55KB initial load (manifest, net positions, indexes)
with per-country series and network files fetched on demand. A naive records-per-row dump was
65MB.

Implementation conventions and the per-upstream API gotchas live in `CLAUDE.md`. Adding a
connector is covered by the `add-source` skill in `.claude/skills/`.

## Data sources and licensing

We publish a static site, so ingesting is redistributing. Confirmed clean: US Treasury and
Japan MOF (public domain), World Bank (CC BY 4.0), IMF / ECB / OECD / BIS (free with
attribution; BIS additionally forbids resale as a standalone paid product), Natural Earth
(public domain).

Deliberately **not** ingested: **FRED** (terms state API access does not grant redistribution
of third-party series, and OECD SDMX serves the same data with no key),
**WorldGovernmentBonds.com** (Investing.com / TradingEconomics upstream, all rights reserved),
and **AidData / Horn–Reinhart–Trebesch** China-lending datasets (excellent, but no explicit
open license — pending a decision).

## Why a matrix leads, not a map

The primary view is a who-finances-whom **matrix**, with the map demoted to a secondary tab.
This is an encoding decision, not a stylistic one:

- **The biggest positions belong to microstates.** Cayman ($2.13T net), Luxembourg, Ireland,
  Bermuda, Singapore and Hong Kong are invisible dots at any map scale, and four are absent
  from the 110m world atlas entirely. A map systematically under-represents exactly the most
  important entities.
- **A globe hides half the data by construction.** At any rotation the far hemisphere is not
  visible — a permanent handicap for comparing dozens of countries.
- **Most countries carry no signal.** On the choropleth, five countries have colour and the
  rest are pale; the information is not geographically distributed.

A matrix gives every economy identical visual weight and shows all pairs simultaneously. Colour
carries order of magnitude in five labelled bands; the printed number carries the value. The map
remains genuinely useful for geographic *context* and for the net-position choropleth.

Rejected: a Plotly/three.js 3D globe. It would add ~1MB to an 87KB bundle, cost the validated
palette, the no-data hatch, conduit flags and the accessibility work — and solve none of the
three problems above.

## Map interaction

- **Scroll or +/−** to zoom (1–12×), **drag** to pan, **⌂** to reset.
- **◍ Globe / ▭ Flat** toggles an orthographic globe. Drag to rotate; selecting a country
  spins it into view, which is required rather than decorative — a country on the far side
  would otherwise show no arcs at all.
- The globe is the truer view for flows: great circles on a sphere need no antimeridian
  clipping, so Japan→US visibly crosses the Pacific and the Arctic instead of being cut at the
  map edge. Note that a great circle through the centre of an orthographic projection projects
  to a straight line, so a centred country produces a starburst — that is correct geometry, not
  a rendering bug. Rotate slightly to see the curves.
- Zoom follows the selected country, so zooming in with Japan selected centres Japan.

## How much debt exists, and who holds it

Cross-border holdings alone are misleading without a denominator, so the dashboard shows both.
For the US (all verified live):

| | |
|---|---|
| Total public debt | **$40.11T** |
| — held by the public / intragovernmental | $32.40T / $7.71T |
| Govt debt securities (marketable, BIS) | $34.23T |
| — held by non-residents | $9.42T (27.5%) |

…plus every holder category from Treasury OFS-2: central bank and government accounts 30.8%,
foreign and international 23.9%, other investors 17.5%, mutual funds 13.1%, banks 5.6%, state
and local government 4.2%, pension funds 3.0%, insurance 1.5%, savings bonds 0.4%.

BIS gives total and non-resident-held government debt securities for **45 areas**, so the
foreign share is available cross-country — Japan 12.1%, US 27.5%, Germany 52.9%, Belgium 60.9%.

**Drill-down stops at sector level, by necessity.** No free official source identifies
individual institutions or hedge funds. Hedge funds fall inside Treasury's residual "Other
investors" (17.5%) and are never broken out; 13F filings cover US-listed equities, not sovereign
bonds. Anything finer needs a commercial feed.

## Status

Working: IMF PIP bilateral holdings, BIS policy rates (49 areas), BIS government debt
outstanding and foreign share (45 areas), Treasury debt totals and full holder breakdown, US and
Japan yield curves, the focal flow map with ranked panel and debt panel, scheduled refresh and deploy.

Not yet wired: OECD 10Y cross-section, ECB (`IRS`/`YC`/`FM`), Bundesbank, BoE, TIC/CSLT, World
Bank IDS, BIS CBS; per-country holder sectors from PIP's `SECTOR` dimension (which would extend
the holder breakdown beyond the US); the rates and per-country views; the chord view. See
`CLAUDE.md` for the endpoints, all verified live.
