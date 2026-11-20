"""Paper-only portfolio engine using the single Hybrid Sniper entry strategy."""
import json
import time
from pathlib import Path
from dataclasses import dataclass, asdict

from .safety import evaluate_token_safety
from .strategy import score_candidate, rank_candidates, detect_entry_model

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
    initial_stop: float = 0.0
    last_price: float = 0.0
    entry_model: str = "unknown"
    candidate_score: int = 0
    safety_status: str = "UNKNOWN"

class PaperEngine:
    def __init__(self, cfg, data_dir="data", notifier=None, safety_provider=None):
        self.cfg, self.notifier = cfg, notifier
        self.safety_provider = safety_provider
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.ledger = self.data_dir / "paper_ledger.jsonl"
        self.state_file = self.data_dir / "state.json"
        self.equity = float(cfg["starting_balance_usd"])
        self.positions, self.history = {}, {}
        self.stats = {"closed_trades": 0, "wins": 0, "losses": 0, "realized_pnl": 0.0}
        self.scan_metrics = self.empty_scan_metrics()
        self.market_status = {"provider": "DexScreener REST", "status": "not_started"}
        self.load_state()

    @staticmethod
    def empty_scan_metrics():
        return {
            "discovered": 0, "valid_price": 0, "invalid_price": 0,
            "managed_positions": 0, "qualified_entries": 0,
            "rejected_liquidity": 0, "rejected_volume": 0, "rejected_flow": 0,
            "rejected_pair_age": 0, "waiting_for_price_history": 0,
            "rejected_momentum": 0, "blocked_position_limit": 0,
            "rejected_safety": 0, "rejected_score": 0,
            "rejected_execution": 0, "rejected_setup": 0,
            "rejected_transactions": 0, "ranked_candidates": 0,
        }

    def load_state(self):
        if not self.state_file.exists():
            return
        try:
            state = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.equity = float(state.get("equity", self.equity))
            self.positions = {k: Position(**v) for k, v in state.get("positions", {}).items()}
            self.history = {k: [[float(t), float(p)] for t, p in v]
                            for k, v in state.get("history", {}).items()}
            self.stats.update(state.get("stats", {}))
        except (ValueError, TypeError, KeyError) as exc:
            raise RuntimeError(f"Invalid paper state; refusing silent reset: {exc}") from exc

    def save_state(self):
        state = {"equity": self.equity,
                 "positions": {k: asdict(v) for k, v in self.positions.items()},
                 "history": self.history, "stats": self.stats}
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def log(self, event):
        with self.ledger.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event, allow_nan=False) + "\n")

    def recent_trades(self, limit=30):
        events = []
        if self.ledger.exists():
            with self.ledger.open(encoding="utf-8") as handle:
                for line in handle:
                    try:
                        event = json.loads(line)
                        if event.get("event") == "paper_exit":
                            events.append(event)
                    except (ValueError, TypeError):
                        continue
        return list(reversed(events[-limit:]))

    def notify(self, message):
        if self.notifier:
            try:
                self.notifier.send(message)
            except Exception as exc:
                print(f"[notify] delivery failed: {str(exc)[:200]}")

    @staticmethod
    def momentum(samples):
        if len(samples) < 2 or samples[0][1] <= 0:
            return None
        return (samples[-1][1] / samples[0][1] - 1) * 100

    @staticmethod
    def _safe_float(value, default=0.0):
        try:
            number = float(value)
            return number if number == number and abs(number) != float("inf") else default
        except (TypeError, ValueError, OverflowError):
            return default

    def _market_metrics(self, snap, samples):
        prices = [self._safe_float(item[1]) for item in samples if self._safe_float(item[1]) > 0]
        momentum = self.momentum(samples)
        buys, sells = self._safe_float(snap.get("buys5")), self._safe_float(snap.get("sells5"))
        count = buys + sells
        buy_ratio = snap.get("buy_volume_ratio")
        if buy_ratio is None and count > 0:
            buy_ratio = buys / count
        acceleration = snap.get("volume_acceleration")
        if acceleration is None:
            h1 = self._safe_float(snap.get("volume1h"))
            h24 = self._safe_float(snap.get("volume24"))
            acceleration = h1 / (h24 / 24) if h24 > 0 else 0.0

        breakout = retest = pullback = higher_lows = False
        if len(prices) >= 5:
            prior = prices[:-2]
            recent = prices[-3:]
            prior_high = max(prior)
            breakout = max(recent[:-1]) > prior_high * 1.001
            retest = breakout and prices[-1] >= prior_high * 0.997
            lows = [min(prices[i:i+2]) for i in range(max(0, len(prices)-6), len(prices)-1)]
            higher_lows = len(lows) >= 3 and lows[-1] > lows[0] and all(
                lows[i] >= lows[i-1] for i in range(1, len(lows)))
            pullback = higher_lows and prices[-1] >= prices[-2]

        metrics = {
            "liquidity_usd": self._safe_float(snap.get("liquidity")),
            "volume24_usd": self._safe_float(snap.get("volume24")),
            "buy_volume_ratio": self._safe_float(buy_ratio, -1.0) if buy_ratio is not None else 0.0,
            "volume_acceleration": self._safe_float(acceleration),
            "execution_impact_pct": self._safe_float(snap.get("execution_impact_pct"), 999.0)
                if snap.get("execution_impact_pct") is not None else 999.0,
            "momentum_pct": self._safe_float(momentum, -999.0) if momentum is not None else -999.0,
            "breakout_confirmed": breakout, "retest_held": retest,
            "pullback_reclaim": pullback, "higher_lows": higher_lows,
        }
        model = detect_entry_model(metrics)
        metrics["setup_confirmation"] = 0.9 if model else 0.0
        return metrics

    def _safety(self, snap, now):
        if not callable(self.safety_provider):
            return evaluate_token_safety(None, now=now)
        try:
            evidence = self.safety_provider(snap, now)
        except Exception as exc:
            print(f"[safety] provider failed closed: {str(exc)[:180]}")
            evidence = None
        return evaluate_token_safety(evidence, now=now)

    def _manage_position(self, pair, snap, price, now, samples):
        pos = self.positions[pair]
        self.scan_metrics["managed_positions"] += 1
        pos.last_price = price
        pos.peak = max(pos.peak, price)
        age = now - pos.opened_at
        risk_unit = pos.entry - pos.initial_stop
        r_multiple = (price - pos.entry) / risk_unit if risk_unit > 0 else 0.0
        reason = None
        if price <= pos.stop:
            reason = "stop_loss_or_trailing_stop"
        elif age >= float(self.cfg["max_hold_seconds"]):
            reason = "max_holding_time"
        elif self._safe_float(snap.get("liquidity")) < float(self.cfg["min_liquidity_usd"]) * 0.65:
            reason = "liquidity_deterioration"
        elif r_multiple >= float(self.cfg["target_r"]):
            reason = "target_reached"
        else:
            momentum = self.momentum(samples)
            if r_multiple > 0 and momentum is not None and momentum <= float(self.cfg["early_exit_momentum_pct"]):
                reason = "early_exit_momentum_weakness"
        if reason:
            self.close(pair, price, reason, now)
        elif r_multiple >= float(self.cfg["trail_after_r"]):
            trail = pos.peak * (1 - float(self.cfg["trailing_drawdown_pct"]) / 100)
            pos.stop = max(pos.stop, trail)

    def process_scan(self, snapshots, now=None):
        """Update open positions, rank all fresh candidates, then fill best-first."""
        now = time.time() if now is None else float(now)
        candidates = []
        for snap in snapshots:
            self.scan_metrics["discovered"] += 1
            pair = snap.get("pair")
            price = self._safe_float(snap.get("price"))
            if not pair or price <= 0:
                self.scan_metrics["invalid_price"] += 1
                continue
            self.scan_metrics["valid_price"] += 1
            samples = self.history.setdefault(pair, [])
            samples.append([now, price])
            samples[:] = [[t, p] for t, p in samples if now - float(t) <= 90]
            if pair in self.positions:
                self._manage_position(pair, snap, price, now, samples)
                continue
            if len(self.positions) >= int(self.cfg["max_positions"]):
                self.scan_metrics["blocked_position_limit"] += 1
                continue
            liquidity = self._safe_float(snap.get("liquidity"))
            volume = self._safe_float(snap.get("volume24"))
            if liquidity < float(self.cfg.get("min_liquidity_usd", 15000)):
                self.scan_metrics["rejected_liquidity"] += 1
                continue
            if volume < float(self.cfg.get("min_volume_24h_usd", 30000)):
                self.scan_metrics["rejected_volume"] += 1
                continue
            buys = self._safe_float(snap.get("buys5"))
            sells = self._safe_float(snap.get("sells5"))
            tx_count = buys + sells
            if tx_count < int(self.cfg.get("min_transactions_5m", 4)):
                self.scan_metrics["rejected_transactions"] += 1
                continue
            if buys <= sells:
                self.scan_metrics["rejected_flow"] += 1
                continue
            created = self._safe_float(snap.get("created_ms"))
            age_min = (now * 1000 - created) / 60000 if created > 0 else 0
            if age_min < float(self.cfg.get("min_pair_age_minutes", 15)):
                self.scan_metrics["rejected_pair_age"] += 1
                continue
            if len(samples) < 2:
                self.scan_metrics["waiting_for_price_history"] += 1
                continue
            safety = self._safety(snap, now)
            if not safety.passed:
                self.scan_metrics["rejected_safety"] += 1
            metrics = self._market_metrics(snap, samples)
            decision = score_candidate(metrics, safety_passed=safety.passed,
                minimum_score=int(self.cfg.get("minimum_candidate_score", 70)),
                execution_impact_limit_pct=float(self.cfg.get("execution_impact_limit_pct", 1.0)))
            if not decision.eligible:
                if ("estimated_price_impact_too_high" in decision.reasons
                    or "execution_impact_unavailable" in decision.reasons):
                    self.scan_metrics["rejected_execution"] += 1
                elif "no_hybrid_setup_confirmed" in decision.reasons:
                    self.scan_metrics["rejected_setup"] += 1
                elif "candidate_score_below_threshold" in decision.reasons:
                    self.scan_metrics["rejected_score"] += 1
                elif safety.passed:
                    self.scan_metrics["rejected_score"] += 1
                continue
            candidates.append({"snapshot": snap, "metrics": metrics,
                "decision": decision.to_dict(), "liquidity_usd": liquidity,
                "safety": safety.to_dict()})

        self.scan_metrics["ranked_candidates"] = len(candidates)
        for candidate in rank_candidates(candidates):
            if len(self.positions) >= int(self.cfg["max_positions"]):
                self.scan_metrics["blocked_position_limit"] += 1
                break
            self._open_position(candidate, now)
        # Bound dormant history to the current discovery universe.
        max_history = max(80, int(self.cfg.get("max_tokens_to_track", 80)) * 2)
        if len(self.history) > max_history:
            ordered = sorted(self.history.items(),
                key=lambda item: item[1][-1][0] if item[1] else 0, reverse=True)
            self.history = dict(ordered[:max_history])
        self.save_state()

    def update(self, snap, now=None):
        self.process_scan([snap], now=now)

    def _open_position(self, candidate, now):
        snap, metrics, decision = candidate["snapshot"], candidate["metrics"], candidate["decision"]
        pair, price = snap["pair"], self._safe_float(snap["price"])
        stop = price * (1 - float(self.cfg["stop_pct"]) / 100)
        budget = max(0.0, self.equity * float(self.cfg["risk_per_trade"]))
        cost_rate = float(self.cfg["estimated_round_trip_cost_pct"]) / 100
        cost_unit = (price + stop) * cost_rate / 2
        risk_unit = (price - stop) + cost_unit
        if budget <= 0 or risk_unit <= 0:
            return
        quantity = budget / risk_unit
        target = price + float(self.cfg["target_r"]) * (price - stop)
        pos = Position(pair, snap.get("token", "UNKNOWN"), snap.get("address", ""),
            price, quantity, stop, target, budget, now, price,
            snap.get("url", ""), stop, price, decision["model"],
            int(decision["score"]), candidate["safety"]["status"])
        self.positions[pair] = pos
        self.scan_metrics["qualified_entries"] += 1
        self.log({"event":"paper_entry","time":now,"token":pos.token,"address":pos.address,
            "pair":pair,"entry":price,"stop":stop,"target":target,"risk_budget":budget,
            "quantity":quantity,"entry_model":pos.entry_model,"candidate_score":pos.candidate_score,
            "safety":candidate["safety"],"signals":decision["signals"],"url":pos.url})
        contract = f"https://solscan.io/token/{pos.address}" if pos.address else "Unavailable"
        self.notify(f"🟢 JABIZ FLASH — PAPER ENTRY\nToken: {pos.token}\nModel: {pos.entry_model} | Score: {pos.candidate_score}/100\n"
            f"Safety: {pos.safety_status}\nEntry: ${price:.8g}\nStop: ${stop:.8g}\n"
            f"Target: ${target:.8g} ({self.cfg['target_r']:.2f}R)\nRisk budget: ${budget:.2f} | Size: {quantity:.6g}\n"
            f"Contract: {contract}\nPair: {pos.url or 'Unavailable'}\nMode: SIMULATED — no real order placed")

    def close(self, pair, price, reason, now):
        pos = self.positions.pop(pair)
        gross = (price - pos.entry) * pos.quantity
        rate = float(self.cfg["estimated_round_trip_cost_pct"]) / 100
        costs = (pos.entry + price) * pos.quantity * rate / 2
        net = gross - costs
        self.equity += net
        self.stats["closed_trades"] += 1
        self.stats["wins" if net > 0 else "losses"] += 1
        self.stats["realized_pnl"] += net
        held = max(0, int(now - pos.opened_at))
        r_multiple = net / pos.risk_usd if pos.risk_usd > 0 else 0.0
        self.log({"event":"paper_exit","time":now,"token":pos.token,"address":pos.address,
            "pair":pair,"entry":pos.entry,"exit":price,"stop":pos.stop,"target":pos.target,
            "risk_budget":pos.risk_usd,"quantity":pos.quantity,"gross_pnl":gross,
            "estimated_costs":costs,"net_pnl":net,"equity":self.equity,"reason":reason,
            "holding_seconds":held,"entry_model":pos.entry_model,
            "candidate_score":pos.candidate_score,"url":pos.url})
        contract = f"https://solscan.io/token/{pos.address}" if pos.address else "Unavailable"
        self.notify(f"🔴 JABIZ FLASH — PAPER EXIT\nToken: {pos.token}\nModel: {pos.entry_model}\n"
            f"Entry: ${pos.entry:.8g} | Exit: ${price:.8g}\nNet P&L: ${net:+.2f} ({r_multiple:+.2f}R)\n"
            f"Estimated costs: ${costs:.2f}\nHeld: {held}s | Reason: {reason}\n"
            f"Equity: ${self.equity:.2f}\nContract: {contract}\nMode: SIMULATED — no real order placed")

    def dashboard_status(self):
        now = time.time()
        cost_rate = float(self.cfg["estimated_round_trip_cost_pct"]) / 100
        open_positions = []
        for pos in self.positions.values():
            current = pos.last_price or pos.entry
            gross = (current - pos.entry) * pos.quantity
            costs = (pos.entry + current) * pos.quantity * cost_rate / 2
            open_positions.append({**asdict(pos), "held_seconds":max(0,int(now-pos.opened_at)),
                "current_price":current,"unrealized_pnl":gross-costs,
                "contract_url":f"https://solscan.io/token/{pos.address}" if pos.address else "",
                "dex_url":pos.url})
        return {"updated_at":now,"mode":"PAPER ONLY","strategy":"HYBRID SNIPER",
            "strategy_models":["momentum","breakout_retest","pullback_continuation"],
            "safety_policy":"STRICT_FAIL_CLOSED","candidate_selection":"BEST_FIRST",
            "entry_confirmation":"FAST","equity":round(self.equity,4),
            "starting_balance":self.cfg["starting_balance_usd"],"open_positions":open_positions,
            "recent_trades":self.recent_trades(),"stats":self.stats,
            "risk_per_trade":self.cfg["risk_per_trade"],"max_positions":self.cfg["max_positions"],
            "max_hold_seconds":self.cfg["max_hold_seconds"],
            "strategy_config":{"minimum_score":self.cfg.get("minimum_candidate_score",70),
                "min_liquidity_usd":self.cfg.get("min_liquidity_usd",15000),
                "min_volume_24h_usd":self.cfg.get("min_volume_24h_usd",30000),
                "max_execution_impact_pct":self.cfg.get("execution_impact_limit_pct",1.0),
                "max_top10_holder_pct":35,"safety_evidence_max_age_seconds":300},
            "scanner":{"metrics":dict(self.scan_metrics),"api":dict(self.market_status)}}
