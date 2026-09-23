/**
 * Debt sustainability panel.
 *
 * Shows the four things that actually distinguish a heavy but stable debt from a fragile one:
 * debt/GDP, interest as a share of revenue, `r - g`, and monetary sovereignty. Presented as
 * indicators with reference points, never as a score or probability -- crisis timing depends on
 * politics and liquidity that annual data cannot see.
 *
 * The ranking is by `r - g` rather than debt level, deliberately. Sorting by debt puts Japan
 * (179% of GDP, entirely stable for decades) at the top and buries South Africa and Brazil,
 * which is exactly the misreading this panel exists to prevent.
 */

import { useState } from 'react'

import type { Sustainability, SustainabilityRow } from '../lib/data'
import { formatUSD } from '../lib/data'
import { type Mode, chrome, status } from '../lib/palette'

const SOVEREIGNTY_LABEL: Record<string, string> = {
  reserve_currency: 'Reserve currency issuer',
  own_currency: 'Own currency',
  none: 'No national central bank (euro area)',
}

/** Colour by how the compounding condition sits, not by debt level. */
function rgTone(value: number | null, mode: Mode): string {
  if (value == null) return chrome[mode].muted
  if (value > 2) return status.critical
  if (value > 0) return status.serious
  return status.good
}

export default function SustainabilityPanel({
  mode,
  data,
  focal,
  onSelect,
}: {
  mode: Mode
  data: Sustainability | null
  focal: string | null
  onSelect: (country: string) => void
}) {
  const ink = chrome[mode]
  const [showAll, setShowAll] = useState(false)
  if (!data) return null

  const row = focal ? data.rows.find((r) => r.country === focal) : undefined
  if (focal) {
    if (!row) {
      return (
        <Card mode={mode} title={`${focal} — debt sustainability`}>
          <p style={{ margin: 0, fontSize: 11.5, color: ink.muted }}>
            Not covered. Requires both a BIS debt-securities total (45 areas) and World Bank GDP.
          </p>
        </Card>
      )
    }
    return (
      <Card mode={mode} title={`${focal} — debt sustainability`}>
        <FocalDetail mode={mode} row={row} />
      </Card>
    )
  }

  // Worst compounding condition first; countries without r-g fall to the end.
  const ranked = [...data.rows]
    .filter((r) => r.debt_pct_gdp != null)
    .sort((a, b) => (b.r_minus_g ?? -99) - (a.r_minus_g ?? -99))
  const shown = showAll ? ranked : ranked.slice(0, 10)

  return (
    <Card mode={mode} title="Debt sustainability">
      <p style={{ margin: '0 0 8px', fontSize: 11, color: ink.textSecondary }}>
        Ranked by <strong>r − g</strong> (yield minus nominal growth), not by debt level. Above
        zero, debt compounds faster than the economy grows.
      </p>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11.5 }}>
        <thead>
          <tr style={{ color: ink.muted, fontSize: 10, textAlign: 'right' }}>
            <th style={{ textAlign: 'left', fontWeight: 500 }}>Country</th>
            <th style={{ fontWeight: 500 }} title="Yield minus nominal GDP growth">
              r−g
            </th>
            <th style={{ fontWeight: 500 }} title="Government debt securities as % of GDP">
              debt/GDP
            </th>
            <th style={{ fontWeight: 500 }} title="Interest payments as % of government revenue">
              int/rev
            </th>
            <th style={{ fontWeight: 500 }} title="Reference points breached">
              flags
            </th>
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <tr
              key={r.country}
              onClick={() => onSelect(r.country)}
              style={{ borderTop: `1px solid ${ink.grid}`, cursor: 'pointer' }}
            >
              <td style={{ padding: '3px 0' }}>
                {r.country}
                {r.monetary_sovereignty === 'none' && (
                  <span title={SOVEREIGNTY_LABEL.none} style={{ color: status.warning }}>
                    {' '}€
                  </span>
                )}
              </td>
              <td
                style={{
                  textAlign: 'right',
                  fontVariantNumeric: 'tabular-nums',
                  color: rgTone(r.r_minus_g, mode),
                  fontWeight: r.r_minus_g != null && r.r_minus_g > 0 ? 650 : 400,
                }}
              >
                {r.r_minus_g == null ? '—' : `${r.r_minus_g > 0 ? '+' : ''}${r.r_minus_g.toFixed(1)}`}
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: ink.textSecondary }}>
                {r.debt_pct_gdp == null ? '—' : `${r.debt_pct_gdp.toFixed(0)}%`}
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', color: ink.textSecondary }}>
                {r.interest_pct_revenue == null ? '—' : `${r.interest_pct_revenue.toFixed(0)}%`}
              </td>
              <td style={{ textAlign: 'right', color: ink.muted, fontVariantNumeric: 'tabular-nums' }}>
                {r.flags.length || ''}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <button
        onClick={() => setShowAll((v) => !v)}
        style={{
          marginTop: 6,
          background: 'transparent',
          border: 'none',
          color: ink.muted,
          cursor: 'pointer',
          padding: 0,
          font: 'inherit',
          fontSize: 10.5,
        }}
      >
        {showAll ? 'Show fewer' : `Show all ${ranked.length}`}
      </button>
      <p style={{ margin: '8px 0 0', fontSize: 10, color: ink.muted, lineHeight: 1.45 }}>
        {data.note}
      </p>
    </Card>
  )
}

