import json, time
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass
class Position:
    pair:str; token:str; address:str; entry:float; quantity:float; stop:float
    target:float; risk_usd:float; opened_at:float; peak:float
    url:str=""; initial_stop:float=0.0

class PaperEngine:
    def __init__(self,cfg,data_dir="data",notifier=None):
        self.cfg,self.notifier=cfg,notifier
        self.data_dir=Path(data_dir); self.data_dir.mkdir(parents=True,exist_ok=True)
        self.ledger=self.data_dir/"paper_ledger.jsonl"; self.state_file=self.data_dir/"state.json"
        self.equity=float(cfg["starting_balance_usd"]); self.positions={}; self.history={}
        self.stats={"closed_trades":0,"wins":0,"losses":0,"realized_pnl":0.0}
        self.load_state()
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
    def notify(self,msg):
        if self.notifier: self.notifier.send(msg)
    @staticmethod
    def momentum(samples):
        if len(samples)<2 or samples[0][1]<=0: return None
        return (samples[-1][1]/samples[0][1]-1)*100
    def update(self,snap,now=None):
        now=time.time() if now is None else now
        pair=snap.get("pair"); price=float(snap.get("price") or 0)
        if not pair or price<=0: return
        samples=self.history.setdefault(pair,[]); samples.append([now,price])
        samples[:]=[[t,p] for t,p in samples if now-float(t)<=90]
        pos=self.positions.get(pair)
        if pos:
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
        if len(self.positions)>=self.cfg["max_positions"]: return
        if snap.get("liquidity",0)<self.cfg["min_liquidity_usd"] or snap.get("volume24",0)<self.cfg["min_volume_24h_usd"]: return
        if snap.get("buys5",0)<=snap.get("sells5",0) or snap.get("buys5",0)+snap.get("sells5",0)<4: return
        created=snap.get("created_ms",0); age_min=(now*1000-created)/60000 if created else 10**9
        if age_min<self.cfg["min_pair_age_minutes"]: return
        mom=self.momentum(samples)
        if mom is None or mom<self.cfg["entry_momentum_pct"]: return
        stop=price*(1-self.cfg["stop_pct"]/100); budget=self.equity*self.cfg["risk_per_trade"]
        cost_rate=self.cfg["estimated_round_trip_cost_pct"]/100
        cost_unit=(price+stop)*cost_rate/2
        risk_unit=(price-stop)+cost_unit
        if budget<=0 or risk_unit<=0: return
        qty=budget/risk_unit; target=price+self.cfg["target_r"]*(price-stop)
        pos=Position(pair,snap.get("token","UNKNOWN"),snap.get("address",""),price,qty,stop,target,
                     budget,now,price,snap.get("url",""),stop)
        self.positions[pair]=pos
        self.log({"event":"paper_entry","time":now,"token":pos.token,"pair":pair,"entry":price,
          "stop":stop,"target":target,"risk_budget":budget,"quantity":qty,"momentum_pct":mom,"url":pos.url})
        self.notify(f"🟢 JABIZ FLASH PAPER ENTRY\n{pos.token}\nEntry ${price:.8g}\nSL ${stop:.8g}\nTP ${target:.8g}\nRisk ${budget:.2f}")
    def close(self,pair,price,reason,now):
        pos=self.positions.pop(pair); gross=(price-pos.entry)*pos.quantity
        rate=self.cfg["estimated_round_trip_cost_pct"]/100
        costs=(pos.entry+price)*pos.quantity*rate/2; net=gross-costs
        self.equity+=net; self.stats["closed_trades"]+=1
        self.stats["wins" if net>0 else "losses"]+=1; self.stats["realized_pnl"]+=net
        self.log({"event":"paper_exit","time":now,"token":pos.token,"pair":pair,"entry":pos.entry,
          "exit":price,"gross_pnl":gross,"estimated_costs":costs,"net_pnl":net,"equity":self.equity,
          "reason":reason,"holding_seconds":now-pos.opened_at,"url":pos.url})
        self.notify(f"🔴 JABIZ FLASH PAPER EXIT\n{pos.token}\nExit ${price:.8g}\nNet ${net:+.2f}\n{reason}\nEquity ${self.equity:.2f}")
        self.save_state()
    def dashboard_status(self):
        return {"updated_at":time.time(),"mode":"PAPER ONLY","equity":round(self.equity,4),
          "starting_balance":self.cfg["starting_balance_usd"],"open_positions":[asdict(p) for p in self.positions.values()],
          "stats":self.stats,"risk_per_trade":self.cfg["risk_per_trade"],
          "max_positions":self.cfg["max_positions"],"max_hold_seconds":self.cfg["max_hold_seconds"]}
