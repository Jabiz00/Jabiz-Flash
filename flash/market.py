import time
import requests
SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"

class DexScreener:
    def __init__(self, timeout=12):
        self.session = requests.Session()
        self.timeout = timeout
    def search(self, term):
        r = self.session.get(SEARCH_URL, params={"q":term}, timeout=self.timeout)
        r.raise_for_status()
        return [p for p in (r.json().get("pairs") or []) if (p.get("chainId") or "").lower()=="solana"]
    def discover(self, terms, limit=80):
        found = {}
        for term in terms:
            try:
                for pair in self.search(term):
                    if pair.get("pairAddress"):
                        found[pair["pairAddress"]] = pair
            except requests.RequestException as exc:
                print(f"[market] {term}: {exc}")
            time.sleep(0.12)
        return list(found.values())[:limit]

def pair_snapshot(pair):
    base, tx = pair.get("baseToken") or {}, pair.get("txns") or {}
    m5 = tx.get("m5") or {}
    return {"pair":pair.get("pairAddress"),"token":base.get("symbol") or "UNKNOWN",
      "address":base.get("address") or "","price":float(pair.get("priceUsd") or 0),
      "liquidity":float((pair.get("liquidity") or {}).get("usd") or 0),
      "volume24":float((pair.get("volume") or {}).get("h24") or 0),
      "buys5":int(m5.get("buys") or 0),"sells5":int(m5.get("sells") or 0),
      "created_ms":int(pair.get("pairCreatedAt") or 0),"url":pair.get("url") or ""}
