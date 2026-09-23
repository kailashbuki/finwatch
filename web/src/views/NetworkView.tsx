/**
 * Focal flow map -- the headline "who finances whom" view.
 *
 * Why focal rather than all-edges: IMF PIP yields ~86k bilateral edges. Drawing them all
 * produces texture, not information. At rest the map is a choropleth of net creditor/debtor
 * position; clicking a country draws only ITS edges (~240 max), which stays legible.
 *
 * Direction is encoded by HUE, not by arrowheads or curvature. In a focal view the focal
 * country is one endpoint of every edge, so inbound/outbound hue determines direction
 * unambiguously. Paths are true great circles sampled in geographic space and projected,
 * so d3 clips them correctly at the antimeridian -- a 2D bezier would draw Japan->US
 * across Asia instead of the Pacific.
 */

import { geoCentroid, geoGraticule10, geoInterpolate, geoPath } from 'd3-geo'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { feature } from 'topojson-client'

import {
  INITIAL_VIEW,
  type ViewState,
  buildProjection,
  clampPhi,
  clampZoom,
  dragToRotation,
  rotationFor,
  shortestDelta,
  wrapLambda,
} from '../lib/mapview'

import {
  type CountryNetwork,
  type DebtOutstanding,
  type Edge,
  type HolderBreakdown,
  type Manifest,
  type NetPosition,
  type NetworkIndexEntry,
  formatDelta,
  formatUSD,
  loadCountryNetwork,
  loadDebtOutstanding,
  loadHoldersUSA,
  loadManifest,
  loadNetPositions,
  loadNetworkIndex,
  loadTopology,
} from '../lib/data'
import { type Mode, arcWidth, chrome, diverging, divergingColor, edgeRole, status } from '../lib/palette'
import DebtStrip from './DebtStrip'

/**
 * Measure a container so the map can fill the space actually available.
 *
 * A fixed viewBox left the map in a 2:1 box with dead space below it on any taller window.
 * The projection is refitted to the measured box instead.
 */
function useMeasure<T extends HTMLElement>() {
  const ref = useRef<T | null>(null)
  const [box, setBox] = useState({ width: 960, height: 480 })
  useEffect(() => {
    const element = ref.current
    if (!element) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      if (width > 40 && height > 40) setBox({ width, height })
    })
    observer.observe(element)
    return () => observer.disconnect()
  }, [])
  return [ref, box] as const
}

/** Great-circle path between two [lon, lat] points, as a GeoJSON LineString. */
function greatCircle(from: [number, number], to: [number, number]) {
  const interpolate = geoInterpolate(from, to)
  const steps = 48
  const coordinates = Array.from({ length: steps + 1 }, (_, i) => interpolate(i / steps))
  return { type: 'LineString' as const, coordinates }
}

interface Props {
  mode: Mode
}

