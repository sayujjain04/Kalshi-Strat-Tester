#!/usr/bin/env python3
"""
kalshi_client.py
─────────────────
Low-level Kalshi access: request signing, REST helpers, and parsers for the
*current* Kalshi v2 schema.

IMPORTANT — the API schema (as of 2026) returns money as decimal-dollar STRINGS
and quantities as fixed-point STRINGS, not integer cents:
    yes_bid_dollars="0.4100"   volume_fp="287133.96"   count_fp="44.00"
All the `d()` / `fp()` helpers below normalize those to plain floats.

Hosts (verified live):
    REST : https://external-api.kalshi.com/trade-api/v2   (api.elections.* also works)
    WS   : wss://api.elections.kalshi.com/trade-api/ws/v2 (external-api 404s on WS!)
"""
import base64, time, requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

import kalshi_creds as creds

# ── endpoints ───────────────────────────────────────────────────────────────
PROD = {
    "rest": "https://external-api.kalshi.com/trade-api/v2",
    "ws":   "wss://api.elections.kalshi.com/trade-api/ws/v2",
    "ws_path": "/trade-api/ws/v2",
    "key_id": creds.KEY_ID,
    "pem":    creds.PEM,
}
DEMO = {
    "rest": "https://demo-api.kalshi.co/trade-api/v2",
    "ws":   "wss://demo-api.kalshi.co/trade-api/ws/v2",
    "ws_path": "/trade-api/ws/v2",
    "key_id": creds.DEMO_KEY_ID,
    "pem":    creds.DEMO_PEM,
}


# ── value parsers (new schema → float) ───────────────────────────────────────
def d(v):
    """Decimal-dollar string ('0.4100') → float dollars (0.41). None-safe."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def fp(v):
    """Fixed-point string ('287133.96') → float quantity. None-safe."""
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def cents(dollars):
    """float dollars → integer cents for display (0.41 → 41). None → None."""
    if dollars is None:
        return None
    return round(dollars * 100)


# ── client ────────────────────────────────────────────────────────────────────
class KalshiClient:
    """Signs requests and talks to one environment (prod or demo)."""

    def __init__(self, env=PROD):
        self.env = env
        self._key = None
        self.sess = requests.Session()
        self.sess.headers["User-Agent"] = "KalshiResearch/2.0"

    # ----- auth -----
    @property
    def key(self):
        if self._key is None:
            if not self.env["pem"]:
                raise RuntimeError(
                    f"No private key configured for this environment. "
                    f"Set credentials in kalshi_creds.py."
                )
            self._key = serialization.load_pem_private_key(
                self.env["pem"].encode(), password=None
            )
        return self._key

    def _sign(self, ts, method, path):
        msg = (ts + method.upper() + path).encode()
        sig = self.key.sign(
            msg,
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()),
                        salt_length=padding.PSS.MAX_LENGTH),
            hashes.SHA256(),
        )
        return base64.b64encode(sig).decode()

    def headers(self, method, full_path):
        """Auth headers. `full_path` must include the /trade-api/v2 (or ws) prefix."""
        ts = str(int(time.time() * 1000))
        return {
            "KALSHI-ACCESS-KEY": self.env["key_id"],
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": self._sign(ts, method, full_path),
        }

    def ws_headers(self):
        return self.headers("GET", self.env["ws_path"])

    # ----- REST -----
    def get(self, path, params=None, auth=False):
        url = self.env["rest"] + path
        h = self.headers("GET", f"/trade-api/v2{path}") if auth else {}
        r = self.sess.get(url, params=params, headers=h, timeout=15)
        if r.status_code != 200:
            return None, f"HTTP {r.status_code}: {r.text[:200]}"
        return r.json(), None

    def post(self, path, body, auth=True):
        url = self.env["rest"] + path
        h = self.headers("POST", f"/trade-api/v2{path}")
        h["Content-Type"] = "application/json"
        r = self.sess.post(url, json=body, headers=h, timeout=15)
        if r.status_code not in (200, 201):
            return None, f"HTTP {r.status_code}: {r.text[:300]}"
        return r.json(), None

    # ----- convenience -----
    def markets(self, series_ticker=None, status="open", limit=200, cursor=None):
        """Paginate markets. Returns a flat list."""
        out, seen_cursor = [], cursor
        while True:
            p = {"limit": limit, "status": status}
            if series_ticker:
                p["series_ticker"] = series_ticker
            if seen_cursor:
                p["cursor"] = seen_cursor
            data, err = self.get("/markets", p)
            if err or not data:
                break
            out.extend(data.get("markets", []))
            seen_cursor = data.get("cursor")
            if not seen_cursor or len(out) >= limit * 8:
                break
        return out

    def market(self, ticker):
        data, err = self.get(f"/markets/{ticker}")
        return (data or {}).get("market"), err
