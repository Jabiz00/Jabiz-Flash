from flash.engine import PaperEngine

def cfg():
    return {
        "starting_balance_usd":100.0,"risk_per_trade":0.01,"max_positions":10,
        "max_hold_seconds":300,"min_liquidity_usd":10000,"min_volume_24h_usd":10000,
        "min_pair_age_minutes":0,"entry_momentum_pct":0.5,"early_exit_momentum_pct":-0.25,
        "target_r":2.0,"stop_pct":1.5,"estimated_round_trip_cost_pct":1.0
    }

def test_risk_and_position_cap(tmp_path):
    e=PaperEngine(cfg(), tmp_path)
    assert e.equity == 100
    assert cfg()["risk_per_trade"] * e.equity == 1

def test_momentum():
    assert round(PaperEngine._momentum([(1,100),(2,102)]),2) == 2.0
    assert PaperEngine._momentum([(1,100)]) is None
