import { useCallback, useEffect, useState } from 'react'
import { api } from './api'
import { PickCard } from './components/PickCard'
import { Performance } from './components/Performance'
import { pct, usd } from './lib/format'
import type { Pick, Stats, Status } from './types'

export default function App() {
  const [status, setStatus] = useState<Status | null>(null)
  const [open, setOpen] = useState<Pick[]>([])
  const [history, setHistory] = useState<Pick[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [scanning, setScanning] = useState(false)

  const refresh = useCallback(async () => {
    const [s, o, h, st] = await Promise.all([
      api.status(),
      api.picks('open'),
      api.picks('graded'),
      api.stats(),
    ])
    setStatus(s)
    setOpen(o)
    setHistory(h)
    setStats(st)
  }, [])

  useEffect(() => {
    const tick = async () => {
      try {
        await refresh()
      } catch (e) {
        setMessage(e instanceof Error ? e.message : 'Could not load data')
      }
    }
    void tick()
    const id = window.setInterval(() => void tick(), 60000)
    return () => window.clearInterval(id)
  }, [refresh])

  const scanNow = async () => {
    setScanning(true)
    setMessage(null)
    try {
      const res = await api.scan()
      setMessage(res.result)
      await refresh()
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Scan failed')
    } finally {
      setScanning(false)
    }
  }

  const next = status ? new Date(status.next_job.at) : null
  const last = status?.last_run

  return (
    <div className="app">
      <header className="top">
        <div className="brand">
          <img src="/favicon.svg" alt="" width={28} height={28} />
          <span>Put Scanner</span>
          {status && <span className="env">{status.environment.toUpperCase()}</span>}
        </div>
        <div className="top-meta">
          {next && (
            <span>
              Next {status?.next_job.kind}:{' '}
              <b className="num">
                {next.toLocaleString('en-US', {
                  weekday: 'short',
                  hour: 'numeric',
                  minute: '2-digit',
                  timeZone: 'America/New_York',
                })}{' '}
                ET
              </b>
            </span>
          )}
          {last && (
            <span>
              Last scan: <b>{last.status}</b> · {last.picks} picks from {last.candidates} movers · SPY{' '}
              <b className={`num ${last.spy_change >= 0 ? 'pos' : 'neg'}`}>{pct(last.spy_change)}</b>
            </span>
          )}
        </div>
        <button
          className="scan-btn"
          onClick={scanNow}
          disabled={scanning || !status?.configured || status?.busy}
        >
          {scanning ? 'Scanning…' : 'Scan now'}
        </button>
      </header>

      <div className="disclaimer">
        Alerts only. This tool never places orders and is not financial advice. Options can lose
        money quickly; size every trade to the risk you can afford.
      </div>

      {message && (
        <div className="notice" role="status">
          {message}
        </div>
      )}

      {status && !status.configured && (
        <section className="panel setup-panel">
          <h2>Connect Webull to start scanning</h2>
          <p>
            The scanner reads market data from the Webull OpenAPI. Set <code>WEBULL_APP_KEY</code>{' '}
            and <code>WEBULL_APP_SECRET</code> on the server (and <code>WEBULL_ENV</code> to{' '}
            <code>sandbox</code> or <code>production</code>). Scans then run automatically on
            weekdays during market hours.
          </p>
        </section>
      )}
      {status?.token_status === 'PENDING' && (
        <section className="panel setup-panel">
          <h2>Approve API access in the Webull app</h2>
          <p>
            Webull sent an access request to your app. Approve it, then press <b>Scan now</b>.
          </p>
        </section>
      )}
      {last?.status === 'error' && (
        <div className="notice error" role="alert">
          Last scan failed: {last.error}
        </div>
      )}

      <main className="grid">
        <section className="panel picks-panel">
          <h2>
            Open picks <span className="count">{open.length}</span>
          </h2>
          {open.length === 0 ? (
            <p className="muted">
              No open picks. Each scan reports up to 5 setups that pass every rule.
            </p>
          ) : (
            <div className="picks">
              {open.map((p) => (
                <PickCard key={p.id} pick={p} />
              ))}
            </div>
          )}
        </section>

        <aside className="side">
          {status && (
            <section className="panel">
              <h2>Rules</h2>
              <ul className="rules">
                <li>
                  Budget {usd(status.rules.budget)} cash secured · max loss{' '}
                  {usd(status.rules.max_loss_per_trade)} per trade
                </li>
                <li>
                  Profit target {usd(status.rules.profit_target[0])} to{' '}
                  {usd(status.rules.profit_target[1])}
                </li>
                <li>
                  Stocks {usd(status.rules.price_range[0])} to {usd(status.rules.price_range[1])},
                  cap ${(status.rules.min_market_cap / 1e9).toFixed(0)}B+, volume{' '}
                  {(status.rules.min_volume / 1000).toFixed(0)}K+, move{' '}
                  {Math.round(status.rules.min_move * 100)}%+
                </li>
                <li>
                  Expiry {status.rules.dte[0]} to {status.rules.dte[1]} days, short strike{' '}
                  {Math.round(status.rules.otm[0] * 100)}% to {Math.round(status.rules.otm[1] * 100)}%
                  below price
                </li>
                <li>Skips falling knives, stocks still at the day low, and earnings before expiry</li>
              </ul>
            </section>
          )}
          {last && last.rejected.length > 0 && (
            <section className="panel">
              <h2>Rejected last scan</h2>
              <ul className="rejected">
                {last.rejected.map((r) => (
                  <li key={r.symbol}>
                    <b className="ticker-cell">{r.symbol}</b> <span className="muted">{r.reason}</span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </aside>
      </main>

      {stats && <Performance stats={stats} history={history} />}
    </div>
  )
}
