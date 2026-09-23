/**
 * Who-finances-whom matrix -- the primary view.
 *
 * Chosen over a map because a map is the wrong encoding for this data, not merely a duller one:
 * the largest positions belong to Cayman, Luxembourg, Ireland, Bermuda, Singapore and Hong Kong,
 * which are invisible dots at any map scale and four of which are absent from the world atlas
 * entirely. A matrix gives every economy identical visual weight and shows all pairs at once.
 *
 * Encoding follows the dataviz rules: magnitude gets a **sequential** ramp (one hue, light to
 * dark), never the diverging one -- holdings have no meaningful zero-crossing. Exact values live
 * in the cells and the tooltip, because colour alone cannot carry five orders of magnitude.
 */

import { useMemo, useState } from 'react'

import type { Matrix } from '../lib/data'
import { formatUSD } from '../lib/data'
import { type Mode, chrome, sequential, status } from '../lib/palette'

type SortKey = 'holds' | 'held_by' | 'alpha'

const SORTS: { key: SortKey; label: string; hint: string }[] = [
  { key: 'holds', label: 'by lending', hint: 'largest creditors first' },
  { key: 'held_by', label: 'by borrowing', hint: 'largest debtors first' },
  { key: 'alpha', label: 'A–Z', hint: 'alphabetical' },
]

/**
 * Explicit order-of-magnitude bands rather than a continuous ramp.
 *
 * Two earlier attempts failed for opposite reasons. Dividing `log10(usd)` by `log10(max)`
 * squashed the whole $1B-$1T range into the top third of the ramp. Normalising log between the
 * observed min and max spread it correctly, but a 9-step single-hue ramp is perceptually mushy
 * in a 21px cell -- adjacent steps were indistinguishable.
 *
 * Discrete decade bands fix both: five clearly separated fills, and a reader can decode any
 * cell from the legend without eyeballing a gradient. Colour carries the order of magnitude;
 * the printed number carries the value.
 */
const BANDS: { limit: number; label: string }[] = [
  { limit: 1e9, label: '<1' },
  { limit: 1e10, label: '1–10' },
  { limit: 1e11, label: '10–100' },
  { limit: 5e11, label: '100–500' },
  { limit: Infinity, label: '>500' },
]

/** Ramp indices chosen for maximum separation across five bands. */
const BAND_STEPS = [0, 2, 4, 6, 8]

function band(usd: number): number {
  for (let i = 0; i < BANDS.length; i += 1) if (usd < BANDS[i].limit) return i
  return BANDS.length - 1
}

