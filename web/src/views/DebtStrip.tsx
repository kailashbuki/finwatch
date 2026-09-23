/**
 * The debt panel: how much government debt exists, and who holds it.
 *
 * This is the denominator the dashboard previously lacked. Foreign cross-border holdings
 * alone invite comparison against headline gross debt, which is a different measure, so
 * both are shown side by side with their definitions stated.
 *
 * Coverage is deliberately uneven and says so: the US has a full holder-class breakdown
 * (Treasury OFS-2), while the other 44 countries have only a domestic/foreign split (BIS).
 * No free source breaks holders down further -- notably, hedge funds are never identified
 * separately and fall inside "Other investors".
 */

import type { DebtOutstanding, DebtRow, HolderBreakdown } from '../lib/data'
import { formatUSD } from '../lib/data'
import { type Mode, chrome, edgeRole, sequential } from '../lib/palette'

interface Props {
  mode: Mode
  debt: DebtOutstanding | null
  holders: HolderBreakdown | null
  focal: string | null
  onSelect: (country: string) => void
}

export default function DebtStrip({ mode, debt, holders, focal, onSelect }: Props) {
  const ink = chrome[mode]
  if (!debt) return null

  const row = focal ? debt.rows.find((r) => r.country === focal) : undefined
  const showHolders = focal === 'USA' && holders

  return (
    <section
      style={{
        background: ink.surface,
        border: `1px solid ${ink.border}`,
        borderRadius: 10,
        padding: '10px 14px',
        display: 'grid',
        gap: 10,
        minHeight: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
        <h2 style={{ margin: 0, fontSize: 13, fontWeight: 650 }}>
          {focal ? `${focal} — government debt` : 'Government debt outstanding'}
        </h2>
        <span style={{ fontSize: 11, color: ink.muted }}>
          BIS, general government debt securities, {debt.period}
          {showHolders && ` · holders: US Treasury OFS-2, ${holders!.period}`}
        </span>
      </div>

      {focal && !row && (
        <p style={{ margin: 0, fontSize: 12, color: ink.muted }}>
          No debt-securities total published for {focal}. BIS covers 45 reporting areas; the
          bilateral holdings data covers many more, so a country can appear on the map without
          a denominator here.
        </p>
      )}

      {focal && row && <FocalDebt mode={mode} row={row} />}
      {showHolders && <HolderBars mode={mode} breakdown={holders!} />}
      {!focal && <TopIssuers mode={mode} rows={debt.rows} onSelect={onSelect} />}
    </section>
  )
}

function Stat({
  mode,
  label,
  value,
  hint,
}: {
  mode: Mode
  label: string
  value: string
  hint?: string
}) {
  const ink = chrome[mode]
  return (
    <div style={{ minWidth: 120 }}>
      <div style={{ fontSize: 10, color: ink.muted, textTransform: 'uppercase', letterSpacing: 0.4 }}>
        {label}
      </div>
      <div style={{ fontSize: 19, fontWeight: 650, fontVariantNumeric: 'tabular-nums' }}>
        {value}
      </div>
      {hint && <div style={{ fontSize: 10, color: ink.muted }}>{hint}</div>}
    </div>
  )
}

function FocalDebt({ mode, row }: { mode: Mode; row: DebtRow }) {
  const ink = chrome[mode]
  const roles = edgeRole[mode]
  const share = row.foreign_share
  return (
    <div style={{ display: 'flex', gap: 26, alignItems: 'flex-end', flexWrap: 'wrap' }}>
      <Stat mode={mode} label="Debt securities outstanding" value={formatUSD(row.usd)} />
      <Stat
        mode={mode}
        label="Held by non-residents"
        value={row.foreign_usd == null ? '—' : formatUSD(row.foreign_usd)}
        hint={row.foreign_usd == null ? 'not reported' : undefined}
      />
      <Stat
        mode={mode}
        label="Foreign share"
        value={share == null ? '—' : `${(share * 100).toFixed(1)}%`}
        hint={share == null ? undefined : 'approximate (mixed valuation)'}
      />

      {share != null && (
        <div style={{ flex: 1, minWidth: 200 }}>
          <div
            style={{
              display: 'flex',
              height: 16,
              borderRadius: 3,
              overflow: 'hidden',
              gap: 2,
            }}
          >
            <div
              style={{ width: `${Math.min(100, share * 100)}%`, background: roles.inbound }}
              title={`Non-resident held: ${formatUSD(row.foreign_usd ?? 0)}`}
            />
            <div
              style={{ flex: 1, background: mode === 'light' ? '#cde2fb' : '#1c5cab' }}
              title="Domestically held"
            />
          </div>
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              fontSize: 10,
              color: ink.textSecondary,
              marginTop: 3,
            }}
          >
            <span>foreign {(share * 100).toFixed(0)}%</span>
            <span>domestic {((1 - share) * 100).toFixed(0)}%</span>
          </div>
        </div>
      )}
    </div>
  )
}

