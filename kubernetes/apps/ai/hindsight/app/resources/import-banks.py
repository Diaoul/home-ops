"""Import every bank template in /banks into Hindsight once it is healthy, then idle."""

import json
import os
import pathlib
import signal
import time
import urllib.request

URL = "http://localhost:8888"
HEADERS = {
    "Authorization": f"Bearer {os.environ['HINDSIGHT_API_TENANT_API_KEY']}",
    "Content-Type": "application/json",
}

while True:
    try:
        urllib.request.urlopen(f"{URL}/health", timeout=5)
        break
    except OSError:
        time.sleep(5)

for manifest in sorted(pathlib.Path("/banks").glob("*.json")):
    request = urllib.request.Request(
        f"{URL}/v1/default/banks/{manifest.stem}/import",
        data=manifest.read_bytes(),
        headers=HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        print(f"{manifest.stem}: {response.read().decode()}", flush=True)

# Kubernetes restarts a sidecar that exits, so exit only on failure, to retry.
signal.pause()
