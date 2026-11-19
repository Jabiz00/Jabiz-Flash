import json
from pathlib import Path
def write_status(engine,output="dashboard/status.json"):
    p=Path(output); p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(engine.dashboard_status(),indent=2),encoding="utf-8")
