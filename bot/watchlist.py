"""
Qubit — Watchlist management
Persists in the SQLite settings table under the key 'watchlist'.
"""
from __future__ import annotations
import os
import sys
sys.path.insert(0, os.path.dirname(__file__))

from database import get_setting, set_setting

# ── Default symbols ────────────────────────────────────────────────────────────

DEFAULT_WATCHLIST: list[str] = [
    "EURUSD",   # Forex
    "GBPUSD",   # Forex
    "XAUUSD",   # Forex (Gold)
    "AAPL",     # Stock
    "NVDA",     # Stock
    "BTCUSD",   # Crypto
    "ETHUSD",   # Crypto
]

# ── Symbol classification ──────────────────────────────────────────────────────

MARKET_TYPES: dict[str, str] = {
    # Forex
    "EURUSD": "forex", "GBPUSD": "forex", "USDJPY": "forex",
    "EURJPY": "forex", "GBPJPY": "forex", "AUDUSD": "forex",
    "USDCAD": "forex", "USDCHF": "forex", "NZDUSD": "forex",
    "EURGBP": "forex", "XAUUSD": "forex", "XAGUSD": "forex",
    # Stocks
    "AAPL": "stock", "NVDA": "stock", "MSFT": "stock",
    "GOOGL": "stock", "AMZN": "stock", "TSLA": "stock",
    "META": "stock",  "NFLX": "stock", "AMD":  "stock",
    "INTC": "stock",  "BABA": "stock", "V":    "stock",
    "JPM":  "stock",  "BAC":  "stock", "XOM":  "stock",
    # Crypto
    "BTCUSD": "crypto", "ETHUSD": "crypto", "SOLUSD": "crypto",
    "BNBUSD": "crypto", "XRPUSD": "crypto", "ADAUSD": "crypto",
    "DOTUSD": "crypto", "LINKUSD": "crypto",
}

MARKET_ICONS: dict[str, str] = {
    "forex":   "💱",
    "stock":   "📊",
    "crypto":  "🪙",
    "unknown": "❓",
}

MARKET_LABELS: dict[str, str] = {
    "forex":   "Forex",
    "stock":   "Stocks",
    "crypto":  "Crypto",
    "unknown": "Other",
}

_WL_KEY = "watchlist"
MAX_WATCHLIST = 20


def get_market_type(symbol: str) -> str:
    return MARKET_TYPES.get(symbol.upper(), "unknown")


def normalise(symbol: str) -> str:
    """Normalise user input to internal key format (e.g. BTC/USD → BTCUSD)."""
    return symbol.upper().replace("/", "").strip()


def get_watchlist() -> list[str]:
    raw = get_setting(_WL_KEY, "")
    if not raw:
        return list(DEFAULT_WATCHLIST)
    return [s.strip() for s in raw.split(",") if s.strip()]


def _save(symbols: list[str]) -> None:
    set_setting(_WL_KEY, ",".join(symbols))


def add_to_watchlist(symbol: str) -> tuple[bool, str]:
    sym = normalise(symbol)
    wl  = get_watchlist()
    if sym in wl:
        return False, f"{sym} is already on your watchlist."
    if len(wl) >= MAX_WATCHLIST:
        return False, f"Watchlist is full (max {MAX_WATCHLIST} symbols)."
    wl.append(sym)
    _save(wl)
    mtype = get_market_type(sym)
    icon  = MARKET_ICONS.get(mtype, "❓")
    return True, f"✅ {sym} added  {icon} {MARKET_LABELS.get(mtype, 'Unknown')}"


def remove_from_watchlist(symbol: str) -> tuple[bool, str]:
    sym = normalise(symbol)
    wl  = get_watchlist()
    if sym not in wl:
        return False, f"{sym} is not on your watchlist."
    wl.remove(sym)
    _save(wl)
    return True, f"🗑 {sym} removed from watchlist."


def reset_watchlist() -> None:
    _save(list(DEFAULT_WATCHLIST))


def group_by_market(symbols: list[str]) -> dict[str, list[str]]:
    """Group symbols into {market_type: [symbols]} dict."""
    groups: dict[str, list[str]] = {}
    for sym in symbols:
        mtype = get_market_type(sym)
        groups.setdefault(mtype, []).append(sym)
    return groups
