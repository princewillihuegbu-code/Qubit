from dataclasses import dataclass
from validator import Signal

DEFAULT_BALANCE: float = 10_000.0
RISK_PER_TRADE_PCT: float = 0.01
MAX_DAILY_LOSS_PCT: float = 0.05
MAX_OPEN_TRADES: int = 3
MAX_CONSECUTIVE_LOSSES: int = 3


@dataclass
class RiskResult:
    allowed: bool
    reason: str
    risk_amount: float | None = None
    rr_ratio: float | None = None


def get_derived(balance: float) -> tuple[float, float]:
    risk_per_trade = round(balance * RISK_PER_TRADE_PCT, 2)
    max_daily_loss = round(balance * MAX_DAILY_LOSS_PCT, 2)
    return risk_per_trade, max_daily_loss


def calculate_rr(signal: Signal) -> float:
    if signal.direction == "BUY":
        risk = signal.entry - signal.stop_loss
        reward = signal.take_profit - signal.entry
    else:
        risk = signal.stop_loss - signal.entry
        reward = signal.entry - signal.take_profit

    if risk <= 0:
        return 0.0
    return round(reward / risk, 2)


def check_risk(approved_today: int, consecutive_losses: int, balance: float) -> RiskResult:
    risk_per_trade, max_daily_loss = get_derived(balance)

    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        return RiskResult(
            False,
            f"Qubit Risk (QR): Trading paused — {MAX_CONSECUTIVE_LOSSES} consecutive losses detected"
        )

    if approved_today >= MAX_OPEN_TRADES:
        return RiskResult(
            False,
            f"Qubit Risk (QR): Maximum open trades ({MAX_OPEN_TRADES}) already reached for today"
        )

    committed = approved_today * risk_per_trade
    if committed >= max_daily_loss:
        return RiskResult(
            False,
            f"Qubit Risk (QR): Daily loss limit of ${max_daily_loss:,.0f} (5%) has been reached"
        )

    return RiskResult(True, "Risk limits OK", risk_amount=risk_per_trade)


def risk_status_text(approved_today: int, consecutive_losses: int, balance: float) -> str:
    risk_per_trade, max_daily_loss = get_derived(balance)
    committed = approved_today * risk_per_trade
    remaining = max(0.0, max_daily_loss - committed)
    trades_left = max(0, MAX_OPEN_TRADES - approved_today)
    losses_left = max(0, MAX_CONSECUTIVE_LOSSES - consecutive_losses)

    filled = min(10, round((committed / max_daily_loss) * 10)) if max_daily_loss > 0 else 0
    bar = "█" * filled + "░" * (10 - filled)

    limits_hit = (
        committed >= max_daily_loss
        or approved_today >= MAX_OPEN_TRADES
        or consecutive_losses >= MAX_CONSECUTIVE_LOSSES
    )

    lines = [
        "⚠️ Qubit Risk (QR) — Status",
        "─" * 30,
        "",
        f"Balance:             ${balance:,.2f}",
        f"Risk Per Trade:      ${risk_per_trade:,.2f} (1%)",
        f"Max Daily Loss:      ${max_daily_loss:,.2f} (5%)",
        "",
        f"Committed Today:     ${committed:,.2f}",
        f"Remaining Capacity:  ${remaining:,.2f}",
        f"[{bar}]",
        "",
        f"Open Trades:         {approved_today}/{MAX_OPEN_TRADES}",
        f"Consecutive Losses:  {consecutive_losses}/{MAX_CONSECUTIVE_LOSSES}",
        f"Trades Remaining:    {trades_left}",
        f"Loss Buffer:         {losses_left} before pause",
        "",
        "🔴 Status: LIMITS REACHED — No new trades" if limits_hit
        else "🟢 Status: ACTIVE — Accepting signals",
    ]

    return "\n".join(lines)
