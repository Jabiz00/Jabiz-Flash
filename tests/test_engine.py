from flash.engine import PaperEngine

def cfg():
    return {"starting_balance_usd":100.0,"risk_per_trade":0.01,"max_positions":10,
      "max_hold_seconds":300,"min_liquidity_usd":10000,"min_volume_24h_usd":10000,
      "min_pair_age_minutes":0,"min_transactions_5m":4,"minimum_candidate_score":70,"execution_impact_limit_pct":1.0,"early_exit_momentum_pct":-0.25,
      "target_r":2.0,"stop_pct":1.5,"estimated_round_trip_cost_pct":1.0,
      "trail_after_r":1.0,"trailing_drawdown_pct":0.8}

def safe_provider(snap, now):
    return {"mint_authority":None,"freeze_authority":None,"top10_holder_pct":22,
      "rugcheck_status":"good","critical_risks":[],"sell_route_available":True,"checked_at":now}

def make_engine(cfg_value, data_dir, **kwargs):
    return PaperEngine(cfg_value, data_dir, safety_provider=safe_provider, **kwargs)

def snap(price,pair="p1"):
    return {"pair":pair,"price":price,"token":"TEST","address":"mint","liquidity":50000,
      "volume24":100000,"volume1h":12000,"buy_volume_ratio":0.68,"volume_acceleration":2.0,"execution_impact_pct":0.2,"buys5":10,"sells5":2,"created_ms":1,"url":"https://example.com"}

def test_cost_included_risk_sizing(tmp_path):
    e=make_engine(cfg(),tmp_path); e.history["p1"]=[[1,100],[2,101]]
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

def test_telegram_entry_and_exit_alert_details(tmp_path):
    class CaptureNotifier:
        def __init__(self): self.messages=[]
        def send(self,message): self.messages.append(message)
    notifier=CaptureNotifier()
    e=PaperEngine(cfg(),tmp_path,notifier=notifier)
    e.history['p1']=[[1,100],[2,101]]
    e.update(snap(102),now=3)
    assert len(notifier.messages)==1
    entry=notifier.messages[0]
    assert 'PAPER ENTRY' in entry and 'Target:' in entry
    assert 'Risk budget:' in entry and 'solscan.io/token/mint' in entry
    assert 'SIMULATED' in entry
    e.close('p1',103,'test_exit',now=13)
    assert len(notifier.messages)==2
    exit_message=notifier.messages[1]
    assert 'PAPER EXIT' in exit_message and 'Net P&L:' in exit_message
    assert 'Held: 10s' in exit_message and 'test_exit' in exit_message
    assert 'Estimated costs:' in exit_message and 'SIMULATED' in exit_message

def test_scan_diagnostics_explain_rejections_and_entries(tmp_path):
    e = make_engine(cfg(), tmp_path)
    e.scan_metrics = e.empty_scan_metrics()
    e.update({**snap(102), "liquidity": 100}, now=3)
    assert e.scan_metrics["discovered"] == 1
    assert e.scan_metrics["rejected_liquidity"] == 1
    e.history["p1"] = [[1, 100], [2, 101]]
    e.update(snap(102), now=4)
    assert e.scan_metrics["qualified_entries"] == 1
    status = e.dashboard_status()
    assert status["scanner"]["metrics"]["qualified_entries"] == 1
    assert status["scanner"]["api"]["provider"] == "DexScreener REST"


def test_scan_diagnostics_distinguish_volume_and_flow(tmp_path):
    e = PaperEngine(cfg(), tmp_path)
    e.scan_metrics = e.empty_scan_metrics()
    e.update({**snap(102, "low-volume"), "volume24": 1}, now=3)
    e.update({**snap(102, "weak-flow"), "buys5": 1, "sells5": 8}, now=3)
    assert e.scan_metrics["rejected_volume"] == 1
    assert e.scan_metrics["rejected_flow"] == 1


def test_strict_safety_default_blocks_entries_without_provider(tmp_path):
    e = PaperEngine(cfg(), tmp_path)
    e.history["p1"] = [[1, 100], [2, 101]]
    e.update(snap(102), now=3)
    assert not e.positions
    assert e.scan_metrics["rejected_safety"] == 1

def test_scan_ranks_best_candidate_before_opening(tmp_path):
    e = make_engine(cfg(), tmp_path)
    first = {**snap(102, "lower-score"), "liquidity": 50000,
             "buy_volume_ratio": 0.60, "execution_impact_pct": 0.8}
    best = {**snap(102, "best-score"), "liquidity": 90000,
            "buy_volume_ratio": 0.75, "execution_impact_pct": 0.1}
    e.history["lower-score"] = [[1, 100], [2, 101]]
    e.history["best-score"] = [[1, 100], [2, 101]]
    e.process_scan([first, best], now=3)
    assert "best-score" in e.positions
    assert e.positions["best-score"].candidate_score >= e.positions["lower-score"].candidate_score

def test_position_persists_hybrid_metadata(tmp_path):
    e = make_engine(cfg(), tmp_path)
    e.history["p1"] = [[1, 100], [2, 101]]
    e.update(snap(102), now=3)
    loaded = make_engine(cfg(), tmp_path)
    assert loaded.positions["p1"].entry_model == "momentum"
    assert loaded.positions["p1"].candidate_score >= 70
    assert loaded.positions["p1"].safety_status == "PASS"
