#!/usr/bin/env python3
"""Plan per-hop component versions for a multi-minor Kubernetes upgrade.

    plan_hops.py --from 1.31 --to 1.33 [--to 1.36]
                 --components components.json --compat compat.json [--eol eol.json]
                 [-o plan.json]
    plan_hops.py --validate findings.json --compat compat.json

Planning: the cluster moves one minor per hop. Before each hop every component
must support the minor it runs on now *and* the next one. When it doesn't, the
planner picks a bridge version: the version reachable without a downgrade that
supports both minors and covers the most future minors, expanded through the
project's upgrade-path rule (one minor at a time, n-2, next major). A component
whose current minor is end of life (per eol.json) moves at the first hop.

Every step carries a window: `earliest` is the first cluster minor on which the
target version is supported, `latest` is the minor the cluster is on when the
step becomes mandatory.
"""
from __future__ import annotations

import argparse
import json
import re
import sys

EOL_ALIASES = {"argocd": "argo-cd"}


# ----------------------------------------------------------------- versions
def vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:3])


def minor_str(v: str) -> str:
    parts = vt(v)
    return f"{parts[0]}.{parts[1]}" if len(parts) > 1 else str(parts[0])


def k8s_path(start: str, end: str) -> list[str]:
    major, lo = vt(start)[:2]
    _, hi = vt(end)[:2]
    if hi < lo:
        raise SystemExit(f"target {end} is older than {start}")
    return [f"{major}.{m}" for m in range(lo, hi + 1)]


def supports(rng: list, k: str, soft_min: bool) -> bool:
    lo, hi = rng
    if lo and not soft_min and vt(k) < vt(lo):
        return False
    return hi is None or vt(k) <= vt(hi)


def key_for(current: str, keys: list[str]) -> tuple[str | None, str | None]:
    """Map a running version (1.17.4) to a compat key (1.17); floor if missing."""
    if not keys:
        return None, None
    want = minor_str(current)
    if want in keys:
        return want, None
    lower = [k for k in keys if vt(k) <= vt(want)]
    if lower:
        return lower[-1], f"no range for {want}; using {lower[-1]}"
    return keys[0], f"{want} is older than all known ranges; using {keys[0]}"


# ------------------------------------------------------------------ planner
def expand(frm: str, to: str, keys: list[str], rule) -> tuple[list[str], list[str]]:
    """Versions to pass through from `frm` to `to` under the upgrade rule."""
    notes: list[str] = []
    if rule == "any" or not isinstance(rule, dict):
        return [to], notes
    ordered = [k for k in keys if vt(frm) < vt(k) <= vt(to)]
    path, cur = [], frm
    while vt(cur) < vt(to):
        if "maxMajorStep" in rule:
            limit = vt(cur)[0] + rule["maxMajorStep"]
            nxt = max((k for k in ordered if vt(k) > vt(cur) and vt(k)[0] <= limit), key=vt, default=None)
        else:
            step = rule.get("maxMinorStep", 1)
            same_major = [k for k in ordered if vt(k) > vt(cur) and vt(k)[0] == vt(cur)[0]
                          and vt(k)[1] - vt(cur)[1] <= step]
            nxt = max(same_major, key=vt, default=None)
            if nxt is None:
                nxt = next((k for k in ordered if vt(k) > vt(cur)), None)
                if nxt and vt(nxt)[0] == vt(cur)[0]:
                    notes.append(f"no range data between {cur} and {nxt}; check intermediate releases")
        if nxt is None:
            break
        path.append(nxt)
        cur = nxt
    return path, notes


def coverage(rng: list) -> tuple[int, ...]:
    return vt(rng[1] or "999.999")


