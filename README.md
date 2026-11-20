# Jabiz Flash — Paper Trading Prototype

Paper trading only. No wallet connection, private keys, or live swaps are included.

## Included
- DexScreener Solana pair discovery and observed-price polling
- Strict read-only Solana mint/freeze checks, largest-account concentration estimate, RugCheck risk screening, and Jupiter size-specific sell quotes
- Best-first Hybrid Sniper shortlist (momentum, breakout/retest, pullback continuation)
- Simulated long-only entries and exits
- 1% risk budget including estimated stop loss and round-trip costs at the planned stop
- Maximum 10 simultaneous positions
- 2R baseline target, profitable early exit on weakening momentum, trailing stop after 1R
- 300-second intended maximum hold
- Persistent state and JSONL trade ledger
- Optional Telegram entry/exit/session notifications
- Read-only web dashboard
- GitHub Actions tests, scheduled paper sessions and GitHub Pages deployment

## Important limitations
This is not a production seconds-scalping system. GitHub Actions is not always-on; the paper workflow runs a bounded session approximately every five minutes, and scheduled runs can be delayed. Prices are observed DexScreener snapshots, not executable quotes. Gaps between runs can delay stop/target observation. Provider checks fail closed when RPC, RugCheck, or Jupiter evidence is missing. Largest-account concentration is an estimate, not a full holder census. Token-2022 extensions are rejected until individually audited. No profitability is guaranteed.

## Mobile installation
1. Extract this ZIP on your phone.
2. Upload the **contents inside the outer `Jabiz-Flash` folder** into the root of your existing GitHub repository, preserving folders. Do not create an extra nested `Jabiz-Flash/Jabiz-Flash` folder.
3. Replace matching files when prompted and commit.
4. For Telegram, add repository Actions secrets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` under Settings → Secrets and variables → Actions. Both are optional. Optional `SOLANA_RPC_URL` (recommended free-tier RPC) and `JUPITER_API_KEY` (free tier; keyless fallback is rate-limited) can also be added.
5. For the web dashboard, open Settings → Pages and set source to **GitHub Actions**.
6. Open Actions → Jabiz Flash Paper Sessions → Run workflow for a manual first run. Scheduled runs are configured every five minutes.

## Dashboard
The static read-only dashboard fetches `dashboard/status.json` from this public repository and refreshes every 30 seconds. It shows the last confirmed market-data response and marks data stale after ten minutes. The GitHub Actions scheduler runs bounded sessions approximately every five minutes; GitHub may delay or skip scheduled events, so this is not a guaranteed always-on/real-time feed.

## Local test (optional)
Python 3.10+: `pip install -e ".[dev]"` then `pytest -v`.

No live execution module exists. A green test run validates only the included tests, not profitability or live readiness.


## Always-on paper runtime
See [docs/ALWAYS_ON_DEPLOYMENT.md](docs/ALWAYS_ON_DEPLOYMENT.md) for the Docker-based continuous runtime, local read-only dashboard/API, persistent paper state, restart policy, and deployment safety notes. The runtime remains paper-only; live execution is not implemented.
