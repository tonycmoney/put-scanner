"""Optional push alerts for new picks via a Discord or Slack incoming webhook."""

from __future__ import annotations

import logging

import httpx

from app.scanner import Proposal

log = logging.getLogger("alerts")


def format_pick(p: Proposal) -> str:
    lines = [
        f"**{p.symbol}** score {p.score} · {p.setup.replace('_', ' ')} "
        f"{p.change_ratio:+.1%} at ${p.price:.2f}",
        f"Spread: sell {p.short_strike:g}P / buy {p.long_strike:g}P exp {p.expiry:%b %d} "
        f"for ${p.credit:.2f} x{p.contracts} · profit ${p.est_profit:.0f} · max loss "
        f"${p.max_loss:.0f}",
    ]
    if p.csp_contracts:
        lines.append(
            f"CSP: sell {p.short_strike:g}P x{p.csp_contracts} for ${p.csp_premium:.2f} · "
            f"collateral ${p.csp_collateral:,.0f} · profit ${p.csp_est_profit:.0f}"
        )
    lines.append(f"Alert below ${p.alert_level:g} · close by {p.close_by:%b %d}")
    return "\n".join(lines)


def send_alert(url: str | None, picks: list[Proposal], client: httpx.Client | None = None) -> bool:
    if not url or not picks:
        return False
    text = "New put selling setups (alerts only, not advice)\n\n" + "\n\n".join(
        format_pick(p) for p in picks
    )
    # "content" for Discord, "text" for Slack; each ignores the other.
    payload = {"content": text[:1900], "text": text}
    try:
        http = client or httpx.Client(timeout=10)
        http.post(url, json=payload).raise_for_status()
        return True
    except httpx.HTTPError as exc:
        log.warning("alert webhook failed: %s", type(exc).__name__)
        return False
