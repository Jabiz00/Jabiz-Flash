import time
import requests

SEARCH_URL = "https://api.dexscreener.com/latest/dex/search"


class DexScreener:
    def __init__(self, timeout=12):
        self.session = requests.Session()
        self.timeout = timeout
        self.metrics = self._empty_metrics()

    @staticmethod
    def _empty_metrics():
        return {
            "provider": "DexScreener REST",
            "request_count": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "last_success_at": None,
            "last_error": "",
            "terms_searched": 0,
            "pairs_returned": 0,
        }

    def status(self):
        return dict(self.metrics)

    def search(self, term):
        self.metrics["request_count"] += 1
        try:
            response = self.session.get(
                SEARCH_URL, params={"q": term}, timeout=self.timeout
            )
            self.metrics["last_http_status"] = response.status_code
            response.raise_for_status()
            payload = response.json()
            self.metrics["successful_requests"] += 1
            self.metrics["last_success_at"] = time.time()
            return [
                pair for pair in (payload.get("pairs") or [])
                if (pair.get("chainId") or "").lower() == "solana"
            ]
        except (requests.RequestException, ValueError) as exc:
            self.metrics["failed_requests"] += 1
            self.metrics["last_error"] = str(exc)[:240]
            raise

    def discover(self, terms, limit=80):
        self.metrics = self._empty_metrics()
        found = {}
        for term in terms:
            self.metrics["terms_searched"] += 1
            try:
                for pair in self.search(term):
                    if pair.get("pairAddress"):
                        found[pair["pairAddress"]] = pair
            except (requests.RequestException, ValueError) as exc:
                print(f"[market] {term}: {exc}")
            time.sleep(0.12)
        result = list(found.values())[:limit]
        self.metrics["pairs_returned"] = len(result)
        return result


def pair_snapshot(pair):
    base, tx = pair.get("baseToken") or {}, pair.get("txns") or {}
    m5 = tx.get("m5") or {}
    return {
        "pair": pair.get("pairAddress"),
        "token": base.get("symbol") or "UNKNOWN",
        "address": base.get("address") or "",
        "price": float(pair.get("priceUsd") or 0),
        "liquidity": float((pair.get("liquidity") or {}).get("usd") or 0),
        "volume24": float((pair.get("volume") or {}).get("h24") or 0),
        "buys5": int(m5.get("buys") or 0),
        "sells5": int(m5.get("sells") or 0),
        "created_ms": int(pair.get("pairCreatedAt") or 0),
        "url": pair.get("url") or "",
    }
