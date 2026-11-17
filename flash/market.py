import time
import requests

BASE = "https://api.dexscreener.com/latest/dex/search"

class DexScreener:
    def __init__(self, timeout=10):
        self.session = requests.Session()
        self.timeout = timeout

    def search(self, term):
        response = self.session.get(BASE, params={"q": term}, timeout=self.timeout)
        response.raise_for_status()
        payload = response.json()
        pairs = payload.get("pairs") or []
        return [p for p in pairs if (p.get("chainId") or "").lower() == "solana"]

    def discover(self, terms, limit=80):
        found = {}
        for term in terms:
            try:
                for pair in self.search(term):
                    address = pair.get("pairAddress")
                    if address:
                        found[address] = pair
            except requests.RequestException as exc:
                print(f"[market] search {term!r} failed: {exc}")
            time.sleep(0.15)
        return list(found.values())[:limit]

def pair_snapshot(pair):
    base = pair.get("baseToken") or {}
    txns = pair.get("txns") or {}
    m5 = txns.get("m5") or {}
    h1 = txns.get("h1") or {}
    return {
        "pair": pair.get("pairAddress"),
        "token": base.get("symbol") or "UNKNOWN",
        "name": base.get("name") or "",
        "address": base.get("address") or "",
        "price": float(pair.get("priceUsd") or 0),
        "liquidity": float((pair.get("liquidity") or {}).get("usd") or 0),
        "volume24": float((pair.get("volume") or {}).get("h24") or 0),
        "buys5": int(m5.get("buys") or 0),
        "sells5": int(m5.get("sells") or 0),
        "buys1h": int(h1.get("buys") or 0),
        "sells1h": int(h1.get("sells") or 0),
        "created_ms": int(pair.get("pairCreatedAt") or 0),
        "url": pair.get("url") or "",
    }
