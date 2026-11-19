import time
from scripts import validation

def test_init_is_idempotent(tmp_path, monkeypatch):
    path=tmp_path/"validation.json"
    monkeypatch.setattr(validation,"DATA",tmp_path)
    monkeypatch.setattr(validation,"META",path)
    first=validation.init(); second=validation.init()
    assert first["started_at"]==second["started_at"]
    assert second["duration_days"]==14 and second["mode"]=="PAPER ONLY"

def test_trade_summary_metrics():
    now=time.time()
    rows=[
      {"event":"paper_exit","time":now-20,"net_pnl":2,"risk_budget":1,"holding_seconds":10,"reason":"target_reached"},
      {"event":"paper_exit","time":now-10,"net_pnl":-1,"risk_budget":1,"holding_seconds":20,"reason":"stop_loss_or_trailing_stop"},
      {"event":"paper_session","time":now-5,"scan_metrics":{"discovered":20,"qualified_entries":2}}]
    result=validation.summary(rows,now-100,100)
    assert result["closed_trades"]==2 and result["win_rate_pct"]==50
    assert result["net_pnl_usd"]==1 and result["profit_factor"]==2
    assert result["average_r"]==0.5 and result["scan_metrics"]["discovered"]==20
