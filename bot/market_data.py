"""
Qubit Markets — Twelve Data API client
Supports Forex, Stocks, and Crypto via the same time_series endpoint.
"""
from __future__ import annotations
import os
import time
import requests

TWELVE_DATA_BASE    = "https://api.twelvedata.com"
TWELVE_DATA_KEY_ENV = "TWELVE_DATA_API_KEY"

# ── Known symbol → Twelve Data format ─────────────────────────────────────────
SYMBOLS: dict[str, str] = {
    # Forex
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "XAUUSD": "XAU/USD",
    "AUDUSD": "AUD/USD",
    "USDCAD": "USD/CAD",
    "USDCHF": "USD/CHF",
    "NZDUSD": "NZD/USD",
    "EURGBP": "EUR/GBP",
    "EURJPY": "EUR/JPY",
    "GBPJPY": "GBP/JPY",
    "XAGUSD": "XAG/USD",
    # Stocks
    "AAPL":  "AAPL",
    "NVDA":  "NVDA",
    "MSFT":  "MSFT",
    "GOOGL": "GOOGL",
    "AMZN":  "AMZN",
    "TSLA":  "TSLA",
    "META":  "META",
    "NFLX":  "NFLX",
    "AMD":   "AMD",
    "INTC":  "INTC",
    "JPM":   "JPM",
    # Crypto
    "BTCUSD":  "BTC/USD",
    "ETHUSD":  "ETH/USD",
    "SOLUSD":  "SOL/USD",
    "BNBUSD":  "BNB/USD",
    "XRPUSD":  "XRP/USD",
    "ADAUSD":  "ADA/USD",
    "DOTUSD":  "DOT/USD",
    "LINKUSD": "LINK/USD",
}

# Default pairs kept for backward-compat with old scan functions
ALL_PAIRS = ["EURUSD", "GBPUSD", "XAUUSD", "BTCUSD"]


def is_api_configured() -> bool:
    return bool(os.environ.get(TWELVE_DATA_KEY_ENV, "").strip())


def _key() -> str:
    k = os.environ.get(TWELVE_DATA_KEY_ENV, "").strip()
    if not k:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY is not configured. "
            "Add it to Replit Secrets and restart the bot."
        )
    return k


def to_twelve_data_symbol(symbol: str) -> str:
    """
    Convert an internal symbol key to Twelve Data API format.
    Handles known mappings, then auto-detects forex / crypto / stock patterns.
    """
    sym = symbol.upper().replace("/", "")
    if sym in SYMBOLS:
        return SYMBOLS[sym]
    # 6-alpha → likely forex: EURUSD → EUR/USD
    if len(sym) == 6 and sym.isalpha():
        return f"{sym[:3]}/{sym[3:]}"
    # EndsWith USD and longer → likely crypto: BTCUSD → BTC/USD
    if sym.endswith("USD") and len(sym) > 6:
        return f"{sym[:-3]}/{sym[-3:]}"
    # Default: plain stock ticker
    return sym


def format_price(price: float, symbol: str) -> str:
    """Human-readable price string with appropriate precision per market."""
    sym = symbol.upper().replace("/", "")
    if sym in ("BTCUSD",):
        return f"${price:,.2f}"
    if sym in ("XAUUSD", "XAGUSD"):
        return f"${price:,.2f}"
    if sym.endswith("USD") and len(sym) > 6:
        return f"${price:,.4f}"
    if len(sym) == 6 and sym.isalpha() and not sym.endswith("USD"):
        return f"{price:.5f}"      # e.g. USDJPY, EURUSD, GBPUSD
    if len(sym) <= 5:
        return f"${price:,.2f}"   # stocks
    return f"{price:.4f}"


def fetch_candles(
    symbol: str,
    interval: str = "15min",
    outputsize: int = 60,
) -> list[dict]:
    """
    Fetch OHLCV candles from Twelve Data.
    Returns list of candle dicts, newest first.
    """
    twelve_sym = to_twelve_data_symbol(symbol)
    resp = requests.get(
        f"{TWELVE_DATA_BASE}/time_series",
        params={
            "symbol":     twelve_sym,
            "interval":   interval,
            "outputsize": outputsize,
            "apikey":     _key(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "error":
        raise ValueError(
            f"Twelve Data error [{symbol}]: {data.get('message', 'unknown error')}"
        )

    values = data.get("values", [])
    if not values:
        raise ValueError(f"No candle data for {symbol}")
    return values


def fetch_price(symbol: str) -> float:
    """Fetch just the current price (1 API credit, very fast)."""
    twelve_sym = to_twelve_data_symbol(symbol)
    resp = requests.get(
        f"{TWELVE_DATA_BASE}/price",
        params={"symbol": twelve_sym, "apikey": _key()},
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    if "price" not in data:
        raise ValueError(f"No price data for {symbol}: {data}")
    return float(data["price"])


def fetch_candles_batch(
    symbols: list[str],
    interval: str = "15min",
    outputsize: int = 60,
    delay_secs: float = 0.5,
) -> dict[str, list[dict] | Exception]:
    """Fetch candles for a list of symbols with rate-limit spacing."""
    results: dict[str, list[dict] | Exception] = {}
    for i, sym in enumerate(symbols):
        if i > 0:
            time.sleep(delay_secs)
        try:
            results[sym] = fetch_candles(sym, interval, outputsize)
        except Exception as exc:
            results[sym] = exc
    return results


def fetch_prices_batch(
    symbols: list[str],
    delay_secs: float = 0.5,
) -> dict[str, float | Exception]:
    """Fetch current prices for multiple symbols with rate-limit spacing."""
    results: dict[str, float | Exception] = {}
    for i, sym in enumerate(symbols):
        if i > 0:
            time.sleep(delay_secs)
        try:
            results[sym] = fetch_price(sym)
        except Exception as exc:
            results[sym] = exc
    return results


# Backward-compat aliases
def fetch_all_pairs(
    interval: str = "15min",
    outputsize: int = 60,
    delay_secs: float = 0.5,
) -> dict[str, list[dict] | Exception]:
    return fetch_candles_batch(ALL_PAIRS, interval, outputsize, delay_secs)
