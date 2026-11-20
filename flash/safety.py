"""Strict fail-closed Solana token safety evaluation.

Provider adapters must supply normalized evidence. None is a valid value for
revoked mint/freeze authorities; missing keys are not. No network or trading
operations are performed in this module.
"""
from __future__ import annotations
from dataclasses import dataclass, asdict
from math import isfinite
from typing import Any, Mapping

@dataclass(frozen=True)
class SafetyResult:
    status: str
    passed: bool
    reasons: tuple[str, ...]
    warnings: tuple[str, ...]
    checked_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["reasons"] = list(self.reasons)
        result["warnings"] = list(self.warnings)
        return result

def evaluate_token_safety(evidence: Mapping[str, Any] | None, *, now: float,
                          max_age_seconds: int = 300,
                          max_top10_holder_pct: float = 35.0) -> SafetyResult:
    """Evaluate normalized evidence; missing/invalid critical evidence rejects."""
    if not isinstance(evidence, Mapping):
        return SafetyResult("REJECT", False, ("safety_evidence_unavailable",), (), None)
    required = ("mint_authority", "freeze_authority", "top10_holder_pct",
                "rugcheck_status", "critical_risks", "sell_route_available", "checked_at")
    missing = [key for key in required if key not in evidence]
    if missing:
        return SafetyResult("REJECT", False,
            ("missing_safety_evidence:" + ",".join(missing),), (), None)

    reasons: list[str] = []
    warnings: list[str] = []
    checked_at = None
    try:
        checked_at = float(evidence["checked_at"])
        if not isfinite(checked_at) or not isfinite(float(now)):
            raise ValueError
        age = float(now) - checked_at
        if age < -30 or age > max_age_seconds:
            reasons.append("stale_or_future_safety_evidence")
    except (TypeError, ValueError, OverflowError):
        reasons.append("invalid_safety_timestamp")

    # None explicitly means revoked/no authority. Empty strings are invalid.
    for key, reason in (("mint_authority", "active_mint_authority"),
                        ("freeze_authority", "active_freeze_authority")):
        value = evidence[key]
        if value is not None:
            if not isinstance(value, str) or not value.strip():
                reasons.append("invalid_" + key)
            else:
                reasons.append(reason)

    try:
        concentration = float(evidence["top10_holder_pct"])
        if not isfinite(concentration) or not 0 <= concentration <= 100:
            raise ValueError
        if concentration > max_top10_holder_pct:
            reasons.append("excessive_top10_holder_concentration")
    except (TypeError, ValueError, OverflowError):
        reasons.append("invalid_holder_concentration")

    rug_status = str(evidence["rugcheck_status"]).strip().lower()
    if rug_status not in {"good", "warn"}:
        reasons.append("rugcheck_not_clear")
    elif rug_status == "warn":
        warnings.append("rugcheck_warning")
    critical = evidence["critical_risks"]
    if not isinstance(critical, (list, tuple)):
        reasons.append("invalid_risk_findings")
    elif critical:
        reasons.append("critical_rugcheck_findings")
    if evidence["sell_route_available"] is not True:
        reasons.append("no_verified_sell_route")

    reasons = list(dict.fromkeys(reasons))
    return SafetyResult("PASS" if not reasons else "REJECT", not reasons,
                        tuple(reasons), tuple(warnings), checked_at)
