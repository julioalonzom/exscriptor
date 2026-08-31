#!/usr/bin/env python3
"""Print the FULL batch JSON (errors included).

Usage: python3 -m exscriptor.batch_raw <batch_id>
"""
import json
import sys
import urllib.request

from exscriptor.credentials import credential


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    key = credential("OPENROUTER_API_KEY")
    batch_id = sys.argv[1]
    req = urllib.request.Request(
        f"https://openrouter.ai/api/v1/batches/{batch_id}",
        headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req) as r:
        print(json.dumps(json.load(r), indent=2))


if __name__ == "__main__":
    main()