export default function MatrixView({
  mode,
  matrix,
  focal,
  onSelect,
}: {
  mode: Mode
  matrix: Matrix | null
  focal: string | null
  onSelect: (country: string | null) => void
}) {
  const ink = chrome[mode]
  const ramp = sequential[mode]
  const [sort, setSort] = useState<SortKey>('holds')
  const [hover, setHover] = useState<{ row: number; col: number } | null>(null)

  const ordered = useMemo(() => {
    if (!matrix) return []
    const withIndex = matrix.countries.map((c, i) => ({ country: c, i }))
    if (sort === 'alpha') return [...withIndex].sort((a, b) => a.country.localeCompare(b.country))
    return [...withIndex].sort(
      (a, b) => (matrix.totals[b.country]?.[sort] ?? 0) - (matrix.totals[a.country]?.[sort] ?? 0),
    )
  }, [matrix, sort])

  if (!matrix) {
    return <p style={{ padding: 20, color: ink.textSecondary, fontSize: 13 }}>Loading matrix…</p>
  }

  const conduit = new Set(matrix.countries.filter((_, i) => matrix.conduit[i]))
  const hoveredCell =
    hover && matrix.cells[ordered[hover.row].i][ordered[hover.col].i]

  return (
    <div
      style={{
        display: 'grid',
        gridTemplateRows: 'auto minmax(0,1fr) auto',
        minHeight: 0,
        gap: 8,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 14, fontWeight: 650 }}>
          Who finances whom — <span style={{ color: ink.textSecondary, fontWeight: 400 }}>rows finance columns</span>
        </h2>
        <span style={{ fontSize: 11, color: ink.muted }}>
          IMF PIP {matrix.period} · top {matrix.countries.length} economies
        </span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 4 }}>
          {SORTS.map((s) => (
            <button
              key={s.key}
              onClick={() => setSort(s.key)}
              title={s.hint}
              style={{
                background: sort === s.key ? ink.grid : 'transparent',
                border: `1px solid ${sort === s.key ? ink.axis : ink.border}`,
                color: sort === s.key ? ink.textPrimary : ink.textSecondary,
                borderRadius: 5,
                padding: '2px 7px',
                fontSize: 10.5,
                cursor: 'pointer',
              }}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      <div style={{ overflow: 'auto', minHeight: 0 }}>
        <table
          style={{
            borderCollapse: 'separate',
            borderSpacing: 1,
            fontSize: 10,
            fontVariantNumeric: 'tabular-nums',
          }}
        >
          <thead>
            <tr>
              <th
                style={{
                  position: 'sticky',
                  left: 0,
                  top: 0,
                  zIndex: 3,
                  background: ink.surface,
                  fontSize: 9,
                  color: ink.muted,
                  fontWeight: 500,
                  textAlign: 'left',
                  padding: '0 6px 2px 0',
                }}
              >
                ↓ lends to →
              </th>
              {ordered.map((c, col) => (
                <th
                  key={c.country}
                  onClick={() => onSelect(c.country === focal ? null : c.country)}
                  onPointerEnter={() => setHover((h) => (h ? { ...h, col } : null))}
                  style={{
                    position: 'sticky',
                    top: 0,
                    zIndex: 2,
                    background: ink.surface,
                    color:
                      c.country === focal
                        ? ink.textPrimary
                        : hover?.col === col
                          ? ink.textPrimary
                          : ink.textSecondary,
                    fontWeight: c.country === focal ? 700 : 500,
                    fontSize: 9.5,
                    padding: '0 0 3px',
                    minWidth: 30,
                    cursor: 'pointer',
                    borderBottom: `2px solid ${c.country === focal ? ink.textPrimary : 'transparent'}`,
                  }}
                  title={`${c.country}${conduit.has(c.country) ? ' — conduit jurisdiction' : ''}`}
                >
                  {c.country.slice(0, 3)}
                  {conduit.has(c.country) && (
                    <span style={{ color: status.warning }}>*</span>
                  )}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ordered.map((r, row) => (
              <tr key={r.country}>
                <th
                  onClick={() => onSelect(r.country === focal ? null : r.country)}
                  onPointerEnter={() => setHover({ row, col: hover?.col ?? 0 })}
                  style={{
                    position: 'sticky',
                    left: 0,
                    zIndex: 1,
                    background: ink.surface,
                    textAlign: 'left',
                    fontWeight: r.country === focal ? 700 : 500,
                    fontSize: 9.5,
                    color:
                      r.country === focal || hover?.row === row
                        ? ink.textPrimary
                        : ink.textSecondary,
                    paddingRight: 6,
                    whiteSpace: 'nowrap',
                    cursor: 'pointer',
                    borderRight: `2px solid ${r.country === focal ? ink.textPrimary : 'transparent'}`,
                  }}
                  title={`${r.country}: lends ${formatUSD(matrix.totals[r.country]?.holds ?? 0)}, borrows ${formatUSD(matrix.totals[r.country]?.held_by ?? 0)}`}
                >
                  {r.country}
                  {conduit.has(r.country) && <span style={{ color: status.warning }}>*</span>}
                </th>
                {ordered.map((c, col) => {
                  const cell = matrix.cells[r.i][c.i]
                  const self = r.i === c.i
                  const crosshair = hover?.row === row || hover?.col === col
                  if (self) {
                    return (
                      <td
                        key={c.country}
                        style={{
                          background: ink.grid,
                          height: 21,
                          opacity: 0.5,
                        }}
                      />
                    )
                  }
                  const b = cell ? band(cell.usd) : -1
                  const s = b >= 0 ? BAND_STEPS[b] : -1
                  // Ink on a dark fill must flip to stay legible.
                  const dark = b >= 3
                  return (
                    <td
                      key={c.country}
                      onPointerEnter={() => setHover({ row, col })}
                      onClick={() => onSelect(r.country === focal ? null : r.country)}
                      title={
                        cell
                          ? `${r.country} → ${c.country}: ${formatUSD(cell.usd)}${
                              cell.gov ? ` (government portion ${formatUSD(cell.gov)})` : ''
                            }`
                          : `${r.country} → ${c.country}: no reported holding`
                      }
                      style={{
                        background: cell ? ramp[s] : 'transparent',
                        color: dark
                          ? mode === 'light'
                            ? '#ffffff'
                            : '#dce8f6'
                          : ink.textSecondary,
                        textAlign: 'right',
                        padding: '1px 3px',
                        height: 21,
                        minWidth: 30,
                        cursor: 'pointer',
                        outline: crosshair ? `1px solid ${ink.axis}` : undefined,
                        fontSize: 9,
                      }}
                    >
                      {cell ? Math.round(cell.usd / 1e9) || '<1' : ''}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{ display: 'flex', gap: 16, alignItems: 'center', flexWrap: 'wrap', fontSize: 10.5, color: ink.muted }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
          <span style={{ color: ink.textSecondary }}>$B</span>
          {BANDS.map((bnd, i) => (
            <span key={bnd.label} style={{ display: 'flex', alignItems: 'center', gap: 3 }}>
              <span
                style={{
                  width: 13,
                  height: 10,
                  background: ramp[BAND_STEPS[i]],
                  borderRadius: 1,
                }}
              />
              {bnd.label}
            </span>
          ))}
        </span>
        <span>
          <span style={{ color: status.warning }}>*</span> conduit jurisdiction — reflects fund
          domicile, not residents financing anyone
        </span>
        <span>blank = no reported holding (not zero)</span>
        {hoveredCell && hover && (
          <span style={{ marginLeft: 'auto', color: ink.textPrimary, fontWeight: 600 }}>
            {ordered[hover.row].country} → {ordered[hover.col].country}:{' '}
            {formatUSD(hoveredCell.usd)}
          </span>
        )}
      </div>
    </div>
  )
}
