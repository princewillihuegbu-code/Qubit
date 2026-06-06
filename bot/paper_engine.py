from datetime import datetime
from database import (
    create_paper_trade,
    close_paper_trade,
    get_paper_trade_by_id,
    get_setting,
    set_setting,
)
from risk import DEFAULT_BALANCE


def get_balance() -> float:
    raw = get_setting("balance", str(DEFAULT_BALANCE))
    try:
        return float(raw)
    except ValueError:
        return DEFAULT_BALANCE


def open_trade(
    signal_id: int,
    symbol: str,
    direction: str,
    entry: float,
    stop_loss: float,
    take_profit: float,
    risk_amount: float,
    rr_ratio: float,
) -> int:
    balance = get_balance()
    return create_paper_trade(
        signal_id=signal_id,
        symbol=symbol,
        direction=direction,
        entry=entry,
        stop_loss=stop_loss,
        take_profit=take_profit,
        risk_amount=risk_amount,
        rr_ratio=rr_ratio,
        balance_before=balance,
    )


def calculate_pnl(result: str, risk_amount: float, rr_ratio: float) -> float:
    if result == "win":
        return round(risk_amount * rr_ratio, 2)
    if result == "loss":
        return round(-risk_amount, 2)
    return 0.0  # breakeven


def close_trade(pt_id: int, result: str) -> dict:
    trade = get_paper_trade_by_id(pt_id)
    if trade is None:
        return {"error": "Trade not found"}
    if trade["status"] == "closed":
        return {"error": "Trade already closed"}

    pnl = calculate_pnl(result, trade["risk_amount"], trade["rr_ratio"])

    open_dt = datetime.fromisoformat(trade["open_time"])
    duration_min = max(1, int((datetime.now() - open_dt).total_seconds() / 60))

    balance_before = trade["balance_before"]
    balance_after = round(balance_before + pnl, 2)
    set_setting("balance", str(balance_after))

    close_paper_trade(
        pt_id=pt_id,
        result=result,
        pnl=pnl,
        balance_after=balance_after,
        duration_min=duration_min,
    )

    return {
        "symbol": trade["symbol"],
        "direction": trade["direction"],
        "result": result,
        "pnl": pnl,
        "balance_before": balance_before,
        "balance_after": balance_after,
        "duration_min": duration_min,
        "risk_amount": trade["risk_amount"],
        "rr_ratio": trade["rr_ratio"],
    }