def plan_component(pid: str, current: str | None, spec: dict, path: list[str], eol_minors: set[str],
                   strategy: str = "lazy") -> dict:
    versions = spec.get("versions") or {}
    keys = sorted(versions, key=vt)
    soft = spec.get("softMin", False)
    rule = spec.get("rule", "any")
    out = {"id": pid, "current": current, "rule": rule, "matrix": spec.get("matrix"),
           "steps": [], "gaps": [], "notes": []}
    if spec.get("notes"):
        out["notes"].append(spec["notes"])
    if not current:
        out["status"] = "unknown-version"
        return out
    if not keys:
        out["status"] = "no-k8s-limit" if spec.get("noK8sLimit") else "missing-data"
        return out
    key, note = key_for(current, keys)
    if note:
        out["notes"].append(note)
    out["key"] = key
    rng = lambda v: versions[v]["k8s"]  # noqa: E731

    def best(need: list[str], floor: str, avoid_eol: bool) -> str | None:
        cands = [k for k in keys if vt(k) >= vt(floor) and all(supports(rng(k), n, soft) for n in need)
                 and not (avoid_eol and k in eol_minors)]
        if not cands:
            return None
        # widest future coverage first, then the lowest version (fewest changes)
        return min(cands, key=lambda k: (tuple(-x for x in coverage(rng(k))), vt(k)))

    def step_record(frm: str, to: str, via: list[str], k: str, reason: str) -> dict:
        transient = [v for v in via[:-1] if not supports(rng(v), k, soft)]
        lo = rng(to)[0]
        rec = {
            "from": frm, "to": to, "via": via, "at": k,
            "earliest": path[0] if soft or not lo or vt(lo) <= vt(path[0]) else lo, "latest": k,
            "reason": reason, "eol": to in eol_minors,
            "source": versions[to].get("source"), "lastVerified": versions[to].get("lastVerified"),
            "confidence": versions[to].get("confidence"),
        }
        if transient:
            rec["transient"] = f"{', '.join(transient)} outside tested range at {k}; pass through quickly"
        return rec

    cur = key
    for i, k in enumerate(path):
        need = path[i:i + 2]
        ok = all(supports(rng(cur), n, soft) for n in need)
        forced_eol = i == 0 and cur in eol_minors
        if ok and strategy == "eager":
            # move as soon as a version with wider coverage can be installed
            target = best(need, cur, True) or best(need, cur, False)
            if target and coverage(rng(target)) > coverage(rng(cur)):
                via, notes = expand(cur, target, keys, rule)
                out["notes"] += notes
                out["steps"].append(step_record(cur, target, via, k, "eager: wider support available"))
                cur = target
            continue
        if ok and not forced_eol:
            continue
        if ok:  # supported but end of life: move only to a non-EOL version
            target = best(need, cur, True)
            if not target or target == cur:
                out["notes"].append(f"{cur} is end of life and no supported non-EOL version fits {k}")
                continue
            reason = "current version is end of life"
        else:
            target = best(need, cur, True) or best(need, cur, False)
            reason = f"{cur} does not support {need[-1] if len(need) > 1 else k}"
            if target is None:
                if len(need) > 1 and supports(rng(cur), need[-1], soft):
                    out["notes"].append(f"{cur} is already outside its tested range on {k}; no newer version covers {k}")
                elif not any(g["next"] == need[-1] for g in out["gaps"]):
                    out["gaps"].append({"at": k, "next": need[-1],
                                        "text": f"no known {pid} version supports both {' and '.join(need)}"
                                        if len(need) > 1 else f"no known {pid} version supports {k}"})
                continue
        if target == cur:
            continue
        via, notes = expand(cur, target, keys, rule)
        out["notes"] += notes
        out["steps"].append(step_record(cur, target, via, k, reason))
        cur = target
    out["final"] = cur
    newest = [kk for kk in keys if supports(rng(kk), path[-1], soft)]
    if newest and vt(newest[-1]) > vt(cur):
        out["newestForFinal"] = newest[-1]
    out["status"] = "blocked" if out["gaps"] else ("upgrade" if out["steps"] else "ok")
    return out


def eol_sets(eol: dict) -> tuple[list[dict], dict[str, set[str]]]:
    k8s = {r["name"]: r for r in (eol.get("kubernetes") or {}).get("releases", [])}
    per_product = {name: {r["name"] for r in data.get("releases", []) if r.get("isEol")}
                   for name, data in eol.items() if isinstance(data, dict)}
    return k8s, per_product


def build_plan(start: str, targets: list[str], components: dict, compat: dict, eol: dict,
               strategy: str = "lazy") -> dict:
    path = k8s_path(start, targets[-1])
    k8s_rel, eol_by_product = eol_sets(eol)
    plan = {"path": path, "targets": targets, "strategy": strategy, "clusters": {}, "eolStops": []}
    for k in path:
        rel = k8s_rel.get(k)
        if rel and rel.get("isEol"):
            plan["eolStops"].append({"minor": k, "eolFrom": rel.get("eolFrom"), "isTarget": k in targets})
    projects = compat.get("projects", {})
    for pid, per_cluster in sorted(components.items()):
        spec = projects.get(pid, {})
        eol_minors = eol_by_product.get(EOL_ALIASES.get(pid, pid), set())
        for cluster, slot in per_cluster.items():
            if cluster == "*":
                continue
            result = plan_component(pid, slot.get("version"), spec, path, eol_minors, strategy)
            plan["clusters"].setdefault(cluster, {})[pid] = result
    plan["matrix"] = matrix(plan)
    return plan


def matrix(plan: dict) -> dict:
    """One row per component; clusters with identical plans share a row."""
    rows: dict[str, dict] = {}
    for cluster, comps in sorted(plan["clusters"].items()):
        for pid, res in comps.items():
            steps = {s["at"]: " → ".join([s["from"]] + s["via"]) for s in res["steps"]}
            for gap in res["gaps"]:
                steps[gap["at"]] = "GAP: " + gap["text"]
            sig = json.dumps([pid, res.get("current"), steps, res.get("status")], sort_keys=True)
            row = rows.setdefault(sig, {"component": pid, "clusters": [], "current": res.get("current"),
                                        "status": res.get("status"), "steps": steps, "final": res.get("final"),
                                        "newestForFinal": res.get("newestForFinal"), "rule": res.get("rule"),
                                        "refs": [{"title": f"{pid} compatibility", "url": res.get("matrix")}]
                                        if res.get("matrix") else []})
            row["clusters"].append(cluster)
    return {"hops": plan["path"], "rows": sorted(rows.values(), key=lambda r: (r["component"], r["clusters"]))}


