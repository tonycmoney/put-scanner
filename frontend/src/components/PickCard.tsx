import { cushion, PART_LABEL, PART_MAX, pct, setupLabel, shortDate, strike, usd } from '../lib/format'
import type { Pick } from '../types'

export function PickCard({ pick }: { pick: Pick }) {
  const d = pick.details
  const price = pick.last_price ?? pick.entry_price
  const room = cushion(price, pick.alert_level)
  const danger = room < 0.03
  return (
    <article className="pick" aria-label={`${pick.symbol} setup`}>
      <header className="pick-head">
        <div>
          <div className="ticker">{pick.symbol}</div>
          <div className="muted small">{d.name}</div>
        </div>
        <div className={`setup ${d.setup}`}>
          {setupLabel(d.setup)} {pct(d.change_ratio)}
        </div>
        <div className="score" title="Setup score out of 100">
          <span>{pick.score}</span>
        </div>
      </header>

      <div className="price-row">
        <div>
          <div className="label">Price</div>
          <div className="num big">{usd(price, 2)}</div>
        </div>
        <div>
          <div className="label">Alert below</div>
          <div className="num big">{usd(pick.alert_level, 2)}</div>
        </div>
        <div>
          <div className="label">Cushion</div>
          <div className={`num big ${danger ? 'neg' : 'pos'}`}>{pct(room)}</div>
        </div>
        <div>
          <div className="label">Close by</div>
          <div className="num big">{shortDate(pick.close_by)}</div>
        </div>
      </div>

      <div className="compare">
        <div className="col">
          <h4>Put credit spread</h4>
          <dl>
            <dt>Legs</dt>
            <dd className="num">
              −{strike(pick.short_strike)}P / +{strike(pick.long_strike)}P {shortDate(pick.expiry)}
            </dd>
            <dt>Contracts</dt>
            <dd className="num">{pick.contracts}</dd>
            <dt>Credit</dt>
            <dd className="num">
              {usd(pick.credit, 2)} <span className="muted">(natural {usd(d.natural_credit, 2)})</span>
            </dd>
            <dt>Est. profit</dt>
            <dd className="num pos">{usd(pick.est_profit)}</dd>
            <dt>Max loss</dt>
            <dd className="num neg">{usd(pick.max_loss)}</dd>
            <dt>Capital</dt>
            <dd className="num">{usd(d.spread_capital)}</dd>
            <dt>Breakeven</dt>
            <dd className="num">{usd(d.spread_breakeven, 2)}</dd>
          </dl>
        </div>
        <div className="col">
          <h4>Cash secured put</h4>
          {d.csp_contracts > 0 ? (
            <dl>
              <dt>Leg</dt>
              <dd className="num">
                −{strike(pick.short_strike)}P {shortDate(pick.expiry)}
              </dd>
              <dt>Contracts</dt>
              <dd className="num">{d.csp_contracts}</dd>
              <dt>Premium</dt>
              <dd className="num">{usd(d.csp_premium, 2)}</dd>
              <dt>Est. profit</dt>
              <dd className="num pos">{usd(d.csp_est_profit)}</dd>
              <dt>Collateral</dt>
              <dd className="num">{usd(d.csp_collateral)}</dd>
              <dt>Breakeven</dt>
              <dd className="num">{usd(d.csp_breakeven, 2)}</dd>
              <dt>Risk</dt>
              <dd className="muted small">Assignment below the strike</dd>
            </dl>
          ) : (
            <p className="muted small">Strike is too high to secure with the budget.</p>
          )}
        </div>
      </div>

      <div className="parts" aria-label="Score breakdown">
        {Object.entries(d.score_parts).map(([k, v]) => (
          <div className="part" key={k}>
            <span className="part-label">{PART_LABEL[k] ?? k}</span>
            <span className="bar">
              <span style={{ width: `${(v / (PART_MAX[k] ?? 25)) * 100}%` }} />
            </span>
            <span className="num small">
              {v}/{PART_MAX[k] ?? 25}
            </span>
          </div>
        ))}
      </div>

      {d.warnings.length > 0 && (
        <ul className="warnings">
          {d.warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      )}
    </article>
  )
}
