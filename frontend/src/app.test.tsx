import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Performance } from './components/Performance'
import { PickCard } from './components/PickCard'
import { cushion, pct, shortDate, signedUsd, strike, usd, winRate } from './lib/format'
import type { Pick, Stats } from './types'

describe('format', () => {
  it('formats money and percents', () => {
    expect(usd(1234.5)).toBe('$1,235')
    expect(usd(0.55, 2)).toBe('$0.55')
    expect(usd(-14)).toBe('−$14')
    expect(signedUsd(60)).toBe('+$60')
    expect(pct(-0.156)).toBe('−15.6%')
    expect(pct(0.12)).toBe('+12.0%')
  })

  it('formats strikes and dates without timezone drift', () => {
    expect(strike(30)).toBe('30')
    expect(strike(27.5)).toBe('27.5')
    expect(shortDate('2026-10-30')).toBe('Oct 30')
  })

  it('computes cushion and win rate', () => {
    expect(cushion(33, 30)).toBeCloseTo(0.0909, 3)
    expect(winRate(3, 4)).toBe('75%')
    expect(winRate(0, 0)).toBe('—')
  })
})

const PICK: Pick = {
  id: 1,
  symbol: 'LQDA',
  status: 'open',
  trade_date: '2026-10-14',
  expiry: '2026-10-30',
  close_by: '2026-10-28',
  alert_level: 30,
  entry_price: 33.5,
  last_price: 30.5,
  last_spread_value: null,
  score: 80,
  short_strike: 30,
  long_strike: 27,
  credit: 0.6,
  contracts: 1,
  est_profit: 60,
  max_loss: 240,
  pnl: 0,
  grade_reason: '',
  buckets: { setup: 'up_spike' },
  details: {
    name: 'Liquidia',
    setup: 'up_spike',
    change_ratio: 0.12,
    score_parts: { move_vs_normal: 25, strike_cushion: 14 },
    natural_credit: 0.45,
    spread_capital: 300,
    spread_breakeven: 29.4,
    csp_contracts: 1,
    csp_premium: 0.7,
    csp_collateral: 3000,
    csp_est_profit: 70,
    csp_breakeven: 29.3,
    strike_otm: 0.104,
    spy_change: 0.002,
    warnings: ['est profit under the $100 target'],
  },
}

describe('PickCard', () => {
  it('shows spread and cash secured put side by side', () => {
    render(<PickCard pick={PICK} />)
    expect(screen.getByText('Put credit spread')).toBeInTheDocument()
    expect(screen.getByText('Cash secured put')).toBeInTheDocument()
    expect(screen.getByText('$240')).toHaveClass('neg')
    expect(screen.getByText('$3,000')).toBeInTheDocument()
    expect(screen.getByText('est profit under the $100 target')).toBeInTheDocument()
  })

  it('flags a thin cushion above the alert level', () => {
    render(<PickCard pick={PICK} />)
    expect(screen.getByText('+1.6%')).toHaveClass('neg')
  })

  it('handles a strike too high for a cash secured put', () => {
    render(<PickCard pick={{ ...PICK, details: { ...PICK.details, csp_contracts: 0 } }} />)
    expect(screen.getByText(/too high to secure/)).toBeInTheDocument()
  })
})

const STATS: Stats = {
  graded: 2,
  wins: 1,
  losses: 1,
  win_rate: 0.5,
  pnl: -40,
  avg_win: 60,
  avg_loss: -100,
  buckets: { setup: { up_spike: { trades: 2, wins: 1, pnl: -40 } } },
  adaptation: { active: false, graded_needed: 8, filtered: {} },
}

describe('Performance', () => {
  it('summarizes results and explains when learning starts', () => {
    render(<Performance stats={STATS} history={[{ ...PICK, status: 'loss', pnl: -100 }]} />)
    expect(screen.getAllByText('50%')).toHaveLength(2)
    expect(screen.getByText('1W · 1L')).toBeInTheDocument()
    expect(screen.getByText(/Learning starts after 8 graded picks/)).toBeInTheDocument()
    expect(screen.getByText('LOSS')).toBeInTheDocument()
  })
})
