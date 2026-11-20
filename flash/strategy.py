"""Hybrid sniper candidate scoring and fast-confirmation rules.

Pure deterministic logic. Market observations and safety evidence are supplied
by adapters; this module never places orders and is paper-strategy only.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
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


def score_candidate(
    metrics: Mapping[str, Any],
    *,
    safety_passed: bool,
    minimum_score: int = 70,
    execution_impact_limit_pct: float = 1.0,
) -> CandidateDecision:
    """Score market/execution quality; safety is an unconditional hard gate.

    Expected normalized metrics include liquidity_usd, volume24_usd,
    buy_volume_ratio (0..1), volume_acceleration, setup_confirmation (0..1),
    execution_impact_pct, momentum_pct, breakout_confirmed, retest_held,
    pullback_reclaim, higher_lows.
    """
    reasons: list[str] = []
    signals: list[str] = []
    if not safety_passed:
        return CandidateDecision(False, 0, None, ("safety_gate_failed",), ())

    liquidity = max(0.0, float(metrics.get("liquidity_usd") or 0))
    volume = max(0.0, float(metrics.get("volume24_usd") or 0))
    buy_ratio = min(1.0, max(0.0, float(metrics.get("buy_volume_ratio") or 0)))
    acceleration = max(0.0, float(metrics.get("volume_acceleration") or 0))
    setup = min(1.0, max(0.0, float(metrics.get("setup_confirmation") or 0)))
    impact = max(0.0, float(metrics.get("execution_impact_pct") or 999))

    # Market quality: 25 points.
    market_points = min(12.5, liquidity / 15000 * 12.5)
    market_points += min(12.5, volume / 30000 * 12.5)
    # Flow/volume: 25 points.
    flow_points = min(15.0, max(0.0, (buy_ratio - 0.5) * 60))
    flow_points += min(10.0, acceleration * 5)
    # Setup confirmation: 30 points.
    setup_points = setup * 30
    # Execution: 20 points, sharply penalize excessive impact.
    execution_points = max(0.0, 20.0 * (1 - impact / execution_impact_limit_pct))
    score = round(market_points + flow_points + setup_points + execution_points)

    if liquidity < 15000:
        reasons.append("liquidity_below_experimental_floor")
    if volume < 30000:
        reasons.append("volume_below_experimental_floor")
    if impact > execution_impact_limit_pct:
        reasons.append("estimated_price_impact_too_high")

    model = detect_entry_model(metrics)
    if model:
        signals.append("setup:" + model)
    if buy_ratio > 0.55:
        signals.append("buy_volume_leads")
    if acceleration >= 1.2:
        signals.append("volume_accelerating")
    if float(metrics.get("momentum_pct") or 0) >= 0.35:
        signals.append("momentum_confirmed")
    if metrics.get("higher_lows") is True:
        signals.append("higher_lows")

    # Fast mode: setup-specific confirmation plus at least one independent
    # market signal. Hard market/execution floors remain mandatory.
    independent = [s for s in signals if not s.startswith("setup:")]
    eligible = (
        model is not None
        and len(independent) >= 1
        and liquidity >= 15000
        and volume >= 30000
        and impact <= execution_impact_limit_pct
        and score >= minimum_score
    )
    if not model:
        reasons.append("no_hybrid_setup_confirmed")
    if not independent:
        reasons.append("no_independent_confirmation_signal")
    if score < minimum_score:
        reasons.append("candidate_score_below_threshold")
    return CandidateDecision(eligible, score, model, tuple(reasons), tuple(signals))


def detect_entry_model(metrics: Mapping[str, Any]) -> str | None:
    """Return the strongest confirmed model in deterministic priority order."""
    if metrics.get("breakout_confirmed") is True and metrics.get("retest_held") is True:
        return "breakout_retest"
    if metrics.get("pullback_reclaim") is True and metrics.get("higher_lows") is True:
        return "pullback_continuation"
    momentum = float(metrics.get("momentum_pct") or 0)
    buy_ratio = float(metrics.get("buy_volume_ratio") or 0)
    acceleration = float(metrics.get("volume_acceleration") or 0)
    if momentum >= 0.35 and buy_ratio > 0.55 and acceleration >= 1.2:
        return "momentum"
    return None


def rank_candidates(candidates: list[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    """Rank eligible candidate records by score, then liquidity, stably."""
    eligible = [c for c in candidates if c.get("decision", {}).get("eligible") is True]
    return sorted(
        eligible,
        key=lambda c: (
            int(c["decision"].get("score", 0)),
            float(c.get("liquidity_usd") or 0),
        ),
        reverse=True,
    )
