import time
from .config import load_config
from .market import DexScreener, pair_snapshot
from .engine import PaperEngine

def main():
    cfg = load_config()
    market = DexScreener()
    engine = PaperEngine(cfg)
    print("JABIZ FLASH — PAPER TRADING ONLY")
    print(f"Virtual equity: ${engine.equity:.2f} | risk/trade: {cfg['risk_per_trade']*100:.1f}% | max positions: {cfg['max_positions']}")
    print("No wallet connection. No real swaps. Press Ctrl+C to stop.")
    while True:
        pairs = market.discover(cfg["search_terms"], cfg["max_tokens_to_track"])
        now = time.time()
        for pair in pairs:
            snap = pair_snapshot(pair)
            engine.update(snap, now)
        engine.save_state()
        print(f"[SCAN] {len(pairs)} Solana pairs | open positions: {len(engine.positions)} | equity: ${engine.equity:.2f}")
        time.sleep(cfg["poll_seconds"])

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nJabiz Flash stopped safely.")
