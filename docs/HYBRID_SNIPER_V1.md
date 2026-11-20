# Hybrid Sniper v1 — implementation notes

Status: core decision modules added; not yet connected to the market scanner or paper engine.
Mode: paper trading only.

## Locked decisions
- Token safety: strict; fail closed on missing/stale critical evidence.
- Candidate selection: best eligible candidate first.
- Entry confirmation: fast, requiring a detected setup plus at least one independent market signal.
- Entry models: momentum, breakout/retest, pullback continuation.
- Score: 100-point market/execution score; safety is a hard gate and cannot be offset by score.
- Risk envelope remains unchanged: $100 initial paper balance, 1% risk, max 10 open positions, 300-second maximum hold, 2R baseline target.

## Experimental floors
- Liquidity: $15,000.
- 24-hour volume: $30,000.
- Estimated price impact: at most 1%.
- Top-10 holder concentration: at most 35%.
- Safety evidence freshness: at most 300 seconds.
- Momentum model threshold: 0.35%, buy-volume ratio > 0.55, volume acceleration >= 1.2.

These are initial research thresholds, not claims of profitability. Pair age and minimum transaction count remain market-quality inputs and must be incorporated by the adapter before integration.

## Safety evidence contract
The safety module requires normalized, timestamped evidence for mint authority, freeze authority, top-10 holder concentration, RugCheck status/findings, and sell-route availability. Provider adapters are not implemented in this change. Missing evidence rejects the candidate. The strict authority policy rejects active mint/freeze authority. Provider responses must be mapped to this contract only after their current schema and semantics are verified.

## Integration plan
1. Add provider adapters for on-chain mint/freeze authority and holder distribution, plus RugCheck and a credible sell-route quote source.
2. Normalize DexScreener market snapshots to include 5-minute USD buy/sell volume, volume acceleration, and enough time-series observations for breakout/retest/pullback detection.
3. Run safety before scoring; score and rank candidates; recheck safety/price/liquidity/exit route at paper-entry time.
4. Integrate decisions into PaperEngine while retaining a baseline strategy toggle for A/B paper comparison.
5. Add dashboard fields for safety outcome, model, score, and rejection reasons.
6. Run tests and verify Telegram delivery after the separate workflow fix is merged.

## Safety boundaries
No wallet, private-key, signing, swap-submission, or live execution code is introduced. All decisions are advisory inputs to paper simulation only. A successful provider safety check is not a guarantee that a token is safe or sellable in future.
