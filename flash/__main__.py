import argparse
import os
import signal
import threading
import time

from .config import load_config
from .market import DexScreener, pair_snapshot, market_data_is_stale
from .engine import PaperEngine
from .notify import TelegramNotifier
from .dashboard import write_status
from .web import start_status_server
from .providers import SolanaTokenAssessor


def main():
    parser = argparse.ArgumentParser(description="Jabiz Flash paper-trading engine")
    parser.add_argument("--duration-seconds", type=int, default=230,
                        help="Bounded session length (30-240 seconds)")
    parser.add_argument("--continuous", action="store_true",
                        help="Run continuously until SIGTERM or SIGINT")
    args = parser.parse_args()

    cfg = load_config()
    notifier = TelegramNotifier()
    assessor = SolanaTokenAssessor()
    engine = PaperEngine(cfg, notifier=notifier, safety_provider=assessor.assess)
    market = DexScreener()
    # Carry the last confirmed market response across short GitHub Actions sessions.
    try:
        import json
        with open("dashboard/status.json", encoding="utf-8") as previous:
            prior = json.load(previous)
        prior_success = (prior.get("scanner") or {}).get("api", {}).get("last_success_at")
        if prior_success:
            market.metrics["last_success_at"] = float(prior_success)
    except (OSError, ValueError, TypeError):
        pass
    stop_event = threading.Event()
    started_at = time.time()

    def request_stop(signum, frame):
        print(f"[runtime] received signal {signum}; shutting down cleanly")
        stop_event.set()

    signal.signal(signal.SIGTERM, request_stop)
    signal.signal(signal.SIGINT, request_stop)

    port = int(os.getenv("JABIZ_STATUS_PORT", "8080"))
    host = os.getenv("JABIZ_STATUS_HOST", "0.0.0.0")
    status_server = start_status_server(host=host, port=port)
    print(f"[runtime] read-only dashboard listening on {host}:{port}")
    print("JABIZ FLASH — PAPER ONLY; NO WALLET OR LIVE SWAPS")

    deadline = None if args.continuous else time.monotonic() + max(30, min(args.duration_seconds, 240))
    cycle = 0
    last_error_notice = 0.0
    last_stale_notice = 0.0

    try:
        while not stop_event.is_set() and (deadline is None or time.monotonic() < deadline):
            cycle += 1
            engine.scan_metrics = engine.empty_scan_metrics()
            try:
                pairs = market.discover(cfg["search_terms"], cfg["max_tokens_to_track"], engine.positions.keys())
                now = time.time()
                snapshots = []
                for pair in pairs:
                    try:
                        snapshots.append(pair_snapshot(pair))
                    except (TypeError, ValueError, KeyError) as exc:
                        engine.scan_metrics["invalid_price"] += 1
                        print(f"[scanner] skipped malformed pair: {exc}")
                engine.process_scan(snapshots, now)
                engine.market_status = market.status()
                engine.market_status["safety_provider"] = assessor.status()
                engine.market_status["execution_impact_source"] = "Jupiter read-only sell quote"
                engine.market_status["last_scan_at"] = now
                engine.market_status["cycle"] = cycle
            except Exception as exc:
                now = time.time()
                engine.market_status = market.status()
                engine.market_status.update({"safety_provider":assessor.status(), "runtime_error": str(exc)[:240], "last_scan_at": now, "cycle": cycle})
                print(f"[scanner] cycle {cycle} failed: {exc}")
                if now - last_error_notice >= 300:
                    notifier.send("⚠️ JABIZ FLASH — SCANNER ERROR\n" + str(exc)[:300] + "\nPaper engine remains running and will retry.")
                    last_error_notice = now

            if market_data_is_stale(engine.market_status.get("last_success_at"), now,
                                     int(cfg.get("data_stale_after_seconds",600))):
                if now - last_stale_notice >= 300:
                    notifier.send("⚠️ JABIZ FLASH — MARKET DATA STALE\nNo successful DexScreener response within the configured freshness window. New entries remain fail-closed; check provider/API health.")
                    last_stale_notice = now
            engine.save_state()
            write_status(engine)
            metrics, api = engine.scan_metrics, engine.market_status
            print(f"[SCAN {cycle}] discovered={metrics['discovered']} qualified={metrics['qualified_entries']} safety_rejected={metrics.get('rejected_safety', 0)} "
                  f"open={len(engine.positions)} API={api.get('successful_requests', 0)}/{api.get('request_count', 0)} "
                  f"success | equity={engine.equity:.2f}")
            if deadline is not None and time.monotonic() >= deadline:
                break
            stop_event.wait(max(1, int(cfg.get("poll_seconds", 5))))
    finally:
        ended_at = time.time()
        engine.log({"event": "paper_session", "time": ended_at, "started_at": started_at,
                    "duration_seconds": round(ended_at - started_at, 2), "cycles": cycle,
                    "scan_metrics": dict(engine.scan_metrics), "market_status": dict(engine.market_status),
                    "open_positions": len(engine.positions), "equity": engine.equity})
        engine.save_state()
        write_status(engine)
        if status_server:
            status_server.shutdown()
            status_server.server_close()

    stats = engine.stats
    closed = stats["closed_trades"]
    win_rate = (stats["wins"] / closed * 100) if closed else 0.0
    notifier.send(
        f"📊 JABIZ FLASH — PAPER SESSION STOPPED\n"
        f"Equity: {engine.equity:.2f} USD (start {cfg['starting_balance_usd']:.2f})\n"
        f"Realized P&L: {stats['realized_pnl']:+.2f} USD\n"
        f"Closed trades: {closed} | Wins: {stats['wins']} | Losses: {stats['losses']}\n"
        f"Win rate: {win_rate:.1f}% | Open positions: {len(engine.positions)}\n"
        "Mode: PAPER ONLY — no live orders"
    )


if __name__ == "__main__":
    main()
