from dataclasses import dataclass
from validator import Signal

STARTING_BALANCE: float = 10_000.0
RISK_PER_TRADE_PCT: float = 0.01
MAX_DAILY_LOSS_PCT: float = 0.05
MAX_OPEN_TRADES: int = 3
MAX_CONSECUTIVE_LOSSES: int = 3

RISK_PER_TRADE: float = STARTING_BALANCE * RISK_PER_TRADE_PCT
MAX_DAILY_LOSS: float = STARTING_BALANCE * MAX_DAILY_LOSS_PCT


@dataclass
class RiskResult:
    allowed: bool
    reason: str
    risk_amount: float | None = None
    rr_ratio: float | None = None


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


def check_risk(approved_today: int, consecutive_losses: int) -> RiskResult:
    if consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        return RiskResult(
            False,
            f"Q Risk Engine: Trading paused — {MAX_CONSECUTIVE_LOSSES} consecutive losses detected"
        )

    if approved_today >= MAX_OPEN_TRADES:
        return RiskResult(
            False,
            f"Q Risk Engine: Maximum open trades ({MAX_OPEN_TRADES}) already reached for today"
        )

    committed = approved_today * RISK_PER_TRADE
    if committed >= MAX_DAILY_LOSS:
        return RiskResult(
            False,
            f"Q Risk Engine: Daily loss limit of ${MAX_DAILY_LOSS:.0f} (5%) has been reached"
        )

    return RiskResult(True, "Risk limits OK", risk_amount=RISK_PER_TRADE)


def risk_status_text(approved_today: int, consecutive_losses: int) -> str:
    committed = approved_today * RISK_PER_TRADE
    remaining = max(0.0, MAX_DAILY_LOSS - committed)
    trades_left = max(0, MAX_OPEN_TRADES - approved_today)
    losses_left = max(0, MAX_CONSECUTIVE_LOSSES - consecutive_losses)

    committed_bar_filled = min(10, round((committed / MAX_DAILY_LOSS) * 10))
    committed_bar = "█" * committed_bar_filled + "░" * (10 - committed_bar_filled)

    lines = [
        "⚠️ Q Risk Engine — Status",
        "─" * 30,
        "",
        f"Starting Balance:    ${STARTING_BALANCE:,.0f}",
        f"Risk Per Trade:      ${RISK_PER_TRADE:.0f} (1%)",
        f"Max Daily Loss:      ${MAX_DAILY_LOSS:.0f} (5%)",
        "",
        f"Committed Today:     ${committed:.0f}",
        f"Remaining Capacity:  ${remaining:.0f}",
        f"[{committed_bar}]",
        "",
        f"Open Trades:         {approved_today}/{MAX_OPEN_TRADES}",
        f"Consecutive Losses:  {consecutive_losses}/{MAX_CONSECUTIVE_LOSSES}",
        f"Trades Remaining:    {trades_left}",
        f"Loss Buffer:         {losses_left} before pause",
    ]

    if committed >= MAX_DAILY_LOSS or approved_today >= MAX_OPEN_TRADES or consecutive_losses >= MAX_CONSECUTIVE_LOSSES:
        lines.append("")
        lines.append("🔴 Status: LIMITS REACHED — No new trades")
    else:
        lines.append("")
        lines.append("🟢 Status: ACTIVE — Accepting signals")

    return "\n".join(lines)
