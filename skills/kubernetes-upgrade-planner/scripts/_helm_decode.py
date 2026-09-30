#!/usr/bin/env python3
"""Read `kubectl get secrets -l owner=helm,status=deployed -o json` on stdin and
print chart metadata for each release. Release payloads (values, manifests) are
decoded in memory only and never written out."""
import base64
import gzip
import json
import sys


def decode(item: dict) -> dict:
    meta = item.get("metadata", {})
    labels = meta.get("labels", {})
    row = {
        "namespace": meta.get("namespace"),
        "release": labels.get("name"),
        "revision": labels.get("version"),
    }
    try:
        raw = base64.b64decode(base64.b64decode(item["data"]["release"]))
        if raw[:2] == b"\x1f\x8b":
            raw = gzip.decompress(raw)
        rel = json.loads(raw)
        chart = rel.get("chart", {}).get("metadata", {})
        row.update(
            chart=chart.get("name"),
            version=chart.get("version"),
            appVersion=chart.get("appVersion"),
            updated=rel.get("info", {}).get("last_deployed"),
        )
    except Exception as exc:  # keep the index row even if decoding fails
        row["error"] = f"{type(exc).__name__}: {exc}"[:200]
    return row


def main() -> None:
    items = json.load(sys.stdin).get("items", [])
    rows = sorted((decode(i) for i in items), key=lambda r: (r["namespace"] or "", r["release"] or ""))
    json.dump(rows, sys.stdout, indent=1)
    sys.stdout.write("\n")


if __name__ == "__main__":
    main()
