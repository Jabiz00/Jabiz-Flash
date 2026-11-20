"""Hybrid Sniper candidate scoring. Pure deterministic, paper-only decision logic."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from math import isfinite
from typing import Any, Mapping

@dataclass(frozen=True)
class CandidateDecision:
    eligible: bool
    score: int
    model: str | None
    reasons: tuple[str, ...]
    signals: tuple[str, ...]
    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reasons"] = list(self.reasons)
        data["signals"] = list(self.signals)
        return data

def _number(metrics: Mapping[str, Any], key: str, default: float = 0.0) -> float:
    try:
        value = float(metrics.get(key, default))
        return value if isfinite(value) else default
    except (TypeError, ValueError, OverflowError):
        return default

def detect_entry_model(metrics: Mapping[str, Any]) -> str | None:
    if metrics.get("breakout_confirmed") is True and metrics.get("retest_held") is True:
        return "breakout_retest"
    if metrics.get("pullback_reclaim") is True and metrics.get("higher_lows") is True:
        return "pullback_continuation"
    if (_number(metrics, "momentum_pct") >= 0.35
        and _number(metrics, "buy_pressure_ratio") > 0.55
        and _number(metrics, "volume_velocity_ratio") >= 1.2):
        return "momentum"
    return None

def score_candidate(metrics: Mapping[str, Any], *, safety_passed: bool,
                    minimum_score: int = 70,
                    execution_impact_limit_pct: float = 1.0) -> CandidateDecision:
    if not safety_passed:
        return CandidateDecision(False, 0, None, ("safety_gate_failed",), ())
    reasons: list[str] = []
    signals: list[str] = []
    liquidity = max(0.0, _number(metrics, "liquidity_usd"))
    volume = max(0.0, _number(metrics, "volume24_usd"))
    buy_ratio = min(1.0, max(0.0, _number(metrics, "buy_pressure_ratio")))
    acceleration = max(0.0, _number(metrics, "volume_velocity_ratio"))
    setup = min(1.0, max(0.0, _number(metrics, "setup_confirmation")))
    raw_impact = metrics.get("execution_impact_pct")
    impact = _number(metrics, "execution_impact_pct", 999.0)
    try:
        impact_available = raw_impact is not None and isfinite(float(raw_impact))
    except (TypeError, ValueError, OverflowError):
        impact_available = False
    impact_limit = max(0.01, _number({"v": execution_impact_limit_pct}, "v", 1.0))

    market_points = min(12.5, liquidity / 15000 * 12.5) + min(12.5, volume / 30000 * 12.5)
    flow_points = min(15.0, max(0.0, (buy_ratio - 0.5) * 60)) + min(10.0, acceleration * 5)
    execution_points = max(0.0, 20.0 * (1 - impact / impact_limit))
    score = round(market_points + flow_points + setup * 30 + execution_points)

    if liquidity < 15000: reasons.append("liquidity_below_experimental_floor")
    if volume < 30000: reasons.append("volume_below_experimental_floor")
    if not impact_available: reasons.append("execution_impact_unavailable")
    elif impact < 0 or impact > impact_limit: reasons.append("estimated_price_impact_too_high")
    model = detect_entry_model(metrics)
    if model: signals.append("setup:" + model)
    if buy_ratio > 0.55: signals.append("buy_pressure_leads")
    if acceleration >= 1.2: signals.append("volume_velocity_confirmed")
    if _number(metrics, "momentum_pct") >= 0.35: signals.append("momentum_confirmed")
    if metrics.get("higher_lows") is True: signals.append("higher_lows")
    independent = [s for s in signals if not s.startswith("setup:")]
    eligible = (model is not None and bool(independent) and liquidity >= 15000
                and volume >= 30000 and 0 <= impact <= impact_limit and score >= minimum_score)
    if not model: reasons.append("no_hybrid_setup_confirmed")
    if not independent: reasons.append("no_independent_confirmation_signal")
    if score < minimum_score: reasons.append("candidate_score_below_threshold")
    return CandidateDecision(eligible, score, model, tuple(dict.fromkeys(reasons)), tuple(signals))

def rank_candidates(candidates: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    eligible = [c for c in candidates if c.get("decision", {}).get("eligible") is True]
    return sorted(eligible, key=lambda c: (
        _number(c.get("decision", {}), "score"),
        _number(c, "liquidity_usd")), reverse=True)
