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

/** One bilateral edge. `instrument` records what it actually measures -- see the hybrid rule. */
export interface Edge {
  creditor: string
  debtor: string
  usd: number
  prev_usd: number | null
  /** `government` = sovereign bonds only. `all_debt` = government + corporate + bank. */
  instrument: 'government' | 'all_debt'
  conduit: boolean
  source: string
}

export interface CountryNetwork {
  country: string
  period: string
  holds: Edge[]
  held_by: Edge[]
}

export interface NetworkIndexEntry {
  holds: number
  held_by: number
  total_holds: number
  total_held_by: number
  conduit: boolean
  government_only: boolean
}

export interface RatePoint {
  country: string
  kind: 'policy' | 'yield'
  tenor_months: number | null
  pct: number
  date: string
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
