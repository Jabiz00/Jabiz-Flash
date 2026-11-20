# Jabiz Flash — Hybrid Sniper (single active strategy)

**Status:** Integrated into the paper engine; provider-gated paper entries remain disabled until verified safety and execution-impact adapters are configured.
**Mode:** PAPER ONLY. No wallet, private key, signing, swaps, or real-money execution.

## Locked strategy decisions
- One active entry strategy: **Hybrid Sniper**. The previous momentum-only entry path is retired.
- Entry patterns: momentum sniper, breakout/retest, pullback continuation.
- Token safety: strict, fail-closed. Unknown, stale, missing, malformed, or provider-error evidence rejects the candidate.
- Candidate selection: score eligible candidates and rank best-first across each discovery batch.
- Confirmation: fast; a setup must have an independent market confirmation.
- Score: 100 points — market quality 25, buy flow/volume 25, setup 30, execution quality 20. Safety is a hard gate and never contributes compensating points.
- Experimental thresholds: liquidity >= $15,000; 24h volume >= $30,000; minimum 4 transactions in 5m; pair age >= 15m; score >= 70; estimated impact <= 1%; top-10 concentration <= 35%; safety evidence <= 300s old.
- Momentum pattern: >= 0.35% short-window momentum, buy-volume ratio > 0.55, acceleration >= 1.2.
- Portfolio envelope retained: $100 starting virtual balance, 1% risk budget per trade, up to 10 concurrent positions, 300s maximum hold, 2R target, trailing protection begins at +1R.

Thresholds are experimental filters, not evidence of profitability or a promised win rate.

## Integration now present
- The paper engine calls the safety gate before candidate scoring.
- The old momentum-only entry branch is removed from the active engine.
- Market snapshots are normalized defensively; malformed prices/metrics do not crash a scan.
- Candidates are evaluated as a batch and ranked best-first before opening positions.
- Position records, ledger entries, Telegram alerts, and dashboard data include model, score, safety status, contract, target, hold duration, and P&L.
- Existing state and ledger formats are retained; new Position fields have defaults so older saved positions remain loadable.
- Telegram response bodies are checked, not just HTTP status codes.
- Scanner diagnostics distinguish safety, score, execution, setup, transaction-count, liquidity, volume, age, and flow rejections.

## Important provider boundary — no fabricated safety
DexScreener search snapshots do not provide verified mint/freeze authority, holder concentration, RugCheck findings, or a reliable executable sell-route/impact quote. Those values are not inferred from transaction counts or invented. The runtime currently has no configured safety provider and no execution-impact quote provider. Consequently **the live paper engine intentionally rejects all new entries by default** until both providers are implemented and their schemas tested. Existing open paper positions continue to be managed.

To enable entries later, implement and test providers for:
1. Solana mint/freeze authority and token-program/extension checks.
2. Holder distribution with pool/burn/treasury exclusions documented.
3. RugCheck risk findings mapped to the normalized safety contract.
4. A current sell-side quote/route and impact estimate for the exact token and simulated size.

The safety provider callback must return the exact normalized evidence accepted by `evaluate_token_safety`; provider exceptions and missing values reject. The execution quote must populate `execution_impact_pct`. No permissive fallback is allowed.

## Validation
A clean CI run is required before merge. The first 14-day validation window must start only after the integrated code and required providers are active; runs before then are useful for scanner/diagnostic checks, not strategy performance validation.
