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

# A sidecar that exits is restarted; exiting only on failure retries the import.
signal.pause()
