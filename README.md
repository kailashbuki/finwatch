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

## Status

Working: IMF PIP bilateral holdings, BIS policy rates (49 areas), US and Japan full yield
curves, the focal flow map with ranked panel, scheduled refresh and deploy.

Not yet wired: OECD 10Y cross-section, ECB (`IRS`/`YC`/`FM`), Bundesbank, BoE, BIS debt
securities, TIC/CSLT, World Bank IDS, BIS CBS; the rates and per-country views; the chord view.
See `CLAUDE.md` for the endpoints, all verified live.
