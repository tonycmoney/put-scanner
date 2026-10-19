import { shortDate, signedUsd, usd, winRate } from '../lib/format'
import type { Pick, Stats } from '../types'

const BUCKET_LABEL: Record<string, string> = {
  setup: 'Setup',
  score_band: 'Score',
  strike_distance: 'Strike distance',
  spy_direction: 'Market',
}

export function Performance({ stats, history }: { stats: Stats; history: Pick[] }) {
  return (
    <section className="panel">
      <h2>Performance</h2>
      <div className="tiles">
        <Tile label="Graded" value={String(stats.graded)} />
        <Tile
          label="Win rate"
          value={stats.win_rate === null ? '—' : `${Math.round(stats.win_rate * 100)}%`}
          sub={`${stats.wins}W · ${stats.losses}L`}
        />
        <Tile label="P&L" value={signedUsd(stats.pnl)} tone={stats.pnl >= 0 ? 'pos' : 'neg'} />
        <Tile label="Avg win" value={stats.avg_win === null ? '—' : usd(stats.avg_win)} />
        <Tile label="Avg loss" value={stats.avg_loss === null ? '—' : usd(stats.avg_loss)} />
      </div>

      <p className="muted small adapt">
        {stats.adaptation.active
          ? Object.keys(stats.adaptation.filtered).length
            ? `Learning is on. Now skipping: ${Object.entries(stats.adaptation.filtered)
                .map(([k, v]) => `${BUCKET_LABEL[k] ?? k} ${v.join(', ')}`)
                .join('; ')}.`
            : 'Learning is on. No setup type has a poor enough record to skip yet.'
          : `Learning starts after ${stats.adaptation.graded_needed} graded picks (${stats.graded} so far).`}
      </p>

      {stats.graded > 0 && (
        <table className="buckets">
          <thead>
            <tr>
              <th>Bucket</th>
              <th>Value</th>
              <th>Trades</th>
              <th>Win rate</th>
              <th>P&amp;L</th>
            </tr>
          </thead>
          <tbody>
            {Object.entries(stats.buckets).flatMap(([bucket, values]) =>
              Object.entries(values).map(([value, s]) => (
                <tr key={bucket + value}>
                  <td>{BUCKET_LABEL[bucket] ?? bucket}</td>
                  <td>{value.replace('_', ' ')}</td>
                  <td className="num">{s.trades}</td>
                  <td className="num">{winRate(s.wins, s.trades)}</td>
                  <td className={`num ${s.pnl >= 0 ? 'pos' : 'neg'}`}>{signedUsd(s.pnl)}</td>
                </tr>
              )),
            )}
          </tbody>
        </table>
      )}

      <h3>Graded picks</h3>
      {history.length === 0 ? (
        <p className="muted small">No graded picks yet. Picks are graded after each close.</p>
      ) : (
        <table className="history">
          <thead>
            <tr>
              <th>Date</th>
              <th>Ticker</th>
              <th>Trade</th>
              <th>Score</th>
              <th>Result</th>
              <th>P&amp;L</th>
              <th>Why</th>
            </tr>
          </thead>
          <tbody>
            {history.map((p) => (
              <tr key={p.id}>
                <td className="num">{shortDate(p.trade_date)}</td>
                <td className="ticker-cell">{p.symbol}</td>
                <td className="num">
                  {p.short_strike}/{p.long_strike}P {shortDate(p.expiry)}
                </td>
                <td className="num">{p.score}</td>
                <td>
                  <span className={`result ${p.status}`}>{p.status.toUpperCase()}</span>
                </td>
                <td className={`num ${p.pnl >= 0 ? 'pos' : 'neg'}`}>{signedUsd(p.pnl)}</td>
                <td className="muted small">{p.grade_reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  )
}

function Tile({ label, value, sub, tone }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <div className="tile">
      <div className="label">{label}</div>
      <div className={`num tile-value ${tone ?? ''}`}>{value}</div>
      {sub && <div className="muted small">{sub}</div>}
    </div>
  )
}