export default function NetworkView({ mode }: Props) {
  const ink = chrome[mode]
  const roles = edgeRole[mode]

  const [topology, setTopology] = useState<any>(null)
  const [net, setNet] = useState<NetPosition[]>([])
  const [index, setIndex] = useState<Record<string, NetworkIndexEntry>>({})
  const [manifest, setManifest] = useState<Manifest | null>(null)
  const [focal, setFocal] = useState<string | null>(null)
  const [network, setNetwork] = useState<CountryNetwork | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [debt, setDebt] = useState<DebtOutstanding | null>(null)
  const [holders, setHolders] = useState<HolderBreakdown | null>(null)
  const liveRegion = useRef<HTMLDivElement>(null)

  useEffect(() => {
    Promise.all([loadTopology(), loadNetPositions(), loadNetworkIndex(), loadManifest()])
      .then(([topo, positions, idx, mf]) => {
        setTopology(topo)
        setNet(positions)
        setIndex(idx)
        setManifest(mf)
      })
      .catch((e) => setError(String(e)))

    // Debt context loads independently: if BIS is unavailable the map still works.
    loadDebtOutstanding().then(setDebt).catch(() => setDebt(null))
    loadHoldersUSA().then(setHolders).catch(() => setHolders(null))
  }, [])

  useEffect(() => {
    if (!focal) {
      setNetwork(null)
      return
    }
    let cancelled = false
    loadCountryNetwork(focal)
      .then((data) => !cancelled && setNetwork(data))
      .catch(() => !cancelled && setNetwork(null))
    return () => {
      cancelled = true
    }
  }, [focal])

  const [mapRef, box] = useMeasure<HTMLDivElement>()

  const [view, setView] = useState<ViewState>(INITIAL_VIEW)
  const projection = useMemo(
    () => buildProjection(view, box.width, box.height),
    [view, box],
  )
  const path = useMemo(() => geoPath(projection), [projection])
  const graticule = useMemo(() => geoGraticule10(), [])

  /**
   * Antarctica is dropped, not just excluded from the fit. It has no sovereign issuer, so it
   * rendered as a wide "no data" hatch that ate roughly a sixth of the panel height.
   */
  const countries = useMemo(
    () =>
      topology
        ? (feature(topology, topology.objects.countries) as any).features.filter(
            (f: any) => f.id !== 'ATA',
          )
        : [],
    [topology],
  )

  const netByCountry = useMemo(
    () => new Map(net.map((r) => [r.country, r.net])),
    [net],
  )
  const maxAbsNet = useMemo(
    () => Math.max(1, ...net.map((r) => Math.abs(r.net))),
    [net],
  )

  /** Centroids for every country the map can draw, used as arc endpoints. */
  const centroids = useMemo(() => {
    const map = new Map<string, [number, number]>()
    for (const f of countries) map.set(f.id as string, geoCentroid(f) as [number, number])
    return map
  }, [countries])

  /**
   * Jurisdictions present in the data but absent from the 110m atlas -- Cayman, Bermuda,
   * Hong Kong, Singapore, BVI, Jersey. These are the LARGEST net creditors in the dataset,
   * so omitting them silently would hide the biggest flows. They get an explicit strip.
   */
  const offMap = useMemo(() => {
    if (!countries.length || !net.length) return []
    const drawable = new Set(countries.map((f: any) => f.id as string))
    return net.filter((r) => !drawable.has(r.country)).sort((a, b) => Math.abs(b.net) - Math.abs(a.net))
  }, [countries, net])

  /**
   * Top-N cap per direction. A focal country can have 300+ counterparties (the US holds debt
   * of 238), and drawing all of them reproduces the hairball the focal view exists to avoid.
   * The long tail is negligible in value but dominates the ink, so it lives in the table only.
   */
  const ARC_CAP = 15

  const edges = useMemo(() => {
    if (!network) return []
    const drawable = (list: Edge[]) =>
      list
        .filter((e) => centroids.has(e.creditor) && centroids.has(e.debtor))
        .slice(0, ARC_CAP)
    return [
      ...drawable(network.held_by).map((e) => ({ ...e, direction: 'inbound' as const })),
      ...drawable(network.holds).map((e) => ({ ...e, direction: 'outbound' as const })),
    ]
  }, [network, centroids])

  /** How many edges exist but are not drawn, so the omission is stated rather than hidden. */
  const hiddenEdges = useMemo(() => {
    if (!network) return 0
    const drawableCount = (list: Edge[]) =>
      list.filter((e) => centroids.has(e.creditor) && centroids.has(e.debtor)).length
    return (
      Math.max(0, drawableCount(network.held_by) - ARC_CAP) +
      Math.max(0, drawableCount(network.holds) - ARC_CAP)
    )
  }, [network, centroids])

  const maxEdge = useMemo(
    () => Math.max(1, ...edges.map((e) => e.usd)),
    [edges],
  )
  const connected = useMemo(
    () => new Set(edges.flatMap((e) => [e.creditor, e.debtor])),
    [edges],
  )

  // --- interaction: pan/zoom on the flat map, drag-to-rotate on the globe ---------------

  const drag = useRef<{ x: number; y: number; pointer: number } | null>(null)
  const animation = useRef<number | null>(null)
  const [grabbing, setGrabbing] = useState(false)
  /**
   * Set once a pointer moves beyond a few pixels, so releasing after a pan or rotate does not
   * also select whichever country happens to be under the cursor.
   */
  const moved = useRef(false)

  const cancelAnimation = () => {
    if (animation.current !== null) {
      cancelAnimationFrame(animation.current)
      animation.current = null
    }
  }

  const onPointerDown = (event: React.PointerEvent<SVGSVGElement>) => {
    cancelAnimation()
    drag.current = { x: event.clientX, y: event.clientY, pointer: event.pointerId }
    moved.current = false
    setGrabbing(true)
    event.currentTarget.setPointerCapture(event.pointerId)
  }

  const onPointerMove = (event: React.PointerEvent<SVGSVGElement>) => {
    const start = drag.current
    if (!start) return
    const dx = event.clientX - start.x
    const dy = event.clientY - start.y
    if (Math.abs(dx) + Math.abs(dy) > 3) moved.current = true
    drag.current = { ...start, x: event.clientX, y: event.clientY }

    setView((v) => {
      if (v.mode === 'globe') {
        const { dLambda, dPhi } = dragToRotation(dx, dy, v.k)
        return { ...v, lambda: wrapLambda(v.lambda + dLambda), phi: clampPhi(v.phi + dPhi) }
      }
      return { ...v, x: v.x + dx, y: v.y + dy }
    })
  }

  const onPointerUp = (event: React.PointerEvent<SVGSVGElement>) => {
    drag.current = null
    setGrabbing(false)
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId)
    }
  }

  const selectCountry = (id: string) => {
    if (moved.current) return // the pointer was dragged, not clicked
    setFocal((current) => (current === id ? null : id))
  }

  const onWheel = (event: React.WheelEvent<SVGSVGElement>) => {
    event.preventDefault()
    cancelAnimation()
    const factor = Math.exp(-event.deltaY * 0.002)
    setView((v) => {
      const k = clampZoom(v.k * factor)
      if (v.mode === 'globe') return { ...v, k }
      // Keep the point under the cursor fixed while zooming the flat map.
      const rect = event.currentTarget.getBoundingClientRect()
      const px = event.clientX - rect.left
      const py = event.clientY - rect.top
      const ratio = k / v.k
      return { ...v, k, x: px - (px - v.x) * ratio, y: py - (py - v.y) * ratio }
    })
  }

  /**
   * Projected position of the selected country in untransformed projection space, if any.
   * Zoom is a group transform, so the on-screen position is `p * k + (x, y)`.
   */
  const focalPoint = useCallback((): [number, number] | null => {
    const centre = focal && centroids.get(focal)
    if (!centre) return null
    const projected = projection(centre)
    return projected ? [projected[0], projected[1]] : null
  }, [focal, centroids, projection])

  const zoomBy = (factor: number) =>
    setView((v) => {
      const k = clampZoom(v.k * factor)
      if (v.mode === 'globe') return { ...v, k }

      const cx = box.width / 2
      const cy = box.height / 2
      const point = focalPoint()
      // With a country selected, zoom brings it to the centre -- otherwise zooming in with
      // Japan selected walked off to Africa. With nothing selected, hold the centre fixed.
      if (point) return { ...v, k, x: cx - point[0] * k, y: cy - point[1] * k }
      const ratio = k / v.k
      return { ...v, k, x: cx - (cx - v.x) * ratio, y: cy - (cy - v.y) * ratio }
    })

  const resetView = useCallback(() => {
    cancelAnimation()
    setView((v) => ({ ...INITIAL_VIEW, mode: v.mode }))
  }, [])

  const toggleMode = () =>
    setView((v) => ({ ...INITIAL_VIEW, mode: v.mode === 'flat' ? 'globe' : 'flat' }))

  /**
   * On the globe, spin the focal country into view.
   *
   * Without this, selecting a country on the far side shows nothing at all -- its arcs are
   * behind the horizon -- so this is a correctness requirement of globe mode, not polish.
   */
  useEffect(() => {
    if (view.mode !== 'globe' || !focal) return
    const centre = centroids.get(focal)
    if (!centre) return

    const target = rotationFor(centre)
    cancelAnimation()
    const from = { lambda: view.lambda, phi: view.phi }
    const dLambda = shortestDelta(from.lambda, target.lambda)
    const dPhi = target.phi - from.phi
    if (Math.abs(dLambda) < 0.5 && Math.abs(dPhi) < 0.5) return

    const started = performance.now()
    const duration = 600
    const step = (now: number) => {
      const t = Math.min(1, (now - started) / duration)
      // easeInOutCubic
      const e = t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2
      setView((v) =>
        v.mode === 'globe'
          ? {
              ...v,
              lambda: wrapLambda(from.lambda + dLambda * e),
              phi: clampPhi(from.phi + dPhi * e),
            }
          : v,
      )
      if (t < 1) animation.current = requestAnimationFrame(step)
      else animation.current = null
    }
    animation.current = requestAnimationFrame(step)
    return cancelAnimation
    // Intentionally keyed on focal/mode only: including view would restart the tween each frame.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focal, view.mode, centroids])

  useEffect(() => cancelAnimation, [])

  useEffect(() => {
    if (focal && network && liveRegion.current) {
      liveRegion.current.textContent =
        `${focal} selected. Holds ${network.holds.length} counterparties, ` +
        `held by ${network.held_by.length}.`
    }
  }, [focal, network])

  if (error) {
    return (
      <p style={{ color: status.critical, padding: 24 }}>
        Could not load data: {error}. Run <code>uv run python -m ingest.build</code> first.
      </p>
    )
  }
  if (!topology) return <p style={{ padding: 24, color: ink.textSecondary }}>Loading…</p>

  const entry = focal ? index[focal] : null
  const staleSources = manifest
    ? Object.entries(manifest.sources).filter(([, s]) => s.status !== 'ok')
    : []

  return (
    // Full-viewport shell: the page itself never scrolls, panels scroll internally. This is
    // what removes the dead band that appeared below a fixed-aspect map.
    <div
      style={{
        background: ink.plane,
        color: ink.textPrimary,
        height: '100dvh',
        display: 'grid',
        gridTemplateRows: 'auto minmax(0,1fr)',
        gap: 10,
        padding: '14px 16px 16px',
        boxSizing: 'border-box',
        overflow: 'hidden',
      }}
    >
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', paddingRight: 44 }}>
        <h1 style={{ margin: 0, fontSize: 18, fontWeight: 650 }}>Who finances whom</h1>
        <p style={{ margin: 0, color: ink.textSecondary, fontSize: 12 }}>
          Cross-border holdings of debt securities — click a country for its creditors and debtors.
          {manifest && ` Holdings as of ${manifest.sources.imf_pip?.as_of ?? '—'} (IMF PIP).`}
        </p>
        {staleSources.length > 0 && (
          <p style={{ margin: 0, fontSize: 11, color: status.warning }}>
            ⚠ stale: {staleSources.map(([n]) => n).join(', ')}
          </p>
        )}
      </header>

      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'minmax(0,1fr) 400px',
          gap: 12,
          minHeight: 0,
        }}
      >
        {/* Left column: map fills the free space, debt panel takes what it needs below. */}
        <div style={{ display: 'grid', gridTemplateRows: 'minmax(0,1fr) auto', gap: 10, minHeight: 0 }}>
        <section
          style={{
            background: ink.surface,
            border: `1px solid ${ink.border}`,
            borderRadius: 10,
            padding: 10,
            display: 'grid',
            gridTemplateRows: 'minmax(0,1fr) auto',
            minHeight: 0,
          }}
        >
          <div ref={mapRef} style={{ minHeight: 0, position: 'relative' }}>
          <MapToolbar
            mode={mode}
            view={view}
            onToggleMode={toggleMode}
            onZoom={zoomBy}
            onReset={resetView}
          />
          <svg
            viewBox={`0 0 ${box.width} ${box.height}`}
            style={{
              width: '100%',
              height: '100%',
              display: 'block',
              cursor: grabbing ? 'grabbing' : 'grab',
              touchAction: 'none',
            }}
            role="img"
            aria-label="World map of net creditor and debtor positions"
            onPointerDown={onPointerDown}
            onPointerMove={onPointerMove}
            onPointerUp={onPointerUp}
            onPointerCancel={onPointerUp}
            onWheel={onWheel}
          >
            <defs>
              {/*
                No-data hatch. Without this, "no data" and "net position near zero" render as
                two near-identical grays (dark mode: #2c2c2a vs #383835), so absent data reads
                as a real neutral value. A texture separates the two unambiguously in both
                modes and survives greyscale printing and forced-colors.
              */}
              <pattern
                id="no-data"
                width="6"
                height="6"
                patternTransform="rotate(45)"
                patternUnits="userSpaceOnUse"
              >
                <rect width="6" height="6" fill={ink.plane} />
                <line x1="0" y1="0" x2="0" y2="6" stroke={ink.axis} strokeWidth="1.6" />
              </pattern>
            </defs>

            {/*
              Flat mode zooms by transforming this group, which keeps coastlines crisp and is
              far cheaper than reprojecting. Globe mode instead scales the projection itself,
              so the horizon stays a true circle -- hence the identity transform there.
            */}
            <g
              transform={
                view.mode === 'flat'
                  ? `translate(${view.x},${view.y}) scale(${view.k})`
                  : undefined
              }
            >
            {/* On the globe the sphere is a filled disc, giving the map an edge to read against. */}
            <path
              d={path({ type: 'Sphere' }) ?? ''}
              // Ocean is kept clearly cooler and darker than the palest choropleth steps, so
              // land still reads against sea where a country's net position is near zero.
              fill={view.mode === 'globe' ? (mode === 'light' ? '#dde6f0' : '#0b1015') : 'none'}
              stroke={ink.grid}
              vectorEffect="non-scaling-stroke"
            />
            {view.mode === 'globe' && (
              <path
                d={path(graticule) ?? ''}
                fill="none"
                stroke={ink.grid}
                strokeWidth={0.5}
                vectorEffect="non-scaling-stroke"
              />
            )}

            {countries.map((f: any) => {
              const value = netByCountry.get(f.id)
              const dim = focal !== null && !connected.has(f.id) && f.id !== focal
              return (
                <path
                  key={f.id}
                  d={path(f) ?? ''}
                  fill={
                    value === undefined
                      ? 'url(#no-data)'
                      : divergingColor(value, maxAbsNet, mode)
                  }
                  stroke={f.id === focal ? ink.textPrimary : ink.surface}
                  strokeWidth={f.id === focal ? 1.6 : 0.4}
                  vectorEffect="non-scaling-stroke"
                  opacity={dim ? 0.25 : 1}
                  style={{ cursor: 'pointer', transition: 'opacity .15s' }}
                  onClick={() => selectCountry(f.id)}
                  tabIndex={0}
                  role="button"
                  aria-label={`${f.properties?.name ?? f.id}: net position ${
                    value === undefined ? 'no data' : formatUSD(value)
                  }`}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      setFocal(f.id === focal ? null : f.id)
                    }
                  }}
                />
              )
            })}

            {/* Focal edges. A 2px surface-coloured casing separates overlapping arcs. */}
            <g fill="none" strokeLinecap="round">
              {edges.map((e) => {
                const from = centroids.get(e.creditor)!
                const to = centroids.get(e.debtor)!
                const d = path(greatCircle(from, to)) ?? ''
                const w = arcWidth(e.usd, maxEdge)
                return (
                  <g key={`${e.creditor}-${e.debtor}`}>
                    <path
                      d={d}
                      stroke={ink.surface}
                      strokeWidth={w + 2}
                      opacity={0.7}
                      vectorEffect="non-scaling-stroke"
                    />
                    <path
                      d={d}
                      stroke={roles[e.direction]}
                      strokeWidth={w}
                      opacity={0.85}
                      vectorEffect="non-scaling-stroke"
                    >
                      <title>
                        {e.creditor} → {e.debtor}: {formatUSD(e.usd)} (all debt securities
                        {e.usd_government
                          ? `; government portion ${formatUSD(e.usd_government)}`
                          : ''}
                        {e.conduit ? ', conduit jurisdiction' : ''})
                      </title>
                    </path>
                  </g>
                )
              })}
            </g>
            </g>
          </svg>
          </div>

          <div>
            <Legend mode={mode} focal={focal} />
            {focal && hiddenEdges > 0 && (
              <p style={{ margin: '3px 0 0', fontSize: 10.5, color: ink.muted }}>
                Showing the {ARC_CAP} largest flows each way; {hiddenEdges} smaller ones are in
                the table but not drawn, to keep the map legible.
              </p>
            )}
          </div>
        </section>

          <DebtStrip
            mode={mode}
            debt={debt}
            holders={holders}
            focal={focal}
            onSelect={setFocal}
          />
        </div>

        <aside
          style={{
            display: 'grid',
            gap: 10,
            gridAutoRows: 'min-content',
            overflowY: 'auto',
            minHeight: 0,
            paddingRight: 2,
          }}
        >
          <Panel mode={mode} title={focal ?? 'Select a country'}>
            {!focal && (
              <>
                <p style={{ color: ink.textSecondary, fontSize: 12.5, margin: '0 0 8px' }}>
                  The map shows <strong>net position</strong>: blue countries hold more of others'
                  debt than others hold of theirs; red are net debtors. Click one to drill in.
                </p>
                <p style={{ color: ink.muted, fontSize: 11.5, margin: 0 }}>
                  Holdings are cross-border only. The panel below gives total government debt and,
                  for the US, every holder category — so foreign holdings can be read as a share
                  of the whole rather than in isolation.
                </p>
              </>
            )}
            {focal && entry && (
              <>
                {entry.conduit && <ConduitWarning mode={mode} />}
                {entry.government_detail < 1 && (
                  <MixedDefinitionNote mode={mode} share={entry.government_detail} />
                )}
                <Ranked
                  mode={mode}
                  title="Financed by (holders of its debt)"
                  rows={network?.held_by ?? []}
                  nameOf={(e) => e.creditor}
                  accent={roles.inbound}
                  unattributed={network?.unattributed_held_by ?? 0}
                />
                <Ranked
                  mode={mode}
                  title="Finances (debt it holds)"
                  rows={network?.holds ?? []}
                  nameOf={(e) => e.debtor}
                  accent={roles.outbound}
                />
              </>
            )}
          </Panel>

          {offMap.length > 0 && <OffMapPanel mode={mode} rows={offMap} onSelect={setFocal} />}

          <Panel mode={mode} title="All net positions">
            <NetTable mode={mode} rows={net} onSelect={setFocal} />
          </Panel>
        </aside>
      </div>

      <div ref={liveRegion} aria-live="polite" style={{ position: 'absolute', left: -9999 }} />
    </div>
  )
}

