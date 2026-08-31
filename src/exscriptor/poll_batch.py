#!/usr/bin/env python3
"""Poll an OpenRouter batch by id; print status until done or wait elapses.

Usage: python3 -m exscriptor.poll_batch <batch_id> [wait_s]
"""
import json
import sys
import time
import urllib.request

from exscriptor.credentials import credential

key = credential("OPENROUTER_API_KEY")


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    batch_id = sys.argv[1]
    wait_s = int(sys.argv[2]) if len(sys.argv) > 2 else 0
    deadline = time.time() + wait_s
    while True:
        req = urllib.request.Request(
            f"https://openrouter.ai/api/v1/batches/{batch_id}",
            headers={"Authorization": f"Bearer {key}"})
        with urllib.request.urlopen(req) as r:
            d = json.load(r)
        data = d.get("data", d)
        print(data.get("status"), "| ended?:", data.get("ended_at"))
        if data.get("status") in ("completed", "failed", "expired", "cancelled"):
            break
        if time.time() >= deadline:
            break
        time.sleep(20)


if __name__ == "__main__":
    main()
