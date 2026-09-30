#!/usr/bin/env python3
"""Build compat.json: supported Kubernetes range per component minor.

    check_compat.py [--components components.json | --projects a,b]
                    [--extra overrides.yaml] [-o compat.json] [--offline]

Sources, in order:
  1. compatibility.fyi data files (raw YAML on GitHub) for projects it covers
  2. data/compat.yaml (curated from official pages)
  3. --extra files you write for anything else (same format as compat.yaml)
When fyi and curated data disagree for a version, the newer lastVerified wins
and the disagreement is listed under "conflicts" so you can check it.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys

import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from _net import DEFAULT_CACHE, fetch  # noqa: E402

SKILL = pathlib.Path(__file__).resolve().parents[1]
FYI_RAW = "https://raw.githubusercontent.com/compatibility-fyi/compatibility.fyi/master/data/{}.yaml"
RANGE_RE = re.compile(r"(>=|<=|<|>|=)?\s*v?(\d+)\.(\d+)")


def parse_range(expr: str) -> list:
    """'>=1.34 <1.37' -> ['1.34', '1.36']; '>=1.25.0' -> ['1.25', None]."""
    lo, hi = None, None
    for op, major, mnr in RANGE_RE.findall(expr):
        major, mnr = int(major), int(mnr)
        if op in (">=", "", "="):
            lo = f"{major}.{mnr}"
            if op == "=":
                hi = lo
        elif op == ">":
            lo = f"{major}.{mnr + 1}"
        elif op == "<":
            hi = f"{major}.{mnr - 1}"
        elif op == "<=":
            hi = f"{major}.{mnr}"
    return [lo, hi]


def fyi_versions(fyi_id: str, cache: pathlib.Path, offline: bool) -> tuple[dict, dict]:
    body, info = fetch(FYI_RAW.format(fyi_id), cache, offline)
    if body is None:
        return {}, info
    try:
        doc = yaml.safe_load(body)
        project = doc["projects"][fyi_id]
    except (yaml.YAMLError, KeyError, TypeError) as exc:
        return {}, dict(info, error=f"unexpected format: {exc}")
    out = {}
    for ver, spec in (project.get("versions") or {}).items():
        dep = ((spec or {}).get("dependencies") or {}).get("kubernetes")
        if not dep or not dep.get("ranges"):
            continue
        lo_hi = parse_range(" ".join(dep["ranges"]))
        sources = dep.get("sources") or []
        out[str(ver)] = {
            "k8s": lo_hi,
            "source": sources[0]["url"] if sources else f"https://compatibility.fyi/projects/{fyi_id}/",
            "lastVerified": str(dep.get("lastVerified") or ""),
            "confidence": dep.get("confidence", "high"),
            "basis": dep.get("basis"),
            "from": "compatibility.fyi",
        }
    return out, info


def merge(catalog: dict, curated: dict, projects: list[str], cache: pathlib.Path, offline: bool) -> dict:
    result = {}
    for pid in projects:
        cat = catalog.get(pid, {})
        cur = curated["projects"].get(pid, {})
        versions = {}
        for ver, spec in (cur.get("versions") or {}).items():
            versions[str(ver)] = {
                "k8s": spec["k8s"],
                "source": spec.get("source", cur.get("source")),
                "lastVerified": str(spec.get("lastVerified", curated.get("lastVerified", ""))),
                "confidence": spec.get("confidence", "high"),
                "from": "curated",
            }
        conflicts, fyi_info = [], None
        if cat.get("fyi"):
            fyi, fyi_info = fyi_versions(cat["fyi"], cache, offline)
            for ver, spec in fyi.items():
                old = versions.get(ver)
                if old and old["k8s"] != spec["k8s"]:
                    conflicts.append({"version": ver, "curated": old["k8s"], "fyi": spec["k8s"]})
                if not old or spec["lastVerified"] >= old["lastVerified"]:
                    versions[ver] = spec
        result[pid] = {
            "rule": cat.get("rule", "any"),
            "noK8sLimit": bool(cat.get("noK8sLimit")),
            "softMin": bool(cur.get("softMin")),
            "matrix": cat.get("matrix") or cur.get("source"),
            "notes": cur.get("notes"),
            "versions": dict(sorted(versions.items(), key=lambda kv: tuple(int(x) for x in kv[0].split(".")))),
            "conflicts": conflicts,
            "fyi": ({"id": cat["fyi"], "source": fyi_info.get("source"), "error": fyi_info.get("error")}
                    if fyi_info else None),
        }
        if not versions and not cat.get("noK8sLimit"):
            result[pid]["missing"] = "no range data; look up the official matrix and add it with --extra"
    return result


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--components", help="components.json from inventory_repo.py")
    ap.add_argument("--projects", help="comma list of catalog ids instead of --components")
    ap.add_argument("--extra", action="append", default=[], help="extra ranges in compat.yaml format")
    ap.add_argument("-o", "--output", default="-")
    ap.add_argument("--offline", action="store_true")
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    args = ap.parse_args()

    catalog = yaml.safe_load(open(SKILL / "data" / "components.yaml"))["components"]
    curated = yaml.safe_load(open(SKILL / "data" / "compat.yaml"))
    for extra in args.extra:
        doc = yaml.safe_load(open(extra)) or {}
        for pid, spec in (doc.get("projects") or {}).items():
            base = curated["projects"].setdefault(pid, {"versions": {}})
            base.update({k: v for k, v in spec.items() if k != "versions"})
            base.setdefault("versions", {}).update(spec.get("versions") or {})
            catalog.setdefault(pid, {"rule": spec.get("rule", "any")})
    if args.components:
        projects = sorted(json.load(open(args.components))["components"])
    elif args.projects:
        projects = [p.strip() for p in args.projects.split(",") if p.strip()]
    else:
        projects = sorted(set(catalog) | set(curated["projects"]))
    if "containerd" not in projects:
        projects.append("containerd")

    result = {"lastVerifiedCurated": curated.get("lastVerified"),
              "projects": merge(catalog, curated, projects, pathlib.Path(args.cache), args.offline)}
    out = sys.stdout if args.output == "-" else open(args.output, "w")
    json.dump(result, out, indent=1)
    out.write("\n")
    for pid, spec in result["projects"].items():
        if spec.get("missing"):
            print(f"warning: {pid}: {spec['missing']}", file=sys.stderr)
        for c in spec["conflicts"]:
            print(f"note: {pid} {c['version']}: curated {c['curated']} vs fyi {c['fyi']}", file=sys.stderr)


if __name__ == "__main__":
    main()
