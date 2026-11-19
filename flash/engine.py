import json, time
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass
class Position:
    pair:str; token:str; address:str; entry:float; quantity:float; stop:float
    target:float; risk_usd:float; opened_at:float; peak:float
    url:str=""; initial_stop:float=0.0; last_price:float=0.0

class PaperEngine:
    def __init__(self,cfg,data_dir="data",notifier=None):
        self.cfg,self.notifier=cfg,notifier
        self.data_dir=Path(data_dir); self.data_dir.mkdir(parents=True,exist_ok=True)
        self.ledger=self.data_dir/"paper_ledger.jsonl"; self.state_file=self.data_dir/"state.json"
        self.equity=float(cfg["starting_balance_usd"]); self.positions={}; self.history={}
        self.stats={"closed_trades":0,"wins":0,"losses":0,"realized_pnl":0.0}
        self.scan_metrics = self.empty_scan_metrics()
        self.market_status = {"provider": "DexScreener REST", "status": "not_started"}
        self.load_state()
    @staticmethod
    def empty_scan_metrics():
        return {
            "discovered": 0, "valid_price": 0, "invalid_price": 0,
            "managed_positions": 0, "qualified_entries": 0,
            "rejected_liquidity": 0, "rejected_volume": 0,
            "rejected_flow": 0, "rejected_pair_age": 0,
            "waiting_for_price_history": 0, "rejected_momentum": 0,
            "blocked_position_limit": 0,
        }
    def load_state(self):
        if not self.state_file.exists(): return
        try:
            s=json.loads(self.state_file.read_text(encoding="utf-8"))
            self.equity=float(s.get("equity",self.equity))
            self.positions={k:Position(**v) for k,v in s.get("positions",{}).items()}
            self.history={k:[[float(t),float(p)] for t,p in v] for k,v in s.get("history",{}).items()}
            self.stats.update(s.get("stats",{}))
        except (ValueError,TypeError,KeyError) as exc:
            raise RuntimeError(f"Invalid paper state; refusing silent reset: {exc}") from exc
    def save_state(self):
        s={"equity":self.equity,"positions":{k:asdict(v) for k,v in self.positions.items()},
           "history":self.history,"stats":self.stats}
        tmp=self.state_file.with_suffix(".tmp"); tmp.write_text(json.dumps(s,indent=2)); tmp.replace(self.state_file)
    def log(self,event):
        with self.ledger.open("a",encoding="utf-8") as f: f.write(json.dumps(event)+"\n")
    def recent_trades(self,limit=30):
        events=[]
        if self.ledger.exists():
            try:
                with self.ledger.open(encoding="utf-8") as f:
                    for line in f:
                        try:
                            event=json.loads(line)
                            if event.get("event")=="paper_exit": events.append(event)
                        except (ValueError,TypeError):
                            continue
            except OSError:
                pass
        return list(reversed(events[-limit:]))
    def notify(self,msg):
        if self.notifier: self.notifier.send(msg)
    @staticmethod
    def momentum(samples):
        if len(samples)<2 or samples[0][1]<=0: return None
        return (samples[-1][1]/samples[0][1]-1)*100
    def update(self,snap,now=None):
        now=time.time() if now is None else now
        pair=snap.get("pair"); price=float(snap.get("price") or 0)
        self.scan_metrics["discovered"] += 1
        if not pair or price<=0:
            self.scan_metrics["invalid_price"] += 1
            return
        self.scan_metrics["valid_price"] += 1
        samples=self.history.setdefault(pair,[]); samples.append([now,price])
        samples[:]=[[t,p] for t,p in samples if now-float(t)<=90]
        pos=self.positions.get(pair)
        if pos:
            self.scan_metrics["managed_positions"] += 1
            pos.last_price=price
            pos.peak=max(pos.peak,price); age=now-pos.opened_at
            r=(price-pos.entry)/(pos.entry-pos.initial_stop) if pos.entry>pos.initial_stop else 0
            mom=self.momentum(samples); reason=None
            if price<=pos.stop: reason="stop_loss_or_trailing_stop"
            elif age>=self.cfg["max_hold_seconds"]: reason="max_holding_time"
            elif float(snap.get("liquidity") or 0)<self.cfg["min_liquidity_usd"]*0.65: reason="liquidity_deterioration"
            elif r>=self.cfg["target_r"]: reason="target_reached"
            elif r>0 and mom is not None and mom<=self.cfg["early_exit_momentum_pct"]: reason="early_exit_momentum_weakness"
            if reason: self.close(pair,price,reason,now)
            elif r>=self.cfg["trail_after_r"]:
                pos.stop=max(pos.stop,pos.peak*(1-self.cfg["trailing_drawdown_pct"]/100))
            return
        if len(self.positions)>=self.cfg["max_positions"]:
            self.scan_metrics["blocked_position_limit"] += 1
            return
        if snap.get("liquidity",0)<self.cfg["min_liquidity_usd"]:
            self.scan_metrics["rejected_liquidity"] += 1
            return
        if snap.get("volume24",0)<self.cfg["min_volume_24h_usd"]:
            self.scan_metrics["rejected_volume"] += 1
            return
        if snap.get("buys5",0)<=snap.get("sells5",0) or snap.get("buys5",0)+snap.get("sells5",0)<4:
            self.scan_metrics["rejected_flow"] += 1
            return
        created=snap.get("created_ms",0); age_min=(now*1000-created)/60000 if created else 10**9
        if age_min<self.cfg["min_pair_age_minutes"]:
            self.scan_metrics["rejected_pair_age"] += 1
            return
        mom=self.momentum(samples)
        if mom is None:
            self.scan_metrics["waiting_for_price_history"] += 1
            return
        if mom<self.cfg["entry_momentum_pct"]:
            self.scan_metrics["rejected_momentum"] += 1
            return
        stop=price*(1-self.cfg["stop_pct"]/100); budget=self.equity*self.cfg["risk_per_trade"]
        cost_rate=self.cfg["estimated_round_trip_cost_pct"]/100
        cost_unit=(price+stop)*cost_rate/2
        risk_unit=(price-stop)+cost_unit
        if budget<=0 or risk_unit<=0: return
        qty=budget/risk_unit; target=price+self.cfg["target_r"]*(price-stop)
        pos=Position(pair,snap.get("token","UNKNOWN"),snap.get("address",""),price,qty,stop,target,
                     budget,now,price,snap.get("url",""),stop,price)
        self.positions[pair]=pos
        self.scan_metrics["qualified_entries"] += 1
        self.log({"event":"paper_entry","time":now,"token":pos.token,"address":pos.address,"pair":pair,"entry":price,
          "stop":stop,"target":target,"risk_budget":budget,"quantity":qty,"momentum_pct":mom,"url":pos.url})
        contract=f"https://solscan.io/token/{pos.address}" if pos.address else "Unavailable"
        dex=pos.url or "Unavailable"
        self.notify(
            f"🟢 JABIZ FLASH — PAPER ENTRY\n"
            f"Token: {pos.token}\n"
            f"Entry: ${price:.8g}\nStop: ${stop:.8g}\n"
            f"Target: ${target:.8g} ({self.cfg['target_r']:.2f}R)\n"
            f"Risk budget: ${budget:.2f} | Size: {qty:.6g}\n"
            f"Contract: {contract}\nPair: {dex}\n"
            f"Mode: SIMULATED — no real order placed"
        )
    def close(self,pair,price,reason,now):
        pos=self.positions.pop(pair); gross=(price-pos.entry)*pos.quantity
        rate=self.cfg["estimated_round_trip_cost_pct"]/100
        costs=(pos.entry+price)*pos.quantity*rate/2; net=gross-costs
        self.equity+=net; self.stats["closed_trades"]+=1
        self.stats["wins" if net>0 else "losses"]+=1; self.stats["realized_pnl"]+=net
        self.log({"event":"paper_exit","time":now,"token":pos.token,"address":pos.address,"pair":pair,"entry":pos.entry,
          "exit":price,"stop":pos.stop,"target":pos.target,"risk_budget":pos.risk_usd,"quantity":pos.quantity,
          "gross_pnl":gross,"estimated_costs":costs,"net_pnl":net,"equity":self.equity,
          "reason":reason,"holding_seconds":now-pos.opened_at,"url":pos.url})
        held=max(0,int(now-pos.opened_at))
        r_multiple=net/pos.risk_usd if pos.risk_usd>0 else 0.0
        contract=f"https://solscan.io/token/{pos.address}" if pos.address else "Unavailable"
        self.notify(
            f"🔴 JABIZ FLASH — PAPER EXIT\n"
            f"Token: {pos.token}\n"
            f"Entry: ${pos.entry:.8g} | Exit: ${price:.8g}\n"
            f"Net P&L: ${net:+.2f} ({r_multiple:+.2f}R)\n"
            f"Estimated costs: ${costs:.2f}\n"
            f"Held: {held}s | Reason: {reason}\n"
            f"Equity: ${self.equity:.2f}\n"
            f"Contract: {contract}\n"
            f"Mode: SIMULATED — no real order placed"
        )
        self.save_state()
    def dashboard_status(self):
        now=time.time(); cost_rate=self.cfg["estimated_round_trip_cost_pct"]/100
        open_positions=[]
        for p in self.positions.values():
            current=p.last_price or p.entry
            gross=(current-p.entry)*p.quantity
            estimated_costs=(p.entry+current)*p.quantity*cost_rate/2
            open_positions.append({**asdict(p),"held_seconds":max(0,int(now-p.opened_at)),
                "current_price":current,"unrealized_pnl":gross-estimated_costs,
                "contract_url":f"https://solscan.io/token/{p.address}" if p.address else "",
                "dex_url":p.url})
        return {"updated_at":now,"mode":"PAPER ONLY","equity":round(self.equity,4),
          "starting_balance":self.cfg["starting_balance_usd"],"open_positions":open_positions,
          "recent_trades":self.recent_trades(),"stats":self.stats,"risk_per_trade":self.cfg["risk_per_trade"],
          "max_positions":self.cfg["max_positions"],"max_hold_seconds":self.cfg["max_hold_seconds"],
          "scanner": {"metrics": self.scan_metrics, "api": self.market_status}}
