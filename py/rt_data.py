"""Data pasar live dari Binance (spot, cadangan api.binance.com; XAU via futures atau PAXG)."""
import json
import time
from dataclasses import dataclass

import numpy as np
import requests

SPOT = ["https://data-api.binance.vision", "https://api.binance.com"]
FUT = "https://fapi.binance.com"
INTERVALS = {"1m": "1m", "5m": "5m", "15m": "15m", "1H": "1h", "4H": "4h", "1D": "1d"}
TF_SECONDS = {"1m": 60, "5m": 300, "15m": 900, "1H": 3600, "4H": 14400, "1D": 86400}

WATCHLIST = ["XAUUSDT", "BTCUSDT", "ETHUSDT", "BNBUSDT", "SOLUSDT", "XRPUSDT", "DOGEUSDT",
             "ADAUSDT", "AVAXUSDT", "LINKUSDT", "TONUSDT", "TRXUSDT", "DOTUSDT", "LTCUSDT"]

_http = requests.Session()
_http.headers["User-Agent"] = "RecognitoTrading/2.0"
_xau = {"src": None, "ts": 0.0}


@dataclass
class Candles:
    t: np.ndarray
    o: np.ndarray
    h: np.ndarray
    l: np.ndarray
    c: np.ndarray
    v: np.ndarray
    label: str

    def __len__(self):
        return len(self.c)


def _to_candles(rows, label):
    a = np.array([[float(x) for x in r[:6]] for r in rows], dtype=float)
    return Candles(a[:, 0], a[:, 1], a[:, 2], a[:, 3], a[:, 4], a[:, 5], label)


def _get(url, params, timeout=10):
    r = _http.get(url, params=params, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _spot(path, params):
    err = None
    for base in SPOT:
        try:
            return _get(base + path, params)
        except Exception as e:  # coba server cadangan
            err = e
    raise err


def fetch_klines(symbol, tf, limit=1000):
    iv = INTERVALS[tf]
    if symbol == "XAUUSDT":
        fresh = time.time() - _xau["ts"] < 600
        if not (fresh and _xau["src"] == "paxg"):
            try:
                rows = _get(FUT + "/fapi/v1/klines", {"symbol": "XAUUSDT", "interval": iv, "limit": limit}, 6)
                _xau.update(src="fut", ts=time.time())
                return _to_candles(rows, "XAUUSDT")
            except Exception:
                _xau.update(src="paxg", ts=time.time())
        rows = _spot("/api/v3/klines", {"symbol": "PAXGUSDT", "interval": iv, "limit": limit})
        return _to_candles(rows, "XAUUSDT (PAXG)")
    rows = _spot("/api/v3/klines", {"symbol": symbol, "interval": iv, "limit": limit})
    return _to_candles(rows, symbol)


def fetch_tickers(symbols):
    real = ["PAXGUSDT" if s == "XAUUSDT" else s for s in symbols]
    data = _spot("/api/v3/ticker/24hr", {"symbols": json.dumps(real, separators=(",", ":"))})
    out = {}
    for d in data:
        s = "XAUUSDT" if d["symbol"] == "PAXGUSDT" else d["symbol"]
        out[s] = (float(d["lastPrice"]), float(d["priceChangePercent"]))
    return out