function FocalDetail({ mode, row }: { mode: Mode; row: SustainabilityRow }) {
  const ink = chrome[mode]
  const metrics: [string, string, string | null][] = [
    [
      'r − g',
      row.r_minus_g == null ? '—' : `${row.r_minus_g > 0 ? '+' : ''}${row.r_minus_g.toFixed(1)}pp`,
      row.r_minus_g == null
        ? null
        : row.r_minus_g > 0
          ? 'debt compounds faster than growth'
          : 'growth outpaces borrowing cost',
    ],
    [
      'Debt / GDP',
      row.debt_pct_gdp == null ? '—' : `${row.debt_pct_gdp.toFixed(0)}%`,
      row.gdp_usd ? `GDP ${formatUSD(row.gdp_usd)}` : null,
    ],
    [
      'Interest / revenue',
      row.interest_pct_revenue == null ? '—' : `${row.interest_pct_revenue.toFixed(1)}%`,
      'annual cash burden',
    ],
    [
      '10Y yield',
      row.long_yield_pct == null ? '—' : `${row.long_yield_pct.toFixed(2)}%`,
      row.nominal_growth_3y_pct == null
        ? null
        : `nominal growth ${row.nominal_growth_3y_pct.toFixed(1)}%`,
    ],
  ]

  return (
    <>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px 12px' }}>
        {metrics.map(([label, value, hint]) => (
          <div key={label}>
            <div style={{ fontSize: 9.5, color: ink.muted, textTransform: 'uppercase', letterSpacing: 0.4 }}>
              {label}
            </div>
            <div
              style={{
                fontSize: 16,
                fontWeight: 650,
                fontVariantNumeric: 'tabular-nums',
                color: label === 'r − g' ? rgTone(row.r_minus_g, mode) : ink.textPrimary,
              }}
            >
              {value}
            </div>
            {hint && <div style={{ fontSize: 9.5, color: ink.muted }}>{hint}</div>}
          </div>
        ))}
      </div>

      <div style={{ marginTop: 10, fontSize: 11, color: ink.textSecondary }}>
        <strong style={{ color: ink.textPrimary }}>
          {SOVEREIGNTY_LABEL[row.monetary_sovereignty] ?? row.monetary_sovereignty}
        </strong>
        {row.monetary_sovereignty === 'none' && (
          <span> — cannot create the currency it owes, so no national backstop.</span>
        )}
        {row.monetary_sovereignty === 'reserve_currency' && (
          <span> — borrows in a currency the world wants to hold.</span>
        )}
      </div>

      {row.flags.length > 0 ? (
        <ul style={{ margin: '8px 0 0', paddingLeft: 16, fontSize: 11, color: ink.textSecondary }}>
          {row.flags.map((f) => (
            <li key={f} style={{ marginBottom: 2 }}>
              {f}
            </li>
          ))}
        </ul>
      ) : (
        <p style={{ margin: '8px 0 0', fontSize: 11, color: status.good }}>
          No conventional reference points breached.
        </p>
      )}
      <p style={{ margin: '8px 0 0', fontSize: 10, color: ink.muted }}>
        Reference points, not thresholds of failure. Japan exceeds every debt measure here and has
        been stable for decades.
      </p>
    </>
  )
}

function Card({
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
      <h2 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 650 }}>{title}</h2>
      {children}
    </section>
  )
}
