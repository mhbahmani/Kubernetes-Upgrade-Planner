#!/usr/bin/env python3
"""Redact a collected data directory in place before sharing.

Replaces IPv4 addresses and node names with stable placeholders (the same
input always maps to the same placeholder, so files stay consistent), and drops
lines that look like credentials.

    redact.py OUT_DIR [--domain example.com ...]

--domain also replaces host names under that domain (api.k8s.example.com ->
host-1a2b3c). REDACT_DOMAINS (comma separated) does the same.
"""
import argparse
import os
import hashlib
import json
import pathlib
import re

IPV4 = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)(?:/\d{1,2})?\b")
SECRETISH = re.compile(r"(?i)(token|password|passwd|secret|client[-_]?secret|api[-_]?key|bearer)\s*[:=]\s*\S+")


def tag(prefix: str, value: str) -> str:
    return f"{prefix}-{hashlib.sha256(value.encode()).hexdigest()[:6]}"


def redact_text(text: str, names: list[str], domains: list[str] = ()) -> str:
    text = IPV4.sub(lambda m: tag("ip", m.group(0)), text)
    for domain in domains:
        pattern = rf"\b(?:[A-Za-z0-9-]+\.)*{re.escape(domain)}\b"
        text = re.sub(pattern, lambda m: tag("host", m.group(0)), text)
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(rf"\b{re.escape(name)}\b", tag("node", name), text)
    return SECRETISH.sub(lambda m: f"{m.group(1)}: <redacted>", text)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("out")
    ap.add_argument("--domain", action="append", default=[])
    args = ap.parse_args()
    domains = args.domain + [d for d in os.environ.get("REDACT_DOMAINS", "").split(",") if d]
    out = pathlib.Path(args.out)
    names: list[str] = []
    nodes = out / "nodes.json"
    if nodes.exists():
        try:
            names = [n["name"] for n in json.loads(nodes.read_text())]
        except (ValueError, KeyError, TypeError):
            pass
    count = 0
    for path in sorted(out.rglob("*")):
        if path.is_file() and path.suffix in {".json", ".yaml", ".txt", ".tsv"}:
            path.write_text(redact_text(path.read_text(errors="replace"), names, domains))
            count += 1
    print(f"redacted {count} files in {out}")


if __name__ == "__main__":
    main()
