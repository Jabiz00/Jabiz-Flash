import argparse, json, os, time
from datetime import datetime, timezone
from pathlib import Path
import requests

DATA=Path("data"); META=DATA/"validation.json"; LEDGER=DATA/"paper_ledger.jsonl"; REPORTS=DATA/"reports"
STRATEGY_VERSION="hybrid-sniper-live-providers-v1"
def iso(ts): return datetime.fromtimestamp(ts,timezone.utc).isoformat(timespec="seconds")
def init():
    DATA.mkdir(parents=True,exist_ok=True)
    if META.exists():
        existing=json.loads(META.read_text(encoding="utf-8"))
        if existing.get("strategy_version")==STRATEGY_VERSION:
            return existing
        REPORTS.mkdir(parents=True,exist_ok=True)
        backup=REPORTS/"pre-provider-validation.json"
        if not backup.exists():
            backup.write_text(json.dumps(existing,indent=2)+"\n",encoding="utf-8")
    now=time.time(); meta={"started_at":now,"started_at_utc":iso(now),"duration_days":14,
      "mode":"PAPER ONLY","starting_balance_usd":100.0,"risk_per_trade":0.01,"max_positions":10,
      "strategy_version":STRATEGY_VERSION,"status":"running"}
    META.write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8"); print("Validation started:",meta["started_at_utc"]); return meta
def read_events():
    out=[]
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try: out.append(json.loads(line))
            except (ValueError,TypeError): pass
    return out
def summary(rows,since,start):
    exits=[e for e in rows if e.get("event")=="paper_exit" and float(e.get("time",0))>=since]
    sessions=[e for e in rows if e.get("event")=="paper_session" and float(e.get("time",0))>=since]
    pnls=[float(e.get("net_pnl",0)) for e in exits]; wins=sum(x>0 for x in pnls)
    gp=sum(x for x in pnls if x>0); gl=abs(sum(x for x in pnls if x<0))
    eq=peak=start; dd=0
    for e in sorted(exits,key=lambda x:float(x.get("time",0))):
        eq+=float(e.get("net_pnl",0)); peak=max(peak,eq)
        if peak>0: dd=max(dd,(peak-eq)/peak*100)
    scans={}
    for e in sessions:
        for k,v in (e.get("scan_metrics") or {}).items():
            if isinstance(v,(int,float)): scans[k]=scans.get(k,0)+v
    holds=[float(e.get("holding_seconds",0)) for e in exits]
    return {"closed_trades":len(exits),"wins":wins,"losses":len(exits)-wins,
      "win_rate_pct":round(wins/len(exits)*100,2) if exits else 0,
      "net_pnl_usd":round(sum(pnls),4),"profit_factor":round(gp/gl,4) if gl else ("infinite" if gp else None),
      "average_r":round(sum(float(e.get("net_pnl",0))/max(float(e.get("risk_budget",0)),1e-12) for e in exits)/len(exits),4) if exits else 0,
      "max_closed_trade_drawdown_pct":round(dd,2),"average_holding_seconds":round(sum(holds)/len(holds),2) if holds else 0,
      "exit_reasons":{r:sum(e.get("reason")==r for e in exits) for r in sorted({e.get("reason","unknown") for e in exits})},
      "scan_metrics":scans,"completed_paper_sessions":len(sessions)}
def get_runs(since):
    token=os.getenv("GH_TOKEN"); repo=os.getenv("GITHUB_REPOSITORY")
    if not token or not repo: return None
    url=f"https://api.github.com/repos/{repo}/actions/workflows/paper-trading.yml/runs"
    headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json"}; found=[]
    for page in range(1,6):
        r=requests.get(url,headers=headers,params={"per_page":100,"page":page,"created":">="+iso(since)[:10]},timeout=20)
        r.raise_for_status(); batch=r.json().get("workflow_runs",[]); found.extend(batch)
        if len(batch)<100: break
    return [x for x in found if x.get("event")=="schedule" and datetime.fromisoformat(x["created_at"].replace("Z","+00:00")).timestamp()>=since]
