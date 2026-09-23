"""
Converts a dollar risk amount into a valid MT5 lot size,
using the symbol's real tick value/size from the broker.
"""
from mt5_client import get_mt5_symbol_info


def calculate_lot_size(symbol: str, risk_amount: float, entry: float, stop_loss: float) -> tuple[float | None, str]:
    """
    Returns (lots, error). lots is None if it couldn't be calculated.
    """
    info = get_mt5_symbol_info(symbol)
    if "error" in info:
        return None, info["error"]

    sl_distance = abs(entry - stop_loss)
    if sl_distance <= 0:
        return None, "Invalid SL distance"

    tick_value = info["tick_value"]
    tick_size = info["tick_size"]
    if tick_size <= 0 or tick_value <= 0:
        return None, "Broker returned invalid tick data for this symbol"

    # Loss in account currency per 1.0 lot if price moves sl_distance
    loss_per_lot = (sl_distance / tick_size) * tick_value
    if loss_per_lot <= 0:
        return None, "Could not compute loss per lot"

    raw_lots = risk_amount / loss_per_lot

    step = info["volume_step"]
    vmin = info["volume_min"]
    vmax = info["volume_max"]

    # Round down to nearest valid step, never round up past your risk budget
    lots = (raw_lots // step) * step
    lots = round(lots, 2)

    if lots < vmin:
        return None, f"Risk amount too small for min lot size ({vmin}) on {symbol}"
    if lots > vmax:
        lots = vmax

    return lots, ""
