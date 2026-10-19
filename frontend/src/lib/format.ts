export const usd = (n: number, digits = 0) =>
  `${n < 0 ? '−' : ''}$${Math.abs(n).toLocaleString('en-US', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}`

export const signedUsd = (n: number) => (n > 0 ? `+${usd(n)}` : usd(n))

export const pct = (ratio: number, digits = 1) =>
  `${ratio > 0 ? '+' : ratio < 0 ? '−' : ''}${Math.abs(ratio * 100).toFixed(digits)}%`

export const strike = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(/0$/, ''))

/** "2026-10-30" -> "Oct 30" without timezone drift. */
export function shortDate(iso: string): string {
  const [y, m, d] = iso.slice(0, 10).split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString('en-US', {
    month: 'short',
    day: 'numeric',
    timeZone: 'UTC',
  })
}

/** How far the stock sits above the alert level, as a share of price. */
export function cushion(price: number, alert: number): number {
  return price > 0 ? (price - alert) / price : 0
}

export function setupLabel(setup: string): string {
  return setup === 'down_shock' ? 'Down shock' : setup === 'up_spike' ? 'Up spike' : setup
}

export const PART_LABEL: Record<string, string> = {
  move_vs_normal: 'Move vs normal',
  strike_cushion: 'Strike cushion',
  credit_quality: 'Credit quality',
  liquidity: 'Liquidity',
  market_backdrop: 'Market backdrop',
}

export const PART_MAX: Record<string, number> = {
  move_vs_normal: 25,
  strike_cushion: 25,
  credit_quality: 20,
  liquidity: 15,
  market_backdrop: 15,
}

export function winRate(wins: number, trades: number): string {
  return trades ? `${Math.round((wins / trades) * 100)}%` : '—'
}
