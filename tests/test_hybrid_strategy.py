from flash.safety import evaluate_token_safety
from flash.strategy import detect_entry_model, rank_candidates, score_candidate


def safe_evidence(**overrides):
    data = {
        "mint_authority": None,
        "freeze_authority": None,
        "top10_holder_pct": 22.0,
        "rugcheck_status": "good",
        "critical_risks": [],
        "sell_route_available": True,
        "checked_at": 1000.0,
    }
    data.update(overrides)
    return data


def strong_metrics(**overrides):
    data = {
        "liquidity_usd": 50000,
        "volume24_usd": 100000,
        "buy_volume_ratio": 0.68,
        "volume_acceleration": 2.0,
        "setup_confirmation": 0.9,
        "execution_impact_pct": 0.2,
        "momentum_pct": 0.6,
        "higher_lows": True,
        "breakout_confirmed": False,
        "retest_held": False,
        "pullback_reclaim": False,
    }
    data.update(overrides)
    return data


def test_strict_safety_passes_fresh_clean_evidence():
    result = evaluate_token_safety(safe_evidence(), now=1010)
    assert result.passed and result.status == "PASS"


def test_strict_safety_rejects_active_authorities():
    result = evaluate_token_safety(
        safe_evidence(mint_authority="authority-address"), now=1010
    )
    assert not result.passed
    assert "active_mint_authority" in result.reasons


def test_strict_safety_fails_closed_on_missing_or_stale_data():
    missing = safe_evidence()
    del missing["sell_route_available"]
    assert not evaluate_token_safety(missing, now=1010).passed
    stale = evaluate_token_safety(safe_evidence(), now=2000)
    assert "stale_or_future_safety_evidence" in stale.reasons


def test_strict_safety_rejects_concentration_and_critical_flags():
    result = evaluate_token_safety(
        safe_evidence(top10_holder_pct=48, critical_risks=["freeze"]),
        now=1010,
    )
    assert not result.passed
    assert "excessive_top10_holder_concentration" in result.reasons
    assert "critical_rugcheck_findings" in result.reasons


def test_detects_three_entry_models():
    assert detect_entry_model(strong_metrics()) == "momentum"
    assert detect_entry_model(strong_metrics(
        breakout_confirmed=True, retest_held=True
    )) == "breakout_retest"
    assert detect_entry_model(strong_metrics(
        pullback_reclaim=True, higher_lows=True
    )) == "pullback_continuation"


def test_fast_confirmation_requires_safety_setup_and_independent_signal():
    decision = score_candidate(strong_metrics(), safety_passed=True)
    assert decision.eligible
    assert decision.model == "momentum"
    no_safety = score_candidate(strong_metrics(), safety_passed=False)
    assert not no_safety.eligible and no_safety.score == 0


def test_rejects_bad_execution_and_weak_candidate():
    decision = score_candidate(
        strong_metrics(execution_impact_pct=1.5), safety_passed=True
    )
    assert not decision.eligible
    assert "estimated_price_impact_too_high" in decision.reasons


def test_ranks_best_candidates_first():
    candidates = [
        {"liquidity_usd": 50000, "decision": {"eligible": True, "score": 80}},
        {"liquidity_usd": 80000, "decision": {"eligible": True, "score": 90}},
        {"liquidity_usd": 100000, "decision": {"eligible": False, "score": 99}},
    ]
    assert rank_candidates(candidates)[0]["decision"]["score"] == 90
    assert len(rank_candidates(candidates)) == 2


def test_none_authority_values_mean_revoked_not_missing():
    result = evaluate_token_safety(safe_evidence(), now=1010)
    assert result.passed

def test_invalid_authority_value_fails_closed():
    result = evaluate_token_safety(safe_evidence(mint_authority=" "), now=1010)
    assert not result.passed
    assert "invalid_mint_authority" in result.reasons

def test_malformed_numeric_metrics_do_not_crash():
    decision = score_candidate(strong_metrics(
        liquidity_usd="not-a-number",
        execution_impact_pct="unknown",
        momentum_pct=None,
    ), safety_passed=True)
    assert not decision.eligible
    assert "execution_impact_unavailable" in decision.reasons
