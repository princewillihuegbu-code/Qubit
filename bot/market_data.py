import os
import time
import requests

TWELVE_DATA_BASE = "https://api.twelvedata.com"
TWELVE_DATA_KEY_ENV = "TWELVE_DATA_API_KEY"

SYMBOLS: dict[str, str] = {
    "EURUSD": "EUR/USD",
    "GBPUSD": "GBP/USD",
    "USDJPY": "USD/JPY",
    "XAUUSD": "XAU/USD",
}

ALL_PAIRS = list(SYMBOLS.keys())


def is_api_configured() -> bool:
    return bool(os.environ.get(TWELVE_DATA_KEY_ENV, "").strip())


def _key() -> str:
    k = os.environ.get(TWELVE_DATA_KEY_ENV, "").strip()
    if not k:
        raise RuntimeError(
            "TWELVE_DATA_API_KEY is not configured. "
            "Add it to Replit Secrets then restart the bot."
        )
    return k


def fetch_candles(
    symbol: str,
    interval: str = "15min",
    outputsize: int = 60,
) -> list[dict]:
    """
    Fetch OHLCV candles from Twelve Data.
    Returns list of candle dicts, newest first.
    Each dict has keys: datetime, open, high, low, close, volume.
    """
    twelve_sym = SYMBOLS.get(symbol, symbol)
    resp = requests.get(
        f"{TWELVE_DATA_BASE}/time_series",
        params={
            "symbol": twelve_sym,
            "interval": interval,
            "outputsize": outputsize,
            "apikey": _key(),
        },
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    if data.get("status") == "error":
        raise ValueError(
            f"Twelve Data API error for {symbol}: {data.get('message', 'unknown error')}"
        )

    values = data.get("values", [])
    if not values:
        raise ValueError(f"No candle data returned for {symbol}")

    return values


def fetch_all_pairs(
    interval: str = "15min",
    outputsize: int = 60,
    delay_secs: float = 0.5,
) -> dict[str, list[dict] | Exception]:
    """
    Fetch candles for all tracked pairs.
    Returns dict: symbol -> candle list (or Exception on failure).
    Adds a small delay between requests to respect rate limits.
    """
    results: dict[str, list[dict] | Exception] = {}
    for i, symbol in enumerate(ALL_PAIRS):
        if i > 0:
            time.sleep(delay_secs)
        try:
            results[symbol] = fetch_candles(symbol, interval, outputsize)
        except Exception as exc:
            results[symbol] = exc
    return results
