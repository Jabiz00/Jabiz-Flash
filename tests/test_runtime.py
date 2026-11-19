import json
from urllib.request import urlopen

from flash import web


def test_status_server_exposes_health_status_and_dashboard(tmp_path, monkeypatch):
    status_file = tmp_path / "status.json"
    status_file.write_text(json.dumps({"mode": "PAPER ONLY", "equity": 100}), encoding="utf-8")
    dashboard_file = tmp_path / "index.html"
    dashboard_file.write_text("<h1>Jabiz Flash</h1>", encoding="utf-8")
    monkeypatch.setattr(web, "STATUS", status_file)
    monkeypatch.setattr(web, "DASHBOARD", dashboard_file)

    server = web.start_status_server(host="127.0.0.1", port=0)
    base = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(base + "/healthz", timeout=3) as response:
            assert response.status == 200
            assert json.loads(response.read())["ok"] is True
        with urlopen(base + "/api/status", timeout=3) as response:
            payload = json.loads(response.read())
            assert payload["mode"] == "PAPER ONLY"
            assert payload["equity"] == 100
        with urlopen(base + "/", timeout=3) as response:
            assert b"Jabiz Flash" in response.read()
    finally:
        server.shutdown()
        server.server_close()