function MapToolbar({
  mode,
  view,
  onToggleMode,
  onZoom,
  onReset,
}: {
  mode: Mode
  view: ViewState
  onToggleMode: () => void
  onZoom: (factor: number) => void
  onReset: () => void
}) {
  const ink = chrome[mode]
  const button = {
    background: ink.surface,
    border: `1px solid ${ink.border}`,
    color: ink.textSecondary,
    borderRadius: 6,
    width: 28,
    height: 26,
    fontSize: 13,
    cursor: 'pointer',
    display: 'grid',
    placeItems: 'center',
    lineHeight: 1,
  } as const
  const zoomed = view.k > 1.01 || view.x !== 0 || view.y !== 0

  return (
    <div
      style={{
        position: 'absolute',
        top: 6,
        right: 6,
        zIndex: 2,
        display: 'grid',
        gap: 4,
        justifyItems: 'end',
      }}
    >
      <button
        onClick={onToggleMode}
        style={{ ...button, width: 'auto', padding: '0 8px', fontSize: 11 }}
        title={
          view.mode === 'flat'
            ? 'Switch to globe — great-circle flows are geometrically true on a sphere'
            : 'Switch to flat map — shows every country at once'
        }
      >
        {view.mode === 'flat' ? '◍ Globe' : '▭ Flat'}
      </button>
      <button onClick={() => onZoom(1.5)} style={button} title="Zoom in" aria-label="Zoom in">
        +
      </button>
      <button onClick={() => onZoom(1 / 1.5)} style={button} title="Zoom out" aria-label="Zoom out">
        −
      </button>
      <button
        onClick={onReset}
        style={{
          ...button,
          borderColor: zoomed || view.mode === 'globe' ? ink.axis : ink.border,
        }}
        title="Reset view"
        aria-label="Reset view"
      >
        ⌂
      </button>
      <span
        style={{
          fontSize: 9.5,
          color: ink.muted,
          background: ink.surface,
          padding: '1px 4px',
          borderRadius: 4,
          fontVariantNumeric: 'tabular-nums',
        }}
      >
        {view.k.toFixed(1)}×
      </span>
    </div>
  )
}

