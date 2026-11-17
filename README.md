# Jabiz Flash — Solana Paper-Trading Bot

A runnable **paper-trading prototype** for Solana tokens. It reads public market snapshots from DexScreener and simulates trades locally. It never connects to a wallet or submits swaps.

## Important scope
This is an initial paper-trading build, not a production seconds-scalping engine. DexScreener search is polled (default 5 seconds), not a low-latency tick feed. The momentum rules are a transparent prototype and need calibration during the 14-day paper test. It does not guarantee trade frequency or profitability.

## Requirements
- Python 3.10+
- Internet access
- No wallet, seed phrase, or paid API key required

## Run
```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -e .
python -m flash
```

Stop with Ctrl+C. Trades and equity are saved in `data/paper_ledger.jsonl` and `data/state.json`.

## Initial settings
- Starting simulated balance: $100
- Risk budget: 1% of current equity per trade
- Maximum simultaneous positions: 10
- Maximum holding time: 300 seconds
- Early exit allowed below 2R when momentum weakens
- Target: 2R baseline; can trail when momentum remains strong
- Paper mode only; live execution is not implemented

## Safety / interpretation
- A simulated fill is not a real executable Solana fill.
- Fees and slippage are estimated; actual execution can be materially worse.
- The scanner can miss tokens and may return stale or incomplete data.
- Do not add wallet secrets. This project has no reason to request them.
- Keep the process running on a reliable internet connection for continuous monitoring.
