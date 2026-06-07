"""
Qubit Analytics (QA) — Signal Engine
EMA 20/50 crossover + RSI(14).  Works across Forex, Stocks, and Crypto.
All calculations are pure Python — no pandas dependency.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from market_data import fetch_candles_batch


# ── Technical indicator helpers ────────────────────────────────────────────────

def _ema(prices: list[float], period: int) -> list[float]:
    """EMA seeded with SMA, oldest-first output aligned to prices."""
    if len(prices) < period:
        return []
    k = 2.0 / (period + 1)
    sma = sum(prices[:period]) / period
    vals = [sma]
    for p in prices[period:]:
        vals.append(p * k + vals[-1] * (1.0 - k))
    pad = [float("nan")] * (period - 1)
    return pad + vals


def _rsi(closes: list[float], period: int = 14) -> float:
    """Wilder RSI. Returns 50.0 if insufficient data."""
    if len(closes) < period + 1:
        return 50.0
    deltas = [closes[i + 1] - closes[i] for i in range(len(closes) - 1)]
    gains  = [max(0.0, d) for d in deltas]
    losses = [abs(min(0.0, d)) for d in deltas]

    avg_g = sum(gains[:period])  / period
    avg_l = sum(losses[:period]) / period

    for g, l in zip(gains[period:], losses[period:]):
        avg_g = (avg_g * (period - 1) + g) / period
        avg_l = (avg_l * (period - 1) + l) / period

    if avg_l == 0:
        return 100.0
    return round(100.0 - 100.0 / (1.0 + avg_g / avg_l), 2)


# ── Price rounding per market / instrument ─────────────────────────────────────

def _round_price(value: float, symbol: str) -> float:
    sym = symbol.upper().replace("/", "")
    # JPY pairs: 3 decimal places
    if "JPY" in sym:
        return round(value, 3)
    # Gold / Silver
    if sym in ("XAUUSD", "XAGUSD"):
        return round(value, 2)
    # BTC (high value, low precision needed)
    if sym == "BTCUSD":
        return round(value, 1)
    # Other crypto (e.g. ETH ~$3k, SOL ~$150)
    if sym.endswith("USD") and len(sym) > 6:
        return round(value, 2)
    # Standard forex: EUR/USD, GBP/USD, etc.
    if len(sym) == 6 and sym.isalpha():
        return round(value, 5)
    # Stocks (AAPL, NVDA…)
    return round(value, 2)


# ── Signal dataclass ───────────────────────────────────────────────────────────

@dataclass
class MarketSignal:
    symbol:     str
    price:      float
    action:     str        # "BUY" | "SELL"
    entry:      float
    sl:         float
    tp:         float
    confidence: float
    rsi:        float
    ema20:      float
    ema50:      float
    crossover:  bool       # True = fresh cross this candle
    interval:   str = "15min"
    market:     str = "unknown"  # "forex" | "stock" | "crypto"


# ── Signal generation ─────────────────────────────────────────────────────────

def generate_signal(symbol: str, candles: list[dict]) -> MarketSignal | None:
    """
    candles: newest-first list (as returned by Twelve Data).
    Returns MarketSignal if a valid signal exists, else None.
    """
    if len(candles) < 52:
        return None

    asc    = list(reversed(candles))
    closes = [float(c["close"]) for c in asc]
    highs  = [float(c["high"])  for c in asc]
    lows   = [float(c["low"])   for c in asc]

    ema20s = _ema(closes, 20)
    ema50s = _ema(closes, 50)
    rsi    = _rsi(closes, 14)

    cur_price = closes[-1]
    cur_e20   = ema20s[-1]
    cur_e50   = ema50s[-1]
    prv_e20   = ema20s[-2]
    prv_e50   = ema50s[-2]

    # Guard NaN
    if any(v != v for v in (cur_e20, cur_e50, prv_e20, prv_e50)):
        return None

    ema_sep_pct = abs(cur_e20 - cur_e50) / cur_e50 * 100

    bullish_cross = prv_e20 <= prv_e50 and cur_e20 > cur_e50
    bearish_cross = prv_e20 >= prv_e50 and cur_e20 < cur_e50
    bullish_trend = cur_e20 > cur_e50
    bearish_trend = cur_e20 < cur_e50

    action:     str | None = None
    confidence: float      = 0.0
    crossover:  bool       = False

    if bullish_trend and 40.0 <= rsi <= 72.0:
        action     = "BUY"
        confidence = 65.0
        if bullish_cross:
            confidence += 10.0
            crossover   = True
        if 50.0 <= rsi <= 65.0:
            confidence += 5.0
        if ema_sep_pct >= 0.05:
            confidence += 5.0
        if ema_sep_pct >= 0.15:
            confidence += 5.0

    elif bearish_trend and 28.0 <= rsi <= 60.0:
        action     = "SELL"
        confidence = 65.0
        if bearish_cross:
            confidence += 10.0
            crossover   = True
        if 35.0 <= rsi <= 50.0:
            confidence += 5.0
        if ema_sep_pct >= 0.05:
            confidence += 5.0
        if ema_sep_pct >= 0.15:
            confidence += 5.0

    if action is None or confidence < 65.0:
        return None

    confidence = min(confidence, 95.0)

    r = lambda v: _round_price(v, symbol)

    recent_lows  = lows[-10:]
    recent_highs = highs[-10:]

    if action == "BUY":
        sl   = r(min(recent_lows))
        risk = cur_price - sl
        if risk <= 0:
            return None
        tp = r(cur_price + risk * 2.0)
    else:
        sl   = r(max(recent_highs))
        risk = sl - cur_price
        if risk <= 0:
            return None
        tp = r(cur_price - risk * 2.0)

    # Derive market type from symbol
    from watchlist import get_market_type
    market = get_market_type(symbol)

    return MarketSignal(
        symbol=symbol,
        price=r(cur_price),
        action=action,
        entry=r(cur_price),
        sl=sl,
        tp=tp,
        confidence=round(confidence, 1),
        rsi=rsi,
        ema20=r(cur_e20),
        ema50=r(cur_e50),
        crossover=crossover,
        market=market,
    )


def get_technical_summary(symbol: str, candles: list[dict]) -> dict | None:
    """
    Full technical snapshot for /analyze — returns even when no clean signal.
    """
    if len(candles) < 52:
        return None

    asc    = list(reversed(candles))
    closes = [float(c["close"]) for c in asc]
    highs  = [float(c["high"])  for c in asc]
    lows   = [float(c["low"])   for c in asc]

    ema20s = _ema(closes, 20)
    ema50s = _ema(closes, 50)
    rsi    = _rsi(closes, 14)

    cur_price = closes[-1]
    cur_e20   = ema20s[-1]
    cur_e50   = ema50s[-1]
    prv_e20   = ema20s[-2]
    prv_e50   = ema50s[-2]

    if any(v != v for v in (cur_e20, cur_e50, prv_e20, prv_e50)):
        return None

    r = lambda v: _round_price(v, symbol)

    bullish_cross = prv_e20 <= prv_e50 and cur_e20 > cur_e50
    bearish_cross = prv_e20 >= prv_e50 and cur_e20 < cur_e50
    bullish_trend = cur_e20 > cur_e50
    ema_sep_pct   = abs(cur_e20 - cur_e50) / cur_e50 * 100

    if bullish_cross:
        crossover_label = "Fresh bullish crossover ✅"
    elif bearish_cross:
        crossover_label = "Fresh bearish crossover 🔻"
    elif bullish_trend:
        crossover_label = "Bullish trend (EMA20 > EMA50)"
    else:
        crossover_label = "Bearish trend (EMA20 < EMA50)"

    # Try to get a signal
    sig = generate_signal(symbol, candles)

    return {
        "price":      r(cur_price),
        "ema20":      r(cur_e20),
        "ema50":      r(cur_e50),
        "rsi":        rsi,
        "trend":      "bullish" if bullish_trend else "bearish",
        "crossover":  crossover_label,
        "ema_sep":    round(ema_sep_pct, 3),
        "signal":     sig,
        "recent_high": r(max(highs[-10:])),
        "recent_low":  r(min(lows[-10:])),
    }


def scan_markets(
    symbols: list[str] | None = None,
    interval: str = "15min",
) -> list[tuple[str, MarketSignal | Exception | None]]:
    """
    Scan a list of symbols (defaults to full watchlist) for signals.
    Returns (symbol, result) tuples where result is MarketSignal, None, or Exception.
    """
    if symbols is None:
        from watchlist import get_watchlist
        symbols = get_watchlist()

    candle_data = fetch_candles_batch(symbols, interval=interval, outputsize=60)
    results = []
    for sym in symbols:
        raw = candle_data[sym]
        if isinstance(raw, Exception):
            results.append((sym, raw))
        else:
            results.append((sym, generate_signal(sym, raw)))
    return results