function Panel({
  mode,
  title,
  children,
}: {
  mode: Mode
  title: string
  children: React.ReactNode
}) {
  const ink = chrome[mode]
  return (
    <section
      style={{
        background: ink.surface,
        border: `1px solid ${ink.border}`,
        borderRadius: 10,
        padding: 14,
      }}
    >
      <h2 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 650 }}>{title}</h2>
      {children}
    </section>
  )
}

function Legend({ mode, focal }: { mode: Mode; focal: string | null }) {
  const ink = chrome[mode]
  const roles = edgeRole[mode]
  const ramp = diverging[mode]
  return (
    <div style={{ display: 'flex', gap: 20, flexWrap: 'wrap', alignItems: 'center', marginTop: 8, fontSize: 11, color: ink.textSecondary }}>
      <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        net debtor
        <span style={{ display: 'flex' }}>
          {[...ramp].reverse().map((c) => (
            <span key={c} style={{ width: 12, height: 10, background: c }} />
          ))}
        </span>
        net creditor
      </span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
        <svg width="14" height="11" aria-hidden>
          <rect width="14" height="11" fill="url(#no-data)" stroke={ink.axis} strokeWidth="0.5" />
        </svg>
        no data
      </span>
      {focal && (
        <>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 18, height: 3, background: roles.inbound, borderRadius: 2 }} />
            financed by
          </span>
          <span style={{ display: 'flex', alignItems: 'center', gap: 5 }}>
            <span style={{ width: 18, height: 3, background: roles.outbound, borderRadius: 2 }} />
            finances
          </span>
          <span style={{ color: ink.muted }}>
            width ∝ √value, capped — read exact amounts in the table
          </span>
        </>
      )}
    </div>
  )
}

