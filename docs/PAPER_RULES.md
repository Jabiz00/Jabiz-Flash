# Paper rules

- Entry requires liquidity, 24h volume, minimum pair age, positive recent buy imbalance, and positive observed price momentum.
- Stop distance defaults to 1.5% of entry; quantity is sized from 1% of equity risk budget.
- Baseline target is 2R. If momentum weakens while a trade is profitable, early exit is allowed below 2R.
- Hard maximum hold is 300 seconds.
- The same pair cannot be opened twice simultaneously.
- All trades are simulated. The program does not submit transactions.
- Current momentum is computed from snapshots collected while the process is running; after a restart, the short-term price history starts fresh.
