---
name: add-source
description: Wire a new upstream data source into the finwatch ingest layer. Use when adding a connector for a statistical API or file feed (SDMX, REST, CSV, XLSX, ZIP) — e.g. "add the ECB yield curve", "ingest World Bank IDS", "add a connector for BIS debt securities". Covers the probe-first procedure, the per-host quirk checklist, normalization to the canonical tables, and the offline golden-file test each connector must ship with.
---

# Adding a data source to finwatch

Connectors here fail in a specific, nasty way: **an upstream answers HTTP 200 with an empty
or wrong-format body instead of an error.** The whole procedure below exists to make that
impossible to ship. Probe before you write code; assert a known value in a test.

## Procedure

### 1. Probe with curl before writing any Python

Never write a connector against documentation. Get a real response first and record the
actual HTTP status, body size, and shape.

```bash
curl -sS "<url>" -o /tmp/probe.out -w "HTTP %{http_code} size=%{size_download}\n"
head -c 400 /tmp/probe.out
```

Check, in order:

- **Status 200 but tiny body?** Almost certainly an empty result set, not success. For SDMX
  that means a dimension code is wrong. Do not proceed until you get real observations.
- **Wrong format?** BIS and Bundesbank return SDMX-ML XML unless you send
  `Accept: application/vnd.sdmx.data+json` (Bundesbank needs `;version=1.0.0` or 406s).
  IMF PIP returns **HTTP 500** for SDMX-JSON — it is XML-only.
- **Encoding?** Try `utf-8`, then `cp932`. Japan MOF files are cp932.
- **Wildcards?** OECD and IMF wildcard a dimension with an **empty string**; the literal
  `all` returns 404.
- **Is the host cloud-IP blocked?** `www.imf.org` returns 403 from CI runners. If the host is
  blocked, find an API subdomain (`api.imf.org`) or the source is unusable — see `BLOCKED_HOSTS`.

### 2. Resolve codelists before building a key (SDMX only)

For SDMX sources, fetch the DSD and resolve the actual code values. Guessing costs more time
than resolving.

```bash
curl -sS "<base>/datastructure/<agency>/<dsd>/<version>?references=all" -o data/cache/dsd.xml
```

Then use `ingest.sdmx.codelist(path, "CL_SOMETHING")`. Note IMF codelists carry names in
several languages with **Arabic often first**, so `ingest.sdmx.english_name` exists — never
take the first `Name` child.

Count the dimensions and match the dot count exactly: PIP has 7 dimensions / 6 dots, and a
7th dot returns HTTP 400.

### 3. Write the module

One file per upstream in `ingest/sources/`. Requirements:

- Module docstring lists **every quirk you discovered, with the verified fact**, not a vague
  warning. Future readers must not have to re-probe. Look at `imf_pip.py` or `jgb_curve.py`.
- Expose `fetch_*(…, use_cache: bool = True) -> pd.DataFrame`.
- Fetch through `ingest.fetch.fetch` — it handles the `Accept` header per host, retries with
  backoff, caches to `data/cache/`, and refuses cloud-blocked hosts. Do not call `httpx` directly.
- Parse with `ingest.sdmx.to_frame` (XML) or `ingest.sdmx.json_to_frame` (JSON).
- **Raise on an empty frame.** This is the single most important line in a connector:
  ```python
  if frame.empty:
      raise ValueError(f"<source> returned no observations for key {key!r}")
  ```
- Return the canonical column names for the target table (below) — do the renaming in the
  connector, not downstream.
- Never hardcode a column set that the upstream can change. The US Treasury file added a
  "1.5 Month" tenor in 2026; parse tenors from the header.

### 4. Normalize to a canonical table

Four long-format tables; ISO **alpha-3** is the join key everywhere.

| Table | Columns |
|---|---|
| `holdings` | `creditor`, `debtor`, `usd`, `instrument`, `source`, `confidence`, `period` |
| `holders_by_class` | `debtor`, `class`, `usd`, `period` |
| `debt_outstanding` | `country`, `usd`, `pct_gdp`, `period` |
| `rates` | `country`, `kind` (`policy`\|`yield`), `tenor_months`, `pct`, `date` |

Two rules that are easy to get wrong:

- **`kind` is not cosmetic.** `policy` rates are administered by a central bank; `yield` is a
  market price. Never merge them into one series.
- **Codes need mapping.** BIS uses 2-letter codes (`US`, `JP`, `XM`); PIP uses alpha-3 plus
  `TX*`/`GX*` pseudo-economies. Aggregates go in the `aggregates` list and are never summed
  with real countries.

### 5. Capture a fixture and write an offline golden test

Tests must run with **no network**, so CI and refactors are not hostage to upstream uptime.

```bash
curl -sS "<small query url>" -o ingest/tests/fixtures/<source>_<slice>.<ext>
```

Keep fixtures small (a couple of countries, a few periods). For large files, truncate to a
header plus a handful of representative rows — include both an early row and a recent one if
the schema drifted over time.

Each connector's test must cover:

1. **A spot-checked value.** Assert a real number you verified live, with the date you
   verified it in a comment. This is what catches silent upstream changes.
2. **The quirk you handled.** If the file is cp932, assert that UTF-8 decoding *raises*. If
   tenors vary, assert the odd one parses. Encode the trap, not just the happy path.
3. **An accounting or ordering sanity check.** A subset must not exceed its total; a 30-year
   yield should not equal a 1-month yield; missing values must be dropped, never coerced to 0.

Inject the fixture by monkeypatching the module's `fetch`:

```python
monkeypatch.setattr(mod, "fetch", lambda *a, **k: raw)
```

### 6. Register and verify

- Add the source to the appropriate refresh tier (daily = rates; monthly = holdings/debt).
- Make sure `build.py` records it in `manifest.json` with `as_of`, row count and status, and
  that a failure marks it `stale` rather than failing the build.
- Run `uv run pytest -q` and `uv run ruff check ingest/`.

## Licensing — check before you ingest, not after

We publish a static site, so ingesting is **redistributing**. Before adding a source, confirm
it permits that. Already-decided exclusions (do not re-litigate without a reason):

- **FRED** — terms state API access does not grant redistribution of third-party series.
- **WorldGovernmentBonds.com** — sourced from Investing.com / TradingEconomics, all rights reserved.
- **AidData / Horn–Reinhart–Trebesch** — no explicit open license; pending a decision.

Clean and confirmed: US Treasury (public domain), World Bank (CC BY 4.0), ECB / OECD / BIS /
IMF (free with attribution; BIS additionally forbids reselling as a standalone paid product).

## Done means

- [ ] Probed live; actual status and shape recorded in the module docstring
- [ ] Raises on empty results
- [ ] Returns canonical columns with alpha-3 codes
- [ ] Fixture committed; tests pass offline
- [ ] A live-verified value asserted in a test
- [ ] Licensing confirmed to permit redistribution
- [ ] Registered in a refresh tier and in the manifest
