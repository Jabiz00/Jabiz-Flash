from flash.providers import SolanaTokenAssessor

class Response:
    def __init__(self, data): self.data=data
    def raise_for_status(self): pass
    def json(self): return self.data

class FakeSession:
    def __init__(self):
        self.calls=[]
    def post(self, url, json, timeout):
        method=json["method"]; self.calls.append(("rpc",method))
        if method=="getAccountInfo":
            return Response({"result":{"value":{"owner":"Tokenkeg","data":{"parsed":{
                "type":"mint","info":{"mintAuthority":None,"freezeAuthority":None,
                "decimals":6,"supply":"1000000000","extensions":[]}}}}}})
        if method=="getTokenLargestAccounts":
            return Response({"result":{"value":[{"address":"acct1","amount":"100000000"}]}})
        if method=="getMultipleAccounts":
            return Response({"result":{"value":[{"data":{"parsed":{"info":{"owner":"holder1"}}}}]}})
        raise AssertionError(method)
    def get(self, url, params=None, headers=None, timeout=None):
        self.calls.append(("get",url))
        if "rugcheck" in url:
            return Response({"risks":[],"tokenProgram":"Tokenkeg"})
        if "jup.ag" in url:
            return Response({"outAmount":"12345","routePlan":[{"swapInfo":{}}],
                             "priceImpactPct":"0.005","router":"metis"})
        raise AssertionError(url)

def test_assessor_builds_fresh_evidence_and_size_specific_sell_quote():
    session=FakeSession()
    provider=SolanaTokenAssessor(session=session)
    result=provider.assess({"address":"mint","price":0.01},now=1000,notional_usd=50)
    assert result["mint_authority"] is None
    assert result["freeze_authority"] is None
    assert result["top10_holder_pct"] == 10
    assert result["sell_route_available"] is True
    assert result["execution_impact_pct"] == 0.5
    assert result["quote_amount_raw"] == "5000000000"
    assert result["quote_router"] == "metis"
    before=len(session.calls)
    cached=provider.assess({"address":"mint","price":0.01},now=1010,notional_usd=50)
    assert cached["checked_at"] == 1000
    assert len(session.calls) == before

def test_assessor_fails_closed_for_unsupported_token2022_extensions():
    class ExtensionSession(FakeSession):
        def post(self,url,json,timeout):
            if json["method"]=="getAccountInfo":
                return Response({"result":{"value":{"owner":"Tokenz","data":{"parsed":{
                    "type":"mint","info":{"mintAuthority":None,"freezeAuthority":None,
                    "decimals":6,"supply":"1000","extensions":[{"extension":"permanentDelegate"}]}}}}}})
            return super().post(url,json,timeout)
    provider=SolanaTokenAssessor(session=ExtensionSession())
    import pytest
    with pytest.raises(ValueError,match="extensions"):
        provider.assess({"address":"mint","price":1},now=1000,notional_usd=50)


def test_price_change_invalidates_cached_sell_quote():
    session=FakeSession()
    provider=SolanaTokenAssessor(session=session)
    provider.assess({"address":"mint","price":0.01},now=1000,notional_usd=50)
    before=len(session.calls)
    provider._last_jupiter_request = -100
    updated=provider.assess({"address":"mint","price":0.0102},now=1001,notional_usd=50)
    assert len(session.calls) > before
    assert updated["quote_amount_raw"] != "5000000000"
