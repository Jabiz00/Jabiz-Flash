"""DexScreener REST discovery and defensive Solana pair normalization."""
import time
import requests

SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"
PAIRS_URL = "https://api.dexscreener.com/latest/dex/pairs/solana"

def _num(value, default=0.0):
    try:
        result = float(value)
        return result if result == result and abs(result) != float("inf") else default
    except (TypeError, ValueError, OverflowError):
        return default

class DexScreener:
    def __init__(self, timeout=12):
        self.session = requests.Session()
        self.timeout = timeout
        self.metrics = self._empty_metrics()
    @staticmethod
    def _empty_metrics():
        return {"provider":"DexScreener REST","request_count":0,"successful_requests":0,
                "failed_requests":0,"last_success_at":None,"scan_last_success_at":None,"last_error":"",
                "terms_searched":0,"pairs_returned":0}
    def status(self): return dict(self.metrics)
    def search(self, term):
        self.metrics["request_count"] += 1
        try:
            response = self.session.get(SEARCH_URL, params={"q":term}, timeout=self.timeout)
            self.metrics["last_http_status"] = response.status_code
            response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict): raise ValueError("Unexpected DexScreener payload")
            self.metrics["successful_requests"] += 1
            self.metrics["last_success_at"] = time.time()
            self.metrics["scan_last_success_at"] = self.metrics["last_success_at"]
            self.metrics["last_error"] = ""
            return [p for p in (payload.get("pairs") or [])
                    if isinstance(p, dict) and (p.get("chainId") or "").lower()=="solana"]
        except (requests.RequestException, ValueError) as exc:
            self.metrics["failed_requests"] += 1
            self.metrics["last_error"] = str(exc)[:240]
            raise
    def fetch_pairs(self, pair_addresses):
        addresses = [str(x) for x in pair_addresses if x]
        if not addresses:
            return []
        self.metrics["request_count"] += 1
        try:
            response = self.session.get(PAIRS_URL + "/" + ",".join(addresses[:30]), timeout=self.timeout)
            self.metrics["last_http_status"] = response.status_code
            response.raise_for_status()
            payload = response.json()
            pairs = payload.get("pairs") if isinstance(payload, dict) else None
            if not isinstance(pairs, list):
                raise ValueError("Unexpected DexScreener pair response")
            self.metrics["successful_requests"] += 1
            self.metrics["last_success_at"] = time.time()
            self.metrics["scan_last_success_at"] = self.metrics["last_success_at"]
            self.metrics["last_error"] = ""
            return [p for p in pairs if isinstance(p, dict) and p.get("pairAddress")]
        except (requests.RequestException, ValueError) as exc:
            self.metrics["failed_requests"] += 1
            self.metrics["last_error"] = str(exc)[:240]
            print(f"[market] open-position refresh failed: {exc}")
            return []

    def discover(self, terms, limit=80, watch_pairs=None):
        previous_success = self.metrics.get("last_success_at")
        self.metrics = self._empty_metrics()
        self.metrics["last_success_at"] = previous_success
        found = {}
        for term in terms:
            self.metrics["terms_searched"] += 1
            try:
                for pair in self.search(term):
                    if pair.get("pairAddress"): found[pair["pairAddress"]] = pair
            except (requests.RequestException, ValueError) as exc:
                print(f"[market] {term}: {exc}")
            time.sleep(0.12)
        watched = set(watch_pairs or [])
        for pair in self.fetch_pairs(watched):
            found[pair["pairAddress"]] = pair
        selected = list(found.values())[:max(0,int(limit))]
        selected.extend(pair for address,pair in found.items() if address in watched)
        result = list({p["pairAddress"]:p for p in selected}.values())
        self.metrics["pairs_returned"] = len(result)
        return result

def pair_snapshot(pair):
    if not isinstance(pair, dict): raise ValueError("Pair payload must be an object")
    base, tx = pair.get("baseToken") or {}, pair.get("txns") or {}
    m5 = tx.get("m5") or {}
    volume = pair.get("volume") or {}
    buys5, sells5 = int(_num(m5.get("buys"))), int(_num(m5.get("sells")))
    # DexScreener search exposes USD volume at h1/h24; buy/sell USD flow is not
    # included in all search payloads, so do not fabricate it from transaction counts.
    return {
        "pair":pair.get("pairAddress"), "token":base.get("symbol") or "UNKNOWN",
        "address":base.get("address") or "", "price":_num(pair.get("priceUsd")),
        "liquidity":_num((pair.get("liquidity") or {}).get("usd")),
        "volume24":_num(volume.get("h24")), "volume1h":_num(volume.get("h1")),
        "buys5":buys5, "sells5":sells5,
        "buy_volume_ratio":None, "volume_acceleration":None,
        "execution_impact_pct":None,
        "created_ms":int(_num(pair.get("pairCreatedAt"))),
        "url":pair.get("url") or "",
    }
