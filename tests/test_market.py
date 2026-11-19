from flash.market import pair_snapshot
def test_pair_snapshot():
    raw={"pairAddress":"pair","baseToken":{"symbol":"ABC","address":"mint"},"priceUsd":"1.25",
      "liquidity":{"usd":50000},"volume":{"h24":90000},"txns":{"m5":{"buys":8,"sells":3}},
      "pairCreatedAt":1000,"url":"https://dexscreener.com"}
    s=pair_snapshot(raw)
    assert s["pair"]=="pair" and s["price"]==1.25 and s["buys5"]==8
