import json
from pathlib import Path

def load_config(path="config/default.json"):
    with open(path, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    return cfg
