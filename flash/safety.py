"""Strict, provider-agnostic safety gate for Solana paper-trading candidates.

This module consumes normalized on-chain/provider evidence. It deliberately does
not fetch external data: callers must supply fresh, attributable evidence.
Unknown critical fields fail closed. No live-trading functionality exists here.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
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


def evaluate_token_safety(
    evidence: Mapping[str, Any],
    *,
    now: float,
    max_age_seconds: int = 300,
    max_top10_holder_pct: float = 35.0,
) -> SafetyResult:
    """Evaluate normalized safety evidence; missing critical evidence rejects.

    Required keys: mint_authority, freeze_authority, top10_holder_pct,
    rugcheck_status, critical_risks, sell_route_available, checked_at.
    Authority values must be None (revoked) or a non-empty authority string.
    rugcheck_status must be 'good' or 'warn'; 'danger'/'unknown' reject.
    """
    reasons: list[str] = []
    warnings: list[str] = []
    required = (
        "mint_authority", "freeze_authority", "top10_holder_pct",
        "rugcheck_status", "critical_risks", "sell_route_available",
        "checked_at",
    )
    missing = [key for key in required if key not in evidence or evidence[key] is None]
    if missing:
        reasons.append("missing_safety_evidence:" + ",".join(missing))
        return SafetyResult("REJECT", False, tuple(reasons), tuple(warnings), None)

    checked_at = float(evidence["checked_at"])
    age = now - checked_at
    if age < -30 or age > max_age_seconds:
        reasons.append("stale_or_future_safety_evidence")

    if evidence["mint_authority"]:
        reasons.append("active_mint_authority")
    if evidence["freeze_authority"]:
        reasons.append("active_freeze_authority")

    try:
        concentration = float(evidence["top10_holder_pct"])
        if not 0 <= concentration <= 100:
            raise ValueError
        if concentration > max_top10_holder_pct:
            reasons.append("excessive_top10_holder_concentration")
    except (TypeError, ValueError):
        reasons.append("invalid_holder_concentration")

    rug_status = str(evidence["rugcheck_status"]).lower()
    if rug_status not in {"good", "warn"}:
        reasons.append("rugcheck_not_clear")
    if rug_status == "warn":
        warnings.append("rugcheck_warning")
    critical = evidence["critical_risks"]
    if not isinstance(critical, (list, tuple)):
        reasons.append("invalid_risk_findings")
    elif critical:
        reasons.append("critical_rugcheck_findings")

    if evidence["sell_route_available"] is not True:
        reasons.append("no_verified_sell_route")

    passed = not reasons
    return SafetyResult(
        "PASS" if passed else "REJECT",
        passed,
        tuple(dict.fromkeys(reasons)),
        tuple(warnings),
        checked_at,
    )
