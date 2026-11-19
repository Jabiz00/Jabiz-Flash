# Jabiz Flash — Always-on paper runtime

Jabiz Flash is a standalone Solana market-monitoring and paper-trading project. It is separate from Jabiz AI Crypto Bot.

## Safety boundary
- Paper trading only. No wallet, private-key handling, signing, or live swaps are included.
- Keep real-money execution disabled. Any future live-trading work requires separate validation and explicit user approval.
- Existing strategy settings remain unchanged: $100 virtual balance, 1% risk budget, maximum 10 positions, 2R target baseline, and 300-second maximum hold.
- Paper fills are estimates based on DexScreener snapshots, not guaranteed executable prices.

## Always-on deployment (Docker)
The continuous runtime is intended for an always-on Linux VM/VPS. GitHub Actions remains responsible for tests and static GitHub Pages deployment; it is not the trading runtime.

1. Install Docker Engine and the Docker Compose plugin on the server.
2. Clone this repository and check out the reviewed always-on runtime branch/merge.
3. Copy `.env.example` to `.env` and add Telegram credentials if desired. Never commit `.env`.
4. Start with `docker compose up -d --build`.
5. Check `docker compose logs -f jabiz-flash` and `docker compose ps`.
6. The read-only dashboard is served on `127.0.0.1:8080`; health is `/healthz` and live status JSON is `/api/status`.

The compose file binds the web port to localhost deliberately. Before making the dashboard public, configure an HTTPS reverse proxy or secure tunnel with authentication/rate limiting appropriate to your deployment. Do not expose the raw service port directly to the internet.

## Runtime behaviour
- The process runs until SIGTERM/SIGINT and is restarted by Docker after an unexpected exit.
- The engine polls the existing DexScreener search integration using the configured `poll_seconds` interval (currently 5 seconds).
- State and ledger are kept in persistent Docker volumes, not committed to GitHub on every scan.
- The process attempts to recover from scan errors and sends throttled Telegram error alerts.
- The status server exposes read-only dashboard data and a health endpoint.
- Configure server monitoring, backups, disk limits, firewall rules, and HTTPS before relying on the service.

## Current limitations / next milestones
This is the first always-on infrastructure milestone, not yet a production-grade low-latency scalper. The data source is still DexScreener REST polling, not a dedicated Solana transaction stream. A 5-second poll can miss events and price moves; REST snapshots and estimated paper fills do not model queue position, transaction inclusion, failed swaps, or exact slippage. Next engineering milestones are a streaming market-data adapter (e.g. Helius), quote-based paper fill modelling, durable database storage, reconnection/backoff tests, and operational monitoring.

## Existing GitHub Actions
The scheduled paper workflow remains for compatibility/testing during migration. Do not run both the scheduled GitHub paper trader and the always-on server against the same state file; they use separate environments and would create divergent paper ledgers. Once the server runtime is validated, disable the scheduled paper-trading workflow and retain CI tests / Pages deployment.
