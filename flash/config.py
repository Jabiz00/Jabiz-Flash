import json
def load_config(path="config/default.json"):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
