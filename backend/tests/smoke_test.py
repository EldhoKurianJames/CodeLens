"""
Manual smoke-check script — NOT part of the automated pytest suite
(excluded via pytest.ini) because it makes real HTTP calls against a
locally running server at import time. Run it directly:

    python tests/smoke_test.py

If the server was started with API_KEY set, export the same value as
API_KEY in this shell first so the requests below are authenticated.
"""

import os

import httpx, json

BASE = "http://127.0.0.1:8000"
HEADERS = {}
if os.environ.get("API_KEY", "").strip():
    HEADERS["X-API-Key"] = os.environ["API_KEY"]

def post(code, label):
    r = httpx.post(
        f"{BASE}/api/v1/analyze",
        json={
            "code": code,
            "cache_config": {"size_bytes": 512, "block_size_bytes": 64, "associativity": 2},
        },
        headers=HEADERS,
        timeout=10,
    )
    d = r.json()
    cs = d.get("cache_stats", {})
    meta = d.get("metadata", {})
    hr = cs.get("hit_rate", 0) * 100
    print(f"--- {label} [{r.status_code}] ---")
    print(f"  hit_rate={hr:.2f}%  total={cs.get('total_accesses')}  mode={d.get('analysis_mode')}")
    print(f"  access_order={meta.get('access_order')}  efficiency={meta.get('cache_efficiency')}")
    print(f"  issues={meta.get('issues')}")
    print()

post(
    "arr = [[0]*64 for _ in range(64)]\nfor i in range(64):\n    for j in range(64):\n        arr[i][j] = i+j",
    "row-major",
)
post(
    "arr = [[0]*64 for _ in range(64)]\nfor j in range(64):\n    for i in range(64):\n        arr[i][j] = i+j",
    "col-major",
)
post(
    "arr = [0]*512\nfor i in range(0, 512, 16):\n    arr[i] = i",
    "stride-16",
)

r_bad = httpx.post(
    f"{BASE}/api/v1/analyze",
    json={"code": "import os\nprint(os.getcwd())", "cache_config": {"size_bytes": 512, "block_size_bytes": 64, "associativity": 2}},
    headers=HEADERS,
    timeout=10,
)
print(f"--- invalid code [{r_bad.status_code}] ---")
print(json.dumps(r_bad.json(), indent=2))
print()

r_gallery = httpx.get(f"{BASE}/api/v1/gallery", headers=HEADERS, timeout=10)
gallery = r_gallery.json()
print(f"--- gallery [{r_gallery.status_code}] --- {len(gallery)} entries")
for entry in gallery:
    print(f"  {entry['id']}: {entry['title']}")
    for v in entry["variants"]:
        hr = v["cache_stats"]["hit_rate"] * 100
        print(f"    {v['label']:40s}  hit={hr:.1f}%")
