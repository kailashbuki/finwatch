/**
 * Loaders for the published artifacts in `data/dist/`.
 *
 * The frontend never calls an upstream API -- everything comes from our own JSON, so a
 * dead upstream degrades freshness (visible via the manifest) but never the site.
 * Per-country files are fetched on demand and cached in memory.
 */

const BASE = import.meta.env.BASE_URL + 'data'

export interface Manifest {
  generated_at: string
  tier: string
  sources: Record<
    string,
    { status: 'ok' | 'stale'; rows?: number; as_of?: string | null; error?: string; tier?: string }
  >
}

export interface NetPosition {
  country: string
  claims: number
  liabilities: number
  net: number
}

/**
 * One bilateral edge, carrying both measurement bases.
 *
 * `usd` is the comparable basis (all debt securities: government + corporate + bank) and is
 * reported by essentially every reporter, so it is safe to rank and total.
 * `usd_government` is the government-only subset, available for just 28 of 85 reporters.
 * The two are never substituted for one another -- mixing them into one column produced a
 * total that summed apples and oranges.
 */
export interface Edge {
  creditor: string
  debtor: string
  usd: number
  usd_government: number | null
  prev_usd: number | null
  basis: 'all_debt' | 'government'
  has_government: boolean
  conduit: boolean
  source: string
}

export interface CountryNetwork {
  country: string
  period: string
  /** Foreign holdings no single country can be credited with: reserve managers, intl. orgs. */
  unattributed_held_by: number
  holds: Edge[]
  held_by: Edge[]
}

export interface NetworkIndexEntry {
  holds: number
  held_by: number
  /** Totals are on the all-debt basis only, so they are coherent to sum. */
  total_holds: number
  total_held_by: number
  unattributed_held_by: number
  conduit: boolean
  /** Fraction of this country's outbound edges that carry government-issuer detail (0..1). */
  government_detail: number
}

export interface RatePoint {
  country: string
  kind: 'policy' | 'yield'
  tenor_months: number | null
  pct: number
  date: string
}

/** General government debt securities outstanding, and how much of it is foreign-held. */
export interface DebtRow {
  country: string
  usd: number
  foreign_usd: number | null
  foreign_share: number | null
}

export interface DebtOutstanding {
  period: string
  note: string
  rows: DebtRow[]
}

/** Holder categories for US Treasury securities (Treasury OFS-2). */
export interface HolderBreakdown {
  country: string
  period: string
  total: number
  federal_and_government_accounts: number
  privately_held: number
  categories: { group: string; usd: number; share: number }[]
}

async function getJSON<T>(path: string): Promise<T> {
  const response = await fetch(`${BASE}/${path}`)
  if (!response.ok) throw new Error(`${path}: HTTP ${response.status}`)
  return response.json() as Promise<T>
}

export const loadManifest = () => getJSON<Manifest>('manifest.json')
export const loadNetPositions = () => getJSON<NetPosition[]>('net_positions.json')
export const loadNetworkIndex = () => getJSON<Record<string, NetworkIndexEntry>>('network_index.json')
export const loadRatesLatest = () => getJSON<RatePoint[]>('rates_latest.json')
export const loadTopology = () => getJSON<any>('world.topo.json')

/**
 * Per-country vulnerability indicators. Note there is deliberately no score or probability:
 * crisis timing depends on politics and liquidity that annual data cannot observe.
 */
export interface SustainabilityRow {
  country: string
  period: string
  usd: number
  foreign_share: number | null
  gdp_usd: number | null
  debt_pct_gdp: number | null
  interest_pct_revenue: number | null
  long_yield_pct: number | null
  policy_rate_pct: number | null
  nominal_growth_3y_pct: number | null
  /** Long yield minus nominal GDP growth. Above zero, debt compounds faster than the economy. */
  r_minus_g: number | null
  reserve_cover: number | null
  monetary_sovereignty: 'reserve_currency' | 'own_currency' | 'none'
  flags: string[]
}

export interface Sustainability {
  note: string
  thresholds: Record<string, number>
  rows: SustainabilityRow[]
}

/** Dense creditor x debtor matrix for the largest economies. `null` = no reported holding. */
export interface MatrixCell {
  usd: number
  /** Government-only portion, where the reporter breaks out issuer sector. */
  gov: number | null
}

export interface Matrix {
  period: string
  countries: string[]
  conduit: boolean[]
  totals: Record<string, { holds: number; held_by: number }>
  cells: (MatrixCell | null)[][]
  note: string
}

export const loadMatrix = () => getJSON<Matrix>('matrix.json')

export const loadDebtOutstanding = () => getJSON<DebtOutstanding>('debt_outstanding.json')
export const loadSustainability = () =>
  getJSON<Sustainability>('sustainability.json').catch(() => null)

/** Optional: only the US has a full holder-class breakdown from a free source. */
export const loadHoldersUSA = () =>
  getJSON<HolderBreakdown>('holders_usa.json').catch(() => null)

const networkCache = new Map<string, Promise<CountryNetwork>>()

export function loadCountryNetwork(country: string): Promise<CountryNetwork> {
  let cached = networkCache.get(country)
  if (!cached) {
    cached = getJSON<CountryNetwork>(`network/${country}.json`)
    networkCache.set(country, cached)
  }
  return cached
}

/** Compact USD formatting. Magnitudes here span millions to trillions. */
export function formatUSD(value: number): string {
  const abs = Math.abs(value)
  const sign = value < 0 ? '-' : ''
  if (abs >= 1e12) return `${sign}$${(abs / 1e12).toFixed(2)}T`
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(1)}B`
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(0)}M`
  return `${sign}$${abs.toFixed(0)}`
}

export function formatDelta(current: number, previous: number | null): string | null {
  if (previous == null || previous === 0) return null
  const change = ((current - previous) / previous) * 100
  if (!Number.isFinite(change)) return null
  return `${change >= 0 ? '+' : ''}${change.toFixed(0)}%`
}
