import json, math, time
from pathlib import Path
from dataclasses import dataclass, asdict

@dataclass
class Position:
    pair: str
    token: str
    address: str
    entry: float
    quantity: float
    stop: float
    target: float
    risk_usd: float
    opened_at: float
    peak: float
    url: str = ""

class PaperEngine:
    def __init__(self, cfg, data_dir="data"):
        self.cfg = cfg
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = self.data_dir / "paper_ledger.jsonl"
        self.state_file = self.data_dir / "state.json"
        self.equity = float(cfg["starting_balance_usd"])
        self.positions = {}
        self.history = {}
        self.load_state()

    def load_state(self):
        if self.state_file.exists():
            try:
                state = json.loads(self.state_file.read_text())
                self.equity = float(state.get("equity", self.equity))
                self.positions = {k: Position(**v) for k, v in state.get("positions", {}).items()}
            except Exception as exc:
                print(f"[state] Could not load state; starting fresh: {exc}")

    def save_state(self):
        state = {"equity": self.equity, "positions": {k: asdict(v) for k, v in self.positions.items()}}
        self.state_file.write_text(json.dumps(state, indent=2))

    def log(self, event):
        with self.ledger.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event) + "\n")

    def update(self, snap, now=None):
        now = now or time.time()
        pair, price = snap["pair"], snap["price"]
        if not pair or price <= 0:
            return
        samples = self.history.setdefault(pair, [])
        samples.append((now, price))
        samples[:] = [(t,p) for t,p in samples if now-t <= 90]
        pos = self.positions.get(pair)
        if pos:
            pos.peak = max(pos.peak, price)
            age = now - pos.opened_at
            ret = (price / pos.entry - 1) * 100
            momentum = self._momentum(samples)
            reason = None
            if price <= pos.stop: reason = "stop_loss"
            elif age >= self.cfg["max_hold_seconds"]: reason = "max_holding_time"
            elif snap["liquidity"] < self.cfg["min_liquidity_usd"] * 0.65: reason = "liquidity_deterioration"
            elif ret >= self.cfg["target_r"] * (pos.entry-pos.stop)/pos.entry*100: reason = "target_reached"
            elif ret > 0 and momentum <= self.cfg["early_exit_momentum_pct"]: reason = "early_exit_momentum_weakness"
            if reason:
                self.close(pair, price, reason, now)
            return
        if len(self.positions) >= self.cfg["max_positions"] or pair in self.positions:
            return
        if snap["liquidity"] < self.cfg["min_liquidity_usd"] or snap["volume24"] < self.cfg["min_volume_24h_usd"]:
            return
        if snap["buys5"] <= snap["sells5"] or (snap["buys5"] + snap["sells5"]) < 4:
            return
        age_minutes = (now*1000 - snap["created_ms"])/60000 if snap["created_ms"] else 999999
        if age_minutes < self.cfg["min_pair_age_minutes"]:
            return
        momentum = self._momentum(samples)
        if momentum is None or momentum < self.cfg["entry_momentum_pct"]:
            return
        stop = price * (1 - self.cfg["stop_pct"]/100)
        risk_usd = self.equity * self.cfg["risk_per_trade"]
        cost_rate = self.cfg["estimated_round_trip_cost_pct"]/100
        effective_risk = risk_usd - (self.equity * cost_rate * 0.01)
        if effective_risk <= 0:
            return
        quantity = effective_risk / (price-stop)
        target = price + 2*(price-stop)
        pos = Position(pair, snap["token"], snap["address"], price, quantity, stop, target,
                       risk_usd, now, price, snap["url"])
        self.positions[pair] = pos
        self.log({"event":"paper_entry","time":now,"token":pos.token,"pair":pair,
                  "entry":price,"stop":stop,"target":target,"risk_usd":risk_usd,
                  "quantity":quantity,"momentum_pct":momentum,"url":pos.url})
        print(f"[ENTRY] {pos.token} @ ${price:.8g} | risk ${risk_usd:.2f} | SL ${stop:.8g} | TP ${target:.8g}")

    def close(self, pair, price, reason, now):
        pos = self.positions.pop(pair)
        gross = (price-pos.entry)*pos.quantity
        costs = (pos.entry+price)*pos.quantity*(self.cfg["estimated_round_trip_cost_pct"]/100/2)
        net = gross-costs
        self.equity += net
        self.log({"event":"paper_exit","time":now,"token":pos.token,"pair":pair,
                  "entry":pos.entry,"exit":price,"gross_pnl":gross,"estimated_costs":costs,
                  "net_pnl":net,"equity":self.equity,"reason":reason,
                  "holding_seconds":now-pos.opened_at,"url":pos.url})
        print(f"[EXIT] {pos.token} @ ${price:.8g} | net ${net:+.2f} | {reason} | equity ${self.equity:.2f}")
        self.save_state()

    @staticmethod
    def _momentum(samples):
        if len(samples) < 2:
            return None
        old, new = samples[0][1], samples[-1][1]
        return (new/old-1)*100 if old else None
