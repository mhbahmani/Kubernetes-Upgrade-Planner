#!/usr/bin/env python3
"""Find removed Kubernetes APIs and deprecated patterns in repos.

    scan_apis.py --repo PATH [--repo PATH ...] --target 1.36 [-o apis.json] [--no-pluto]

Checks every apiVersion string against data/removed-apis.yaml (removed at or
before the target) and greps for deprecated patterns (gitRepo volumes, IPVS,
Endpoints, AppArmor annotations, ...). If `pluto` is on PATH its
detect-files result is added under "pluto".
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

import yaml

SKILL = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / "scripts"))
from inventory_repo import API_RE, TEXT_EXT, walk  # noqa: E402

SCAN_NAMES = {"Makefile", ".gitlab-ci.yml"}


def minor(v: str) -> tuple[int, int]:
    major, mnr = v.lstrip("v").split(".")[:2]
    return int(major), int(mnr)


def scan(repos: list[pathlib.Path], target: str, rules: dict) -> dict:
    tgt = minor(target)
    removed = rules["removed"]
    patterns = [dict(p, rx=re.compile(p["regex"], re.M)) for p in rules["patterns"]]
    api_hits: dict[str, dict] = {}
    pattern_hits: dict[str, dict] = {}
    for root in repos:
        for path in walk(root):
            if path.suffix.lower() not in TEXT_EXT | {".sh", ".toml", ".ini", ".cfg"} and path.name not in SCAN_NAMES:
                continue
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            rel = f"{root.name}/{path.relative_to(root)}"
            for m in API_RE.finditer(text):
                api = m.group(1)
                info = removed.get(api)
                if info and minor(info["removedIn"]) <= tgt:
                    hit = api_hits.setdefault(api, dict(info, api=api, count=0, files=[]))
                    hit["count"] += 1
                    if rel not in hit["files"]:
                        hit["files"].append(rel)
            for p in patterns:
                if minor(p["since"]) > tgt:
                    continue
                n = len(p["rx"].findall(text))
                if n:
                    hit = pattern_hits.setdefault(p["id"], {k: p[k] for k in ("id", "since", "severity", "text")} | {"count": 0, "files": []})
                    hit["count"] += n
                    if rel not in hit["files"]:
                        hit["files"].append(rel)
    for hit in list(api_hits.values()) + list(pattern_hits.values()):
        hit["fileCount"] = len(hit["files"])
        hit["files"] = hit["files"][:10]
    return {
        "target": target,
        "source": rules.get("source"),
        "removedApis": sorted(api_hits.values(), key=lambda h: h["removedIn"]),
        "patterns": sorted(pattern_hits.values(), key=lambda h: h["id"]),
    }


def run_pluto(repos: list[pathlib.Path], target: str) -> list | str:
    out = []
    for root in repos:
        try:
            proc = subprocess.run(
                ["pluto", "detect-files", "-d", str(root), "-o", "json", "--target-versions", f"k8s=v{target}.0"],
                capture_output=True, text=True, timeout=300)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return f"pluto failed: {exc}"
        try:
            out += json.loads(proc.stdout or "{}").get("items", []) or []
        except ValueError:
            return f"pluto output not JSON: {proc.stderr.strip()[:200]}"
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", action="append", required=True)
    ap.add_argument("--target", required=True, help="final Kubernetes minor, e.g. 1.36")
    ap.add_argument("--rules", default=str(SKILL / "data" / "removed-apis.yaml"))
    ap.add_argument("--no-pluto", action="store_true")
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()
    repos = [pathlib.Path(r).expanduser().resolve() for r in args.repo]
    result = scan(repos, args.target, yaml.safe_load(open(args.rules)))
    if not args.no_pluto and shutil.which("pluto"):
        result["pluto"] = run_pluto(repos, args.target)
    else:
        result["pluto"] = "not run (pluto not installed or --no-pluto)"
    out = sys.stdout if args.output == "-" else open(args.output, "w")
    json.dump(result, out, indent=1)
    out.write("\n")


if __name__ == "__main__":
    main()