def build_report():
    meta=init(); now=time.time(); start=float(meta["started_at"]); since=max(start,now-86400); rows=read_events()
    daily=summary(rows,since,float(meta["starting_balance_usd"])); total=summary(rows,start,float(meta["starting_balance_usd"]))
    try:
        runs=get_runs(since); expected=max(0,int((now-since)//300))
        monitor={"scheduled_runs_observed":len(runs),"successful_runs":sum(x.get("conclusion")=="success" for x in runs),
          "failed_or_cancelled_runs":sum(x.get("conclusion") not in ("success",None) for x in runs),
          "expected_5_minute_slots":expected,"unobserved_slots_estimate":max(0,expected-len(runs)),
          "note":"Estimate only; GitHub can delay or skip scheduled events."}
    except (requests.RequestException,ValueError,KeyError) as exc: monitor={"status":"unavailable","error":str(exc)[:200]}
    elapsed=(now-start)/86400; done=elapsed>=int(meta.get("duration_days",14))
    report={"generated_at_utc":iso(now),"validation_started_at_utc":meta["started_at_utc"],
      "elapsed_days":round(elapsed,3),"days_remaining":max(0,round(14-elapsed,3)),
      "status":"completed" if done else "running","mode":"PAPER ONLY",
      "daily_period":{"from_utc":iso(since),"to_utc":iso(now)},"daily":daily,"cumulative":total,"run_monitor":monitor,
      "limitations":["DexScreener snapshots are not executable quotes.","Five-minute sessions leave observation gaps.",
        "Paper fills and estimated costs do not establish live profitability."]}
    REPORTS.mkdir(parents=True,exist_ok=True); day=datetime.fromtimestamp(now,timezone.utc).strftime("%Y-%m-%d")
    for name in (f"{day}.json","latest.json"): (REPORTS/name).write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    if done:
        (REPORTS/"final-14-day.json").write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
        meta.update({"status":"completed","completed_at_utc":iso(now)}); META.write_text(json.dumps(meta,indent=2)+"\n",encoding="utf-8")
    return report
def send_telegram(message):
    token=os.getenv("TELEGRAM_BOT_TOKEN",""); chat=os.getenv("TELEGRAM_CHAT_ID","")
    if not token or not chat: print("Telegram not configured; report saved."); return
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",json={"chat_id":chat,"text":message,"disable_web_page_preview":True},timeout=15); r.raise_for_status()
    except requests.RequestException as exc: print("Telegram report delivery failed:",exc)
def main():
    parser=argparse.ArgumentParser(); parser.add_argument("command",choices=("init","report")); args=parser.parse_args()
    if args.command=="init": init(); return
    report=build_report(); d=report["daily"]; c=report["cumulative"]; mon=report["run_monitor"]
    title="🏁 14-DAY VALIDATION COMPLETE" if report["status"]=="completed" else "📊 JABIZ FLASH — DAILY PAPER REPORT"
    message=(f"{title}\nElapsed: {report['elapsed_days']} days | Remaining: {report['days_remaining']} days\n"
      f"Today: {d['closed_trades']} closed | WR {d['win_rate_pct']:.1f}% | P&L {d['net_pnl_usd']:+.2f} USD\n"
      f"Total: {c['closed_trades']} closed | WR {c['win_rate_pct']:.1f}% | P&L {c['net_pnl_usd']:+.2f} USD\n"
      f"PF: {c['profit_factor']} | Max DD: {c['max_closed_trade_drawdown_pct']:.2f}% | Avg R: {c['average_r']:+.2f}\n"
      f"Avg hold: {c['average_holding_seconds']:.1f}s | Sessions: {c['completed_paper_sessions']}\n"
      f"Scheduled runs observed (24h): {mon.get('scheduled_runs_observed','unavailable')}\n"
      f"Estimated unobserved 5-min slots: {mon.get('unobserved_slots_estimate','unavailable')}\nPAPER ONLY — no live orders.")
    print(json.dumps(report,indent=2)); send_telegram(message)
if __name__=="__main__": main()
