export interface PickDetails {
  name: string
  setup: 'down_shock' | 'up_spike'
  change_ratio: number
  score_parts: Record<string, number>
  natural_credit: number
  spread_capital: number
  spread_breakeven: number
  csp_contracts: number
  csp_premium: number
  csp_collateral: number
  csp_est_profit: number
  csp_breakeven: number
  strike_otm: number
  spy_change: number
  warnings: string[]
}

export interface Pick {
  id: number
  symbol: string
  status: 'open' | 'win' | 'loss'
  trade_date: string
  expiry: string
  close_by: string
  alert_level: number
  entry_price: number
  last_price: number | null
  last_spread_value: number | null
  score: number
  short_strike: number
  long_strike: number
  credit: number
  contracts: number
  est_profit: number
  max_loss: number
  pnl: number
  grade_reason: string
  buckets: Record<string, string>
  details: PickDetails
}

export interface Rejection {
  symbol: string
  reason: string
}

export interface Status {
  configured: boolean
  environment: string
  token_status: string | null
  scheduler_enabled: boolean
  busy: boolean
  alerts_enabled: boolean
  next_job: { kind: 'scan' | 'grade'; at: string }
  last_run: null | {
    id: number
    status: string
    trigger: string
    picks: number
    candidates: number
    spy_change: number
    error: string
    started_at: string
    rejected: Rejection[]
  }
  rules: {
    budget: number
    max_loss_per_trade: number
    profit_target: [number, number]
    price_range: [number, number]
    min_market_cap: number
    min_volume: number
    min_move: number
    dte: [number, number]
    otm: [number, number]
  }
}

export interface BucketStat {
  trades: number
  wins: number
  pnl: number
}

export interface Stats {
  graded: number
  wins: number
  losses: number
  win_rate: number | null
  pnl: number
  avg_win: number | null
  avg_loss: number | null
  buckets: Record<string, Record<string, BucketStat>>
  adaptation: { active: boolean; graded_needed: number; filtered: Record<string, string[]> }
}
