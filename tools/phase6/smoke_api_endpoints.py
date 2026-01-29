import json
import urllib.request

BASE = "http://localhost:5000"

for path in ["/api/health", "/api/version", "/api/ops/stats"]:
    url = BASE + path
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            data = resp.read().decode("utf-8")
            print(path, data)
    except Exception as exc:
        print(path, "FAILED", exc)
