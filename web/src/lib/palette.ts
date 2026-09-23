/**
 * Validated design tokens.
 *
 * The three categorical slots pass every check under `--pairs all` in BOTH modes
 * (worst CVD dE 9.2 light / 9.4 dark, normal-vision 24.0 / 20.9). The diverging ramp is
 * lightness-monotonic with equal arms and a near-gray midpoint; its poles clear CVD
 * separation at dE 16.8.
 *
 * One WARN stands: aqua (#1baf7a) sits at 2.74:1 on the light surface, below 3:1. The
 * skill's relief rule therefore applies and is satisfied because the ranked table is
 * always present beside the map -- do not remove it.
 *
 * Colour follows the ENTITY, never its rank. Filtering the graph must not repaint survivors.
 */

export type Mode = 'light' | 'dark'

export const chrome = {
  light: {
    surface: '#fcfcfb',
    plane: '#f9f9f7',
    textPrimary: '#0b0b0b',
    textSecondary: '#52514e',
    muted: '#898781',
    grid: '#e1e0d9',
    axis: '#c3c2b7',
    border: 'rgba(11,11,11,0.10)',
  },
  dark: {
    surface: '#1a1a19',
    plane: '#0d0d0d',
    textPrimary: '#ffffff',
    textSecondary: '#c3c2b7',
    muted: '#898781',
    grid: '#2c2c2a',
    axis: '#383835',
    border: 'rgba(255,255,255,0.10)',
  },
} as const

/** Categorical slots 1-3, in fixed order. Never cycled; a 4th series folds into "Other". */
export const series = {
  light: ['#2a78d6', '#eb6834', '#1baf7a'],
  dark: ['#3987e5', '#d95926', '#199e70'],
} as const

/** Semantic roles for the network view, drawn from the validated categorical slots. */
export const edgeRole = {
  light: { inbound: '#2a78d6', outbound: '#eb6834', neutral: '#1baf7a' },
  dark: { inbound: '#3987e5', outbound: '#d95926', neutral: '#199e70' },
} as const

/**
 * Diverging ramp for net creditor (blue) <-> net debtor (red), neutral gray midpoint.
 * Two hues plus gray -- never a rainbow, never a hue at the midpoint.
 */
export const diverging = {
  light: [
    '#104281', '#1c5cab', '#2a78d6', '#3987e5', '#6da7ec', '#9ec5f4', '#cde2fb',
    '#f0efec',
    '#fbd5d1', '#f3ada6', '#e7837b', '#da544f', '#ca4441', '#a1302f', '#781f1e',
  ],
  dark: [
    '#104281', '#1c5cab', '#2a78d6', '#3987e5', '#6da7ec', '#9ec5f4', '#cde2fb',
    '#383835',
    '#fbd5d1', '#f3ada6', '#e7837b', '#da544f', '#ca4441', '#a1302f', '#781f1e',
  ],
} as const

export const MIDPOINT = 7

/**
 * Sequential ramp for magnitude (debt outstanding, holdings size). One hue, light -> dark.
 * Never a rainbow, and never used where the value has a meaningful zero-crossing -- that is
 * the diverging ramp's job.
 */
export const sequential = {
  light: ['#cde2fb', '#b7d3f6', '#9ec5f4', '#86b6ef', '#6da7ec', '#5598e7', '#3987e5', '#2a78d6', '#1c5cab'],
  dark: ['#104281', '#184f95', '#1c5cab', '#256abf', '#2a78d6', '#3987e5', '#5598e7', '#6da7ec', '#86b6ef'],
} as const

/** Status colours are reserved and never reused as a series hue. */
export const status = {
  good: '#0ca30c',
  warning: '#fab219',
  serious: '#ec835a',
  critical: '#d03b3b',
} as const

/**
 * Map a signed value to a diverging ramp step.
 *
 * Uses a **power scale (exponent 0.5)**, deliberately not a log scale. Log was tried first
 * and was wrong in a way that is worth recording: it *expands the bottom* of the range, so a
 * country with a negligible -$1B position landed ~72% of the way to the extreme and almost
 * the entire map rendered as a saturated net debtor. Since we want small positions to sit
 * near the neutral midpoint and only genuinely large ones to saturate, the scale has to
 * compress the bottom, not expand it. sqrt keeps mid-range countries distinguishable where
 * a purely linear scale would flatten everything except the three or four largest.
 */
export function divergingStep(value: number, maxAbs: number): number {
  if (!Number.isFinite(value) || value === 0 || maxAbs <= 0) return MIDPOINT
  const scaled = Math.pow(Math.min(1, Math.abs(value) / maxAbs), 0.5)
  const arm = Math.min(MIDPOINT, Math.max(1, Math.ceil(scaled * MIDPOINT)))
  return value > 0 ? MIDPOINT - arm : MIDPOINT + arm
}

export function divergingColor(value: number, maxAbs: number, mode: Mode): string {
  return diverging[mode][divergingStep(value, maxAbs)]
}

/**
 * Stroke width for a flow arc.
 *
 * sqrt-scaled and capped: width is a weak quantitative encoder, so it carries
 * "big vs small" only. Exact magnitudes are read from the ranked table.
 */
export function arcWidth(usd: number, maxUsd: number, cap = 10): number {
  if (!Number.isFinite(usd) || usd <= 0 || maxUsd <= 0) return 0
  return Math.max(1, Math.sqrt(usd / maxUsd) * cap)
}