function HolderBars({ mode, breakdown }: { mode: Mode; breakdown: HolderBreakdown }) {
  const ink = chrome[mode]
  const ramp = sequential[mode]
  const max = Math.max(...breakdown.categories.map((c) => c.usd))
  return (
    <div>
      <div style={{ fontSize: 11, color: ink.textSecondary, marginBottom: 4 }}>
        Every holder of US Treasury securities — total {formatUSD(breakdown.total)}. Note this
        is <em>all</em> Treasury debt, not only the foreign slice shown on the map.
      </div>
      <div style={{ display: 'grid', gap: 3 }}>
        {breakdown.categories.map((c, i) => (
          <div
            key={c.group}
            style={{ display: 'grid', gridTemplateColumns: '1fr 62px 42px', gap: 8, alignItems: 'center' }}
          >
            <div style={{ position: 'relative', height: 16 }}>
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  width: `${(c.usd / max) * 100}%`,
                  background: ramp[Math.min(ramp.length - 1, 2 + i)],
                  borderRadius: '0 3px 3px 0',
                }}
              />
              <span
                style={{
                  position: 'relative',
                  fontSize: 10.5,
                  color: ink.textPrimary,
                  paddingLeft: 5,
                  lineHeight: '16px',
                  textShadow:
                    mode === 'light' ? '0 0 3px rgba(252,252,251,.9)' : '0 0 3px rgba(26,26,25,.9)',
                }}
              >
                {c.group}
              </span>
            </div>
            <span
              style={{
                fontSize: 11,
                textAlign: 'right',
                fontVariantNumeric: 'tabular-nums',
                color: ink.textSecondary,
              }}
            >
              {formatUSD(c.usd)}
            </span>
            <span
              style={{
                fontSize: 11,
                textAlign: 'right',
                fontVariantNumeric: 'tabular-nums',
                color: ink.muted,
              }}
            >
              {(c.share * 100).toFixed(1)}%
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function TopIssuers({
  mode,
  rows,
  onSelect,
}: {
  mode: Mode
  rows: DebtRow[]
  onSelect: (c: string) => void
}) {
  const ink = chrome[mode]
  const roles = edgeRole[mode]
  // Exclude the euro-area aggregate: BIS reports it alongside its member states, so listing
  // both double-counts France, Germany, Italy and Spain in the same ranking.
  const top = rows
    .filter((r) => r.country !== 'U2' && r.country !== 'XM')
    .sort((a, b) => b.usd - a.usd)
    .slice(0, 10)
  const max = top[0]?.usd ?? 1
  return (
    <div>
      <div style={{ fontSize: 11, color: ink.textSecondary, marginBottom: 5 }}>
        Largest issuers, with the share held by non-residents. Click a bar, or a country on the
        map, to drill in.
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit,minmax(210px,1fr))', gap: '3px 16px' }}>
        {top.map((r) => (
          <button
            key={r.country}
            onClick={() => onSelect(r.country)}
            style={{
              display: 'grid',
              gridTemplateColumns: '34px 1fr 58px',
              gap: 7,
              alignItems: 'center',
              background: 'transparent',
              border: 'none',
              padding: '1px 0',
              cursor: 'pointer',
              color: 'inherit',
              textAlign: 'left',
              font: 'inherit',
            }}
          >
            <span style={{ fontSize: 11, color: ink.textSecondary }}>{r.country}</span>
            <span style={{ position: 'relative', height: 13, background: ink.grid, borderRadius: 2 }}>
              <span
                style={{
                  position: 'absolute',
                  inset: 0,
                  width: `${(r.usd / max) * 100}%`,
                  background: mode === 'light' ? '#9ec5f4' : '#1c5cab',
                  borderRadius: 2,
                }}
              />
              {r.foreign_share != null && (
                <span
                  style={{
                    position: 'absolute',
                    top: 0,
                    bottom: 0,
                    width: `${(r.usd / max) * r.foreign_share * 100}%`,
                    background: roles.inbound,
                    borderRadius: 2,
                  }}
                  title={`${(r.foreign_share * 100).toFixed(0)}% held by non-residents`}
                />
              )}
            </span>
            <span
              style={{
                fontSize: 11,
                textAlign: 'right',
                fontVariantNumeric: 'tabular-nums',
                color: ink.textSecondary,
              }}
            >
              {formatUSD(r.usd)}
            </span>
          </button>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 14, fontSize: 10, color: ink.muted, marginTop: 5 }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span style={{ width: 11, height: 9, background: roles.inbound, borderRadius: 2 }} />
          held by non-residents
        </span>
        <span style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
          <span
            style={{
              width: 11,
              height: 9,
              background: mode === 'light' ? '#9ec5f4' : '#1c5cab',
              borderRadius: 2,
            }}
          />
          held domestically
        </span>
      </div>
    </div>
  )
}
