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
    notifier.send(f"JABIZ FLASH SESSION COMPLETE\nEquity ${engine.equity:.2f}\nOpen {len(engine.positions)}\nClosed {engine.stats['closed_trades']}")
if __name__=="__main__": main()