def print_table(plan: dict) -> None:
    hops = plan["path"]
    print("component".ljust(26) + "".join(h.ljust(22) for h in hops) + "final", file=sys.stderr)
    for row in plan["matrix"]["rows"]:
        name = f'{row["component"]} ({",".join(row["clusters"])})'[:25]
        cells = [(row["steps"].get(h) or "")[:21] for h in hops]
        print(name.ljust(26) + "".join(c.ljust(22) for c in cells) + str(row.get("final") or row["status"]),
              file=sys.stderr)
    for stop in plan["eolStops"]:
        print(f'EOL: {stop["minor"]} ended {stop["eolFrom"]}' + (" (a target!)" if stop["isTarget"] else ""),
              file=sys.stderr)


# --------------------------------------------------------------- validation
def validate(findings: dict, compat: dict) -> list[str]:
    errors: list[str] = []
    meta = findings.get("meta") or {}
    path = meta.get("path") or []
    if len(path) < 2:
        errors.append("meta.path needs at least two minors")
    for a, b in zip(path, path[1:]):
        if vt(b)[:2] != (vt(a)[0], vt(a)[1] + 1):
            errors.append(f"meta.path skips a minor: {a} -> {b}")
    if not re.match(r"\d{4}-\d{2}-\d{2}$", str(meta.get("date", ""))):
        errors.append("meta.date must be YYYY-MM-DD")
    for section in ("components", "nodeLayer"):
        for i, row in enumerate(findings.get(section) or []):
            label = row.get("name") or row.get("item") or f"#{i}"
            if not row.get("refs"):
                errors.append(f"{section}[{label}] has no refs (every claim needs a source)")
            for ref in row.get("refs") or []:
                if not str(ref.get("url", "")).startswith("http"):
                    errors.append(f"{section}[{label}] ref without http(s) url: {ref}")
    projects = compat.get("projects", {})
    for row in (findings.get("matrix") or {}).get("rows", []):
        pid = row.get("id") or row.get("component")
        if not row.get("refs"):
            errors.append(f"matrix[{pid}] has no refs")
        spec = projects.get(pid)
        if not spec or not spec.get("versions"):
            continue
        keys = sorted(spec["versions"], key=vt)
        for minor, text in (row.get("steps") or {}).items():
            if str(text).startswith("GAP") or not text:
                continue
            found = re.findall(r"\d+\.\d+(?:\.\d+)?", str(text))
            if not found:
                continue
            key, _ = key_for(found[-1], keys)
            rng = spec["versions"][key]["k8s"]
            if not supports(rng, minor, spec.get("softMin", False)):
                errors.append(f"matrix[{pid}] at {minor}: {found[-1]} supports {rng}, not {minor}")
    first = path[0] if path else None
    for row in findings.get("components") or []:
        pid = row.get("id")
        spec = projects.get(pid or "")
        if row.get("severity") != "ok" or not spec or not spec.get("versions") or not first:
            continue
        for cluster, ver in (row.get("current") or {}).items():
            key, _ = key_for(str(ver), sorted(spec["versions"], key=vt))
            if key and not supports(spec["versions"][key]["k8s"], first, spec.get("softMin", False)):
                errors.append(f"components[{pid}] marked ok but {ver} on {cluster} does not support {first}")
    return errors


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", action="append", default=[], help="phase target minor (repeatable, ascending)")
    ap.add_argument("--components")
    ap.add_argument("--compat", required=True)
    ap.add_argument("--eol")
    ap.add_argument("--strategy", choices=["lazy", "eager"], default="lazy",
                    help="lazy: upgrade just before a hop needs it; eager: as soon as wider support is available")
    ap.add_argument("--validate", metavar="FINDINGS")
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()
    compat = json.load(open(args.compat))

    if args.validate:
        errors = validate(json.load(open(args.validate)), compat)
        for e in errors:
            print(f"error: {e}")
        print("valid" if not errors else f"{len(errors)} error(s)")
        sys.exit(1 if errors else 0)

    if not (args.start and args.to and args.components):
        ap.error("--from, --to and --components are required unless --validate")
    comps = json.load(open(args.components))["components"]
    eol = json.load(open(args.eol)) if args.eol else {}
    plan = build_plan(minor_str(args.start), [minor_str(t) for t in args.to], comps, compat, eol, args.strategy)
    print_table(plan)
    out = sys.stdout if args.output == "-" else open(args.output, "w")
    json.dump(plan, out, indent=1)
    out.write("\n")


if __name__ == "__main__":
    main()