function ConduitWarning({ mode }: { mode: Mode }) {
  const ink = chrome[mode]
  return (
    <p
      style={{
        margin: '0 0 10px',
        padding: '8px 10px',
        borderLeft: `3px solid ${status.warning}`,
        background: mode === 'light' ? '#fdf6e3' : '#2a2617',
        fontSize: 12,
        color: ink.textSecondary,
        borderRadius: 4,
      }}
    >
      <strong style={{ color: ink.textPrimary }}>⚠ Conduit jurisdiction.</strong> Holdings are
      recorded by residence of the <em>immediate</em> holder, so funds merely domiciled here are
      counted as this country's claims. These figures reflect legal domicile, not residents
      financing anyone.
    </p>
  )
}

function MixedDefinitionNote({ mode, share }: { mode: Mode; share: number }) {
  const ink = chrome[mode]
  return (
    <p style={{ margin: '0 0 10px', fontSize: 11.5, color: ink.textSecondary }}>
      Figures below measure <strong>all debt securities</strong> (government, corporate and bank)
      so they are comparable across every pair.{' '}
      {share === 0
        ? 'No counterparty here reports a government-only breakdown (only 28 of 85 IMF PIP reporters do).'
        : `${Math.round(share * 100)}% of these counterparties also report a government-only figure, shown in the gov. column.`}
    </p>
  )
}

