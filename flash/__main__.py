import argparse,time
from .config import load_config
from .market import DexScreener,pair_snapshot
from .engine import PaperEngine
from .notify import TelegramNotifier
from .dashboard import write_status

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--duration-seconds",type=int,default=230)
    args=parser.parse_args(); cfg=load_config(); notifier=TelegramNotifier()
    engine=PaperEngine(cfg,notifier=notifier); market=DexScreener()
    deadline=time.time()+max(30,min(args.duration_seconds,240))
    print("JABIZ FLASH — PAPER ONLY; NO WALLET OR LIVE SWAPS")
    while time.time()<deadline:
        pairs=market.discover(cfg["search_terms"],cfg["max_tokens_to_track"]); now=time.time()
        for pair in pairs: engine.update(pair_snapshot(pair),now)
        engine.save_state(); write_status(engine)
        print(f"[SCAN] {len(pairs)} pairs | open {len(engine.positions)} | equity ${engine.equity:.2f}")
        time.sleep(cfg["poll_seconds"])
    engine.save_state(); write_status(engine)
    stats=engine.stats
    closed=stats["closed_trades"]
    win_rate=(stats["wins"]/closed*100) if closed else 0.0
    notifier.send(
        f"📊 JABIZ FLASH — PAPER SESSION COMPLETE\n"
        f"Equity: ${engine.equity:.2f} (start ${cfg['starting_balance_usd']:.2f})\n"
        f"Realized P&L: ${stats['realized_pnl']:+.2f}\n"
        f"Closed trades: {closed} | Wins: {stats['wins']} | Losses: {stats['losses']}\n"
        f"Win rate: {win_rate:.1f}% | Open positions: {len(engine.positions)}\n"
        f"Mode: PAPER ONLY — no live orders"
    )
if __name__=="__main__": main()
