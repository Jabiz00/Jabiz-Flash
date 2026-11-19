# Paper rules and limitations

- Long-only spot paper entries.
- Filters: minimum liquidity, 24h volume, pair age, positive recent buy imbalance and observed positive price momentum.
- Stop distance defaults to 1.5% of entry.
- Quantity sizing includes estimated stop loss plus estimated round-trip costs at the planned stop within 1% of current equity.
- 2R target is based on price distance before costs; net realized R is lower after estimated costs.
- Profitable early exit is allowed below 2R when momentum weakens.
- Trailing stop activates after 1R.
- Intended maximum hold is 300 seconds, but GitHub schedule gaps can delay observation.
- No mint/freeze authority audit, honeypot simulation, executable quote, or live order routing exists.