function Ranked({
  mode,
  title,
  rows,
  nameOf,
  accent,
  unattributed = 0,
}: {
  mode: Mode
  title: string
  rows: Edge[]
  nameOf: (e: Edge) => string
  accent: string
  /** Holdings no country can be credited with (reserve managers, intl. organisations). */
  unattributed?: number
}) {
  const ink = chrome[mode]
  const attributable = rows.reduce((sum, r) => sum + r.usd, 0)
  // The displayed total includes the unattributable bucket, because omitting it understated
  // real foreign financing -- for the US by $2.31T.
  const total = attributable + unattributed
  const shown = rows.slice(0, 12)
  return (
    <div style={{ marginBottom: 14 }}>
      <h3
        style={{
          margin: '0 0 6px',
          fontSize: 12,
          fontWeight: 600,
          color: ink.textSecondary,
          display: 'flex',
          alignItems: 'center',
          gap: 6,
        }}
      >
        <span style={{ width: 10, height: 3, background: accent, borderRadius: 2 }} />
        {title}
        <span style={{ marginLeft: 'auto', color: ink.muted, fontWeight: 400 }}>
          {formatUSD(total)}
        </span>
      </h3>
      {rows.length === 0 ? (
        <p style={{ margin: 0, fontSize: 12, color: ink.muted }}>No reported counterparties.</p>
      ) : (
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
          <tbody>
            {shown.map((e) => {
              const delta = formatDelta(e.usd, e.prev_usd)
              return (
                <tr key={`${e.creditor}-${e.debtor}`} style={{ borderTop: `1px solid ${ink.grid}` }}>
                  <td style={{ padding: '3px 0', fontVariantNumeric: 'tabular-nums' }}>
                    {nameOf(e)}
                    {e.conduit && (
                      <span title="Conduit jurisdiction — reflects fund domicile" style={{ color: status.warning }}>
                        {' '}⚠
                      </span>
                    )}
                  </td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                    {formatUSD(e.usd)}
                  </td>
                  <td
                    style={{
                      textAlign: 'right',
                      width: 52,
                      color: ink.muted,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                    title={
                      e.usd_government
                        ? 'Government-only portion of this holding'
                        : 'This reporter does not break out issuer sector'
                    }
                  >
                    {e.usd_government ? formatUSD(e.usd_government) : '—'}
                  </td>
                  <td
                    style={{
                      textAlign: 'right',
                      width: 38,
                      color: ink.muted,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {total > 0 ? `${((e.usd / total) * 100).toFixed(0)}%` : ''}
                  </td>
                  <td
                    style={{
                      textAlign: 'right',
                      width: 44,
                      color: ink.muted,
                      fontVariantNumeric: 'tabular-nums',
                    }}
                  >
                    {delta ?? ''}
                  </td>
                </tr>
              )
            })}
            {unattributed > 0 && (
              <tr style={{ borderTop: `1px solid ${ink.grid}` }}>
                <td
                  style={{ padding: '3px 0', fontStyle: 'italic', color: ink.textSecondary }}
                  title="Foreign-exchange reserve managers (SEFER) and international organisations (SSIO). PIP cannot attribute these to an individual country."
                >
                  Reserve managers &amp; intl. orgs.
                </td>
                <td
                  style={{
                    textAlign: 'right',
                    fontVariantNumeric: 'tabular-nums',
                    color: ink.textSecondary,
                  }}
                >
                  {formatUSD(unattributed)}
                </td>
                <td style={{ textAlign: 'right', color: ink.muted }}>—</td>
                <td
                  style={{
                    textAlign: 'right',
                    color: ink.muted,
                    fontVariantNumeric: 'tabular-nums',
                  }}
                >
                  {total > 0 ? `${((unattributed / total) * 100).toFixed(0)}%` : ''}
                </td>
                <td />
              </tr>
            )}
          </tbody>
        </table>
      )}
      {rows.length > shown.length && (
        <p style={{ margin: '4px 0 0', fontSize: 10.5, color: ink.muted }}>
          + {rows.length - shown.length} smaller counterparties. Columns: total / government-only
          portion / share / change.
        </p>
      )}
    </div>
  )
}

function OffMapPanel({
  mode,
  rows,
  onSelect,
}: {
  mode: Mode
  rows: NetPosition[]
  onSelect: (c: string) => void
}) {
  const ink = chrome[mode]
  return (
    <Panel mode={mode} title="Financial centres (not drawn on the map)">
      <p style={{ margin: '0 0 8px', fontSize: 12, color: ink.textSecondary }}>
        Too small to render at this scale, yet among the largest positions in the data. Shown here
        so the map does not hide them.
      </p>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {rows.slice(0, 12).map((r) => (
          <button
            key={r.country}
            onClick={() => onSelect(r.country)}
            style={{
              background: 'transparent',
              border: `1px solid ${ink.border}`,
              borderLeft: `3px solid ${divergingColor(r.net, Math.max(...rows.map((x) => Math.abs(x.net))), mode)}`,
              color: ink.textPrimary,
              borderRadius: 5,
              padding: '3px 7px',
              fontSize: 11,
              cursor: 'pointer',
              fontVariantNumeric: 'tabular-nums',
            }}
          >
            {r.country} {formatUSD(r.net)}
          </button>
        ))}
      </div>
    </Panel>
  )
}

function NetTable({
  mode,
  rows,
  onSelect,
}: {
  mode: Mode
  rows: NetPosition[]
  onSelect: (c: string) => void
}) {
  const ink = chrome[mode]
  return (
    <div style={{ maxHeight: 340, overflow: 'auto', marginTop: 8 }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ textAlign: 'left', color: ink.textSecondary }}>
            <th style={{ padding: 4 }}>Country</th>
            <th style={{ padding: 4, textAlign: 'right' }}>Claims</th>
            <th style={{ padding: 4, textAlign: 'right' }}>Liabilities</th>
            <th style={{ padding: 4, textAlign: 'right' }}>Net</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr
              key={r.country}
              style={{ borderTop: `1px solid ${ink.grid}`, cursor: 'pointer' }}
              onClick={() => onSelect(r.country)}
            >
              <td style={{ padding: 4 }}>{r.country}</td>
              <td style={{ padding: 4, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {formatUSD(r.claims)}
              </td>
              <td style={{ padding: 4, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {formatUSD(r.liabilities)}
              </td>
              <td style={{ padding: 4, textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {formatUSD(r.net)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
