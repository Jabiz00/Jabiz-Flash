# Jabiz Flash — Hybrid Sniper (single active strategy)

**Status:** Integrated read-only safety and execution-quote providers. Paper-only.
**Execution boundary:** No wallet, private key, signing, swap submission, or real-money order path exists.

## Locked strategy
- Hybrid Sniper is the only active strategy: momentum, breakout/retest, and pullback continuation.
- Strict fail-closed token safety; best-first candidate ranking; fast confirmation.
- $100 virtual balance; 1% risk budget; maximum 10 open positions; 300-second intended hold; 2R target; trailing protection begins at +1R.
- Experimental filters: $15k liquidity, $30k 24h volume, four or more 5m transactions, pair age at least 15m, score >=70, quoted sell impact <=1%, and top-holder concentration <=35%.
- Momentum uses short-window observed price movement, transaction buy-pressure ratio (buys / total buys+sells, not USD volume), and 1h volume relative to the 24h hourly average. DexScreener does not expose USD buy/sell volume in this search response, so transaction counts are not labeled as dollar flow.

## Live read-only data providers
1. **DexScreener REST** discovers Solana pairs and refreshes observed prices/liquidity/volume/transaction counts.
2. **Solana JSON-RPC** checks mint/freeze authority, token program, decimals/supply, and largest token-account owners.
3. **RugCheck summary** supplies risk levels; critical/high/danger or unknown risk levels reject.
4. **Jupiter Swap API v2 /order** requests a size-specific token-to-SOL sell quote only. The bot reads route availability and priceImpactPct; it never asks for a taker transaction or submits an order.

Provider errors, stale/missing fields, missing sell route, malformed responses, and unsupported Token-2022 extensions fail closed. Jupiter quote calls are throttled to 0.5 requests/second without a key and 1 request/second with a configured key. Provider checks are limited to the best six pre-ranked candidates per scan to respect upstream limits.

### Concentration caveat
The provider aggregates wallet owners represented in Solana's ten largest token accounts. This is an estimate from the RPC largest-account response, not a full token-account index of every wallet. It can miss secondary accounts belonging to the same wallet. LP/pool vaults can also appear as large accounts and cause conservative rejection.

### Token-2022 policy
Any reported mint extensions are rejected until each extension is explicitly reviewed and added to an allowlist. This may exclude otherwise legitimate Token-2022 tokens by design.

## Data freshness and runtime
- Each GitHub Actions run performs a bounded paper session for up to 230 seconds, polling DexScreener on a five-second loop.
- The scheduled workflow is configured every five minutes and persists state/ledger/dashboard status to the repository.
- The dashboard polls the published status file every 30 seconds and distinguishes dashboard refresh time from the last confirmed market-data response. It marks data stale when no successful market response has occurred within ten minutes.
- GitHub Actions scheduled events can be delayed or skipped. This is not an always-on process, and static GitHub Pages cannot receive each internal five-second scan until the workflow publishes its commit. A continuously fresh five-second dashboard requires a continuously running host and WebSocket-capable market feed; GitHub Actions alone cannot guarantee that.

## Optional GitHub Actions secrets
- TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID: notifications.
- SOLANA_RPC_URL: recommended dedicated/free-tier RPC endpoint. If omitted, the public Solana mainnet RPC is used; Solana documents shared public RPC as rate-limited and not production infrastructure.
- JUPITER_API_KEY: optional free Jupiter Developer Platform key for higher API rate allowance. Keyless mode is throttled conservatively.

Never paste secrets into chat or commit them to the repository.

## Validation and limits
The 14-day strategy validation must begin only after provider-enabled code is running and provider health is visible. CI tests validate software behavior, not profitability. Simulated fills, snapshot prices, quoted impact, and estimated fees do not guarantee live execution or returns.
