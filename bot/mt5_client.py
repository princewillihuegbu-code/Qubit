# bot/mt5_client.py
import os
import requests

MT5_BRIDGE_URL = os.environ.get("MT5_BRIDGE_URL", "").rstrip("/")
TIMEOUT = 8

def _get(path: str) -> dict:
    if not MT5_BRIDGE_URL:
        return {"error": "MT5_BRIDGE_URL not configured"}
    try:
        headers = {"X-API-Key": os.environ.get("BRIDGE_API_KEY", "")}
        r = requests.get(f"{MT5_BRIDGE_URL}{path}", headers=headers, timeout=TIMEOUT)
        r.raise_for_status()
        return r.json()
    except requests.exceptions.ConnectionError:
        return {"error": "MT5 bridge unreachable"}
    except Exception as e:
        return {"error": str(e)}

def get_mt5_status() -> dict:   return _get("/status")
def get_mt5_account() -> dict:  return _get("/account")
def get_mt5_positions() -> dict: return _get("/positions")
def get_mt5_price(symbol: str) -> dict: return _get(f"/price/{symbol}")

def is_mt5_connected() -> bool:
    return get_mt5_status().get("connected", False)