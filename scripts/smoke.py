"""Verify running HTTP services with the Python standard library."""

import json
import os
from urllib.request import urlopen

api = "http://127.0.0.1:" + os.environ.get("API_PORT", "8000")
frontend = "http://127.0.0.1:" + os.environ.get("FRONTEND_PORT", "5173")
for base in (api, frontend):
    for path in ("/health/live", "/health/ready"):
        with urlopen(base + path, timeout=10) as response:
            payload = json.load(response)
            assert response.status == 200 and payload["status"] == "ok", payload
            if path.endswith("ready"):
                assert payload["dependencies"] == {"postgres": "ok", "redis": "ok"}
with urlopen(frontend, timeout=10) as response:
    assert b"Logistics Platform" in response.read()
print("HTTP smoke passed: frontend, API, PostgreSQL/Redis readiness, Vite proxy")
