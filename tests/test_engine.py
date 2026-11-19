from flash.engine import PaperEngine

def cfg():
    return {"starting_balance_usd":100.0,"risk_per_trade":0.01,"max_positions":10,
      "max_hold_seconds":300,"min_liquidity_usd":10000,"min_volume_24h_usd":10000,
      "min_pair_age_minutes":0,"entry_momentum_pct":0.5,"early_exit_momentum_pct":-0.25,
      "target_r":2.0,"stop_pct":1.5,"estimated_round_trip_cost_pct":1.0,
      "trail_after_r":1.0,"trailing_drawdown_pct":0.8}

def snap(price,pair="p1"):
    return {"pair":pair,"price":price,"token":"TEST","address":"mint","liquidity":50000,
      "volume24":100000,"buys5":10,"sells5":2,"created_ms":1,"url":"https://example.com"}

def test_cost_included_risk_sizing(tmp_path):
    e=PaperEngine(cfg(),tmp_path); e.history["p1"]=[[1,100],[2,101]]
    e.update(snap(102),now=3); p=e.positions["p1"]
    sl=p.quantity*(p.entry-p.initial_stop)
    costs=(p.entry+p.initial_stop)*p.quantity*0.01/2
    assert sl+costs <= 1.000001

def test_max_ten_positions(tmp_path):
    e=PaperEngine(cfg(),tmp_path)
    for i in range(12):
        key=f"p{i}"; e.history[key]=[[1,100],[2,101]]
        e.update(snap(102,key),now=3)
    assert len(e.positions)==10

def test_persisted_history(tmp_path):
    e=PaperEngine(cfg(),tmp_path); e.history["p1"]=[[10,1.0],[11,1.1]]; e.save_state()
    e2=PaperEngine(cfg(),tmp_path)
    assert e2.history["p1"]==[[10.0,1.0],[11.0,1.1]]

def test_momentum():
    assert round(PaperEngine.momentum([[1,100],[2,102]]),2)==2.0
    assert PaperEngine.momentum([[1,100]]) is None
def test_dashboard_position_details(tmp_path):
    e=PaperEngine(cfg(),tmp_path)
    e.history["p1"]=[[1,100],[2,101]]
    e.update(snap(102),now=3)
    status=e.dashboard_status()
    p=status["open_positions"][0]
    assert p["address"]=="mint"
    assert p["contract_url"]=="https://solscan.io/token/mint"
    assert p["dex_url"]=="https://example.com"
    assert p["current_price"]==102
    assert p["last_price"]==102
    assert p["held_seconds"]>=0
    assert "unrealized_pnl" in p

def test_closed_trade_history_includes_contract_and_hold_time(tmp_path):
    e=PaperEngine(cfg(),tmp_path)
    e.history["p1"]=[[1,100],[2,101]]
    e.update(snap(102),now=3)
    e.close("p1",103,"test_exit",now=13)
    trade=e.dashboard_status()["recent_trades"][0]
    assert trade["address"]=="mint"
    assert trade["entry"]==102
    assert trade["exit"]==103
    assert trade["holding_seconds"]==10
    assert trade["reason"]=="test_exit"
