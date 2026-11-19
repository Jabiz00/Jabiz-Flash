import argparse, json, os, time
from datetime import datetime, timezone
from pathlib import Path
import requests

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/"data"; META=DATA/"validation.json"; LEDGER=DATA/"paper_ledger.jsonl"
REPORTS=DATA/"reports"; WORKFLOW="paper-trading.yml"

def iso(ts):
    return datetime.fromtimestamp(ts,timezone.utc).isoformat(timespec="seconds")

def init():
    DATA.mkdir(parents=True,exist_ok=True)
    if META.exists(): return json.loads(META.read_text())
    now=time.time()
    m={"started_at":now,"started_at_utc":iso(now),"duration_days":14,"mode":"PAPER ONLY",
       "starting_balance_usd":100.0,"risk_per_trade":0.01,"max_positions":10,"status":"running"}
    META.write_text(json.dumps(m,indent=2)+"\n")
    print("Validation started:",m["started_at_utc"])
    return m

def events():
    out=[]
    if LEDGER.exists():
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            try: out.append(json.loads(line))
            except (ValueError,TypeError): pass
    return out

def summary(items,since,start_balance):
    exits=[e for e in items if e.get("event")=="paper_exit" and float(e.get("time",0))>=since]
    sessions=[e for e in items if e.get("event")=="paper_session" and float(e.get("time",0))>=since]
    pnl=[float(e.get("net_pnl",0)) for e in exits]; wins=sum(x>0 for x in pnl)
    gp=sum(x for x in pnl if x>0); gl=abs(sum(x for x in pnl if x<0))
    eq=peak=start_balance; dd=0
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
      "net_pnl_usd":round(sum(pnl),4),
      "profit_factor":round(gp/gl,4) if gl else ("infinite" if gp else None),
      "average_r":round(sum(float(e.get("net_pnl",0))/max(float(e.get("risk_budget",0)),1e-12) for e in exits)/len(exits),4) if exits else 0,
      "max_closed_trade_drawdown_pct":round(dd,2),
      "average_holding_seconds":round(sum(holds)/len(holds),2) if holds else 0,
      "exit_reasons":{r:sum(e.get("reason")==r for e in exits) for r in sorted({e.get("reason","unknown") for e in exits})},
      "scan_metrics":scans,"completed_paper_sessions":len(sessions)}

def workflow_runs(since):
    token=os.getenv("GH_TOKEN"); repo=os.getenv("GITHUB_REPOSITORY")
    if not token or not repo: return None
    url=f"https://api.github.com/repos/{repo}/actions/workflows/{WORKFLOW}/runs"
    headers={"Authorization":f"Bearer {token}","Accept":"application/vnd.github+json"}
    found=[]
    for page in range(1,6):
        r=requests.get(url,headers=headers,params={"per_page":100,"page":page,"created":">="+iso(since)[:10]},timeout=20)
        r.raise_for_status(); batch=r.json().get("workflow_runs",[]); found.extend(batch)
        if len(batch)<100: break
    return [x for x in found if x.get("event")=="schedule" and
      datetime.fromisoformat(x["created_at"].replace("Z","+00:00")).timestamp()>=since]

def build():
    m=init(); now=time.time(); start=float(m["started_at"]); since=max(start,now-86400); ev=events()
    daily=summary(ev,since,float(m["starting_balance_usd"]))
    total=summary(ev,start,float(m["starting_balance_usd"]))
    try:
        runs=workflow_runs(since)
        expected=max(0,int((now-since)//300))
        monitor={"scheduled_runs_observed":len(runs),"successful_runs":sum(x.get("conclusion")=="success" for x in runs),
          "failed_or_cancelled_runs":sum(x.get("conclusion") not in ("success",None) for x in runs),
          "expected_5_minute_slots":expected,
          "unobserved_slots_estimate":max(0,expected-len(runs)),
          "note":"Estimate only; GitHub can delay or skip scheduled events."}
    except (requests.RequestException,ValueError,KeyError) as exc:
        monitor={"status":"unavailable","error":str(exc)[:200]}
    elapsed=(now-start)/86400; done=elapsed>=int(m.get("duration_days",14))
    report={"generated_at_utc":iso(now),"validation_started_at_utc":m["started_at_utc"],
      "elapsed_days":round(elapsed,3),"days_remaining":max(0,round(14-elapsed,3)),
      "status":"completed" if done else "running","mode":"PAPER ONLY",
      "daily_period":{"from_utc":iso(since),"to_utc":iso(now)},
      "daily":daily,"cumulative":total,"run_monitor":monitor,
      "limitations":["DexScreener snapshots are not executable quotes.",
       "Five-minute scheduled sessions leave observation gaps.",
       "Paper fills and estimated costs do not establish live profitability."]}
    REPORTS.mkdir(parents=True,exist_ok=True)
    day=datetime.fromtimestamp(now,timezone.utc).strftime("%Y-%m-%d")
    for name in (f"{day}.json","latest.json"):
        (REPORTS/name).write_text(json.dumps(report,indent=2)+"\n")
    if done:
        (REPORTS/"final-14-day.json").write_text(json.dumps(report,indent=2)+"\n")
        m.update({"status":"completed","completed_at_utc":iso(now)})
        META.write_text(json.dumps(m,indent=2)+"\n")
    return report

def notify(msg):
    token=os.getenv("TELEGRAM_BOT_TOKEN",""); chat=os.getenv("TELEGRAM_CHAT_ID","")
    if not token or not chat: print("Telegram not configured; report saved."); return
    try:
        r=requests.post(f"https://api.telegram.org/bot{token}/sendMessage",
          json={"chat_id":chat,"text":msg,"disable_web_page_preview":True},timeout=15); r.raise_for_status()
    except requests.RequestException as e: print("Telegram report delivery failed:",e)

def main():
    p=argparse.ArgumentParser(); p.add_argument("command",choices=("init","report")); a=p.parse_args()
    if a.command=="init": init(); return
    r=build(); d=r["daily"]; c=r["cumulative"]; mon=r["run_monitor"]
    title="🏁 14-DAY VALIDATION COMPLETE" if r["status"]=="completed" else "📊 JABIZ FLASH — DAILY PAPER REPORT"
    msg=(f"{title}\nElapsed: {r['elapsed_days']} days | Remaining: {r['days_remaining']} days\n"
      f"Today: {d['closed_trades']} closed | WR {d['win_rate_pct']:.1f}% | P&L {d['net_pnl_usd']:+.2f} USD\n"
      f"Total: {c['closed_trades']} closed | WR {c['win_rate_pct']:.1f}% | P&L {c['net_pnl_usd']:+.2f} USD\n"
      f"PF: {c['profit_factor']} | Max DD: {c['max_closed_trade_drawdown_pct']:.2f}% | Avg R: {c['average_r']:+.2f}\n"
      f"Average hold: {c['average_holding_seconds']:.1f}s | Completed sessions: {c['completed_paper_sessions']}\n"
      f"Scheduled runs observed (24h): {mon.get('scheduled_runs_observed','unavailable')}\n"
      f"Estimated unobserved 5-min slots: {mon.get('unobserved_slots_estimate','unavailable')}\n"
      "PAPER ONLY. Snapshot-based results are not proof of live execution.")
    print(json.dumps(r,indent=2)); notify(msg)

if __name__=="__main__": main()
