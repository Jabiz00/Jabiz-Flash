from flash.market import pair_snapshot
def test_pair_snapshot():
    raw={"pairAddress":"pair","baseToken":{"symbol":"ABC","address":"mint"},"priceUsd":"1.25",
      "liquidity":{"usd":50000},"volume":{"h24":90000},"txns":{"m5":{"buys":8,"sells":3}},
      "pairCreatedAt":1000,"url":"https://dexscreener.com"}
    s=pair_snapshot(raw)
    assert s["pair"]=="pair" and s["price"]==1.25 and s["buys5"]==8


def test_discover_refreshes_exact_open_position_pairs():
    from flash.market import DexScreener
    class Response:
        status_code=200
        def raise_for_status(self): pass
        def json(self):
            return {"pairs":[{"chainId":"solana","pairAddress":"open-pair"}]}
    class Session:
        def get(self,url,params=None,timeout=None):
            if "/pairs/solana/" in url: return Response()
            return Response()
    market=DexScreener()
    market.session=Session()
    pairs=market.fetch_pairs(["open-pair"])
    assert pairs[0]["pairAddress"]=="open-pair"
    assert market.metrics["successful_requests"]==1
