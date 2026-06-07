"""
Qubit Analytics (QA) — Signal Engine
EMA 20/50 crossover + RSI(14) filter.
All calculations are pure Python — no pandas dependency.
"""
from __future__ import annotations
from dataclasses import dataclass
from market_data import fetch_all_pairs, ALL_PAIRS


# ── Technical indicator helpers ────────────────────────────────────────────────

def _ema(prices: list[float], period: int) -> list[float]:
    """Exponential Moving Average, oldest-first output aligned to prices."""
    if len(prices) < period:
        return []
    k = 2.0 / (period + 1)
    # seed with SMA of first `period` values
    sma = sum(prices[:period]) / period
    ema_vals = [sma]
    for p in prices[period:]:
        ema_vals.append(p * k + ema_vals[-1] * (1.0 - k))
    # pad front so output length matches prices
    pad = [float("nan")] * (period - 1)
    return pad + ema_vals


def _rsi(closes: list[float], period: int = 14) -> float:
    """Wilder RSI — uses simple average for seed, then Wilder smoothing."""
    if len(closes) < period + 1:
        return 50.0  # neutral default
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains = [max(0.0, d) for d in deltas]
    losses = [abs(min(0.0, d)) for d in deltas]

    # seed averages
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    # Wilder smoothing for remaining deltas
    for g, l in zip(gains[period:], losses[period:]):
        avg_gain = (avg_gain * (period - 1) + g) / period
        avg_loss = (avg_loss * (period - 1) + l) / period

    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


# ── Signal generation ─────────────────────────────────────────────────────────

@dataclass
class MarketSignal:
    symbol: str
    price: float
    action: str        # "BUY" | "SELL"
    entry: float
    sl: float
    tp: float
    confidence: float
    rsi: float
    ema20: float
    ema50: float
    crossover: bool    # True = fresh cross, False = trend continuation
    interval: str = "15min"


def _round_price(value: float, symbol: str) -> float:
    """Round to appropriate decimal places per instrument."""
    if symbol == "USDJPY":
        return round(value, 3)
    if symbol == "XAUUSD":
        return round(value, 2)
    return round(value, 5)


def generate_signal(symbol: str, candles: list[dict]) -> MarketSignal | None:
    """
    candles: list of OHLCV dicts, newest first (as returned by Twelve Data).
    Returns a MarketSignal if a valid signal is detected, otherwise None.
    """
    if len(candles) < 52:
        return None

    # Reverse to oldest-first for calculations
    asc = list(reversed(candles))
    closes = [float(c["close"]) for c in asc]
    highs  = [float(c["high"])  for c in asc]
    lows   = [float(c["low"])   for c in asc]

    ema20_series = _ema(closes, 20)
    ema50_series = _ema(closes, 50)
    rsi = _rsi(closes, 14)

    cur_price = closes[-1]
    cur_ema20 = ema20_series[-1]
    cur_ema50 = ema50_series[-1]
    prv_ema20 = ema20_series[-2]
    prv_ema50 = ema50_series[-2]

    # Skip if any NaN
    if any(v != v for v in (cur_ema20, cur_ema50, prv_ema20, prv_ema50)):
        return None

    ema_sep_pct = abs(cur_ema20 - cur_ema50) / cur_ema50 * 100

    bullish_cross = prv_ema20 <= prv_ema50 and cur_ema20 > cur_ema50
    bearish_cross = prv_ema20 >= prv_ema50 and cur_ema20 < cur_ema50
    bullish_trend = cur_ema20 > cur_ema50
    bearish_trend = cur_ema20 < cur_ema50

    action: str | None = None
    confidence = 0.0
    crossover = False

    if bullish_trend and 40.0 <= rsi <= 72.0:
        action = "BUY"
        confidence = 65.0
        if bullish_cross:
            confidence += 10.0
            crossover = True
        if 50.0 <= rsi <= 65.0:   # ideal RSI zone
            confidence += 5.0
        if ema_sep_pct >= 0.05:   # meaningful separation
            confidence += 5.0
        if ema_sep_pct >= 0.15:   # strong trend
            confidence += 5.0

    elif bearish_trend and 28.0 <= rsi <= 60.0:
        action = "SELL"
        confidence = 65.0
        if bearish_cross:
            confidence += 10.0
            crossover = True
        if 35.0 <= rsi <= 50.0:
            confidence += 5.0
        if ema_sep_pct >= 0.05:
            confidence += 5.0
        if ema_sep_pct >= 0.15:
            confidence += 5.0

    if action is None or confidence < 65.0:
        return None

    confidence = min(confidence, 95.0)

    # SL/TP from recent swing high/low (10-candle lookback)
    recent_lows  = lows[-10:]
    recent_highs = highs[-10:]
    r = _round_price

    if action == "BUY":
        sl   = r(min(recent_lows), symbol)
        risk = cur_price - sl
        if risk <= 0:
            return None
        tp = r(cur_price + risk * 2.0, symbol)
    else:
        sl   = r(max(recent_highs), symbol)
        risk = sl - cur_price
        if risk <= 0:
            return None
        tp = r(cur_price - risk * 2.0, symbol)

    return MarketSignal(
        symbol=symbol,
        price=r(cur_price, symbol),
        action=action,
        entry=r(cur_price, symbol),
        sl=sl,
        tp=tp,
        confidence=round(confidence, 1),
        rsi=rsi,
        ema20=r(cur_ema20, symbol),
        ema50=r(cur_ema50, symbol),
        crossover=crossover,
    )


def scan_markets(interval: str = "15min") -> list[MarketSignal | Exception | None]:
    """
    Scan all tracked pairs and return results.
    Returns a list of (symbol, result) tuples where result is
    a MarketSignal, None (no signal), or an Exception.
    """
    candle_data = fetch_all_pairs(interval=interval, outputsize=60)
    results = []
    for symbol in ALL_PAIRS:
        raw = candle_data[symbol]
        if isinstance(raw, Exception):
            results.append((symbol, raw))
        else:
            results.append((symbol, generate_signal(symbol, raw)))
    return results
