#!/usr/bin/env python3
"""Draft findings.json from the collected and computed data.

    draft_findings.py --plan plan.json --components components.json --eol eol.json
                      [--install CLUSTER=install.json ...] [--nodes CLUSTER=nodefacts.json ...]
                      [--apis apis.json] [--compat compat.json] [--title TEXT] [-o findings.json]

The draft fills the version data mechanically: support window, snapshot,
components, hop matrix, sequence, and what to verify. Summary cards and
node-layer rows come from simple rules. Review every row, rewrite the text in
your own words, and add the release notes that match these clusters. Then run
plan_hops.py --validate.
"""
from __future__ import annotations

import argparse
import datetime
import json
import re

K8S_REFS = [
    {"title": "endoflife.date Kubernetes", "url": "https://endoflife.date/kubernetes"},
    {"title": "Version skew policy", "url": "https://kubernetes.io/releases/version-skew-policy/"},
    {"title": "Upgrading kubeadm clusters", "url": "https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/"},
    {"title": "Deprecated API migration guide", "url": "https://kubernetes.io/docs/reference/using-api/deprecation-guide/"},
]
CONTAINERD = {"title": "containerd releases and Kubernetes support", "url": "https://github.com/containerd/containerd/blob/main/RELEASES.md"}
CGROUPS = {"title": "About cgroup v2", "url": "https://kubernetes.io/docs/concepts/architecture/cgroups/"}
PROXY = {"title": "kube-proxy modes", "url": "https://kubernetes.io/docs/reference/networking/virtual-ips/"}
ETCD36 = {"title": "etcd 3.6 upgrade", "url": "https://etcd.io/docs/v3.6/upgrades/upgrade_3_6/"}
CHANGELOG = "https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-{}.md"


def vt(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", str(v))[:3])


def kv_files(items: list[str]) -> dict[str, dict]:
    out = {}
    for item in items:
        name, _, path = item.partition("=")
        out[name] = json.load(open(path))
    return out


def spread(groups: dict) -> str:
    return ", ".join(f"{k} ×{len(v) if isinstance(v, list) else v}" for k, v in groups.items())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", required=True)
    ap.add_argument("--components", required=True)
    ap.add_argument("--eol", required=True)
    ap.add_argument("--install", action="append", default=[])
    ap.add_argument("--nodes", action="append", default=[])
    ap.add_argument("--apis")
    ap.add_argument("--title", default="Kubernetes upgrade plan")
    ap.add_argument("-o", "--output", default="findings.json")
    args = ap.parse_args()

    plan = json.load(open(args.plan))
    comps = json.load(open(args.components))
    eol = json.load(open(args.eol))
    installs = kv_files(args.install)
    nodefacts = kv_files(args.nodes)
    apis = json.load(open(args.apis)) if args.apis else {}
    path, targets = plan["path"], plan["targets"]
    clusters = sorted(plan["clusters"]) or sorted(installs)
    final = path[-1]
    phases = [{"name": f"Phase {i + 1}", "until": t} for i, t in enumerate(targets)]

    # --- support window
    rel = {r["name"]: r for r in (eol.get("kubernetes") or {}).get("releases", [])}
    support = [{"minor": m, "released": rel.get(m, {}).get("releaseDate"), "eol": rel.get(m, {}).get("eolFrom"),
                "latest": rel.get(m, {}).get("latest"), "isEol": rel.get(m, {}).get("isEol")} for m in path]

    # --- snapshot
    def row(item: str, fn) -> dict:
        return {"item": item, "values": {c: fn(installs[c]) for c in clusters if c in installs}}

    snapshot = [
        row("Installer", lambda i: f'{i["installer"]["type"]} ({"; ".join(i["installer"]["evidence"][:2])})'),
        row("API server", lambda i: i.get("serverVersion")),
        row("Kubelets", lambda i: ", ".join(f"{k} ×{v}" for k, v in i.get("kubeletVersions", {}).items())),
        row("Control-plane nodes", lambda i: i["controlPlane"]["nodes"]),
        row("etcd", lambda i: f'{i["etcd"].get("topology")} ×{i["etcd"].get("members", "?")} {i["etcd"].get("version") or ""}'.strip()),
        row("containerd", lambda i: spread(i.get("runtimeByNode", {}))),
        row("OS", lambda i: spread(i.get("osByNode", {}))),
        row("Kernel", lambda i: spread(i.get("kernelByNode", {}))),
        row("kube-proxy", lambda i: f'{i["kubeProxy"].get("mode")} · {i["kubeProxy"].get("version")}'),
        row("CNI", lambda i: " ".join(str(x) for x in (i["cni"].get("name"), i["cni"].get("install"), i["cni"].get("version")) if x)),
        row("CoreDNS", lambda i: f'{i["dns"].get("coredns")} · {i["dns"].get("replicas")} replicas'),
        row("NodeLocal DNS", lambda i: ", ".join(i["dns"].get("nodeLocalDNS") or []) or "none"),
        row("Nodes not ready", lambda i: ", ".join(i["nodes"]["notReady"]) or "none"),
    ]
    if nodefacts:
        snapshot.append({"item": "cgroup v2", "values": {
            c: f'{sum(1 for n in nodefacts[c] if n.get("cgroupV2"))}/{len(nodefacts[c])} nodes' for c in nodefacts}})

    # --- node layer (rule based)
    node_layer, summary, verify = [], [], []
    runtimes = {c: i.get("runtimeByNode", {}) for c, i in installs.items()}
    old_ctr = {c: [k for k in r if re.search(r"containerd://1\.", k)] for c, r in runtimes.items()}
    if any(old_ctr.values()) and vt(final) >= (1, 36):
        node_layer.append({"item": "containerd", "severity": "blocker", "neededBy": "before 1.36",
                           "current": "; ".join(f"{c}: {spread(runtimes[c])}" for c in runtimes),
                           "problem": "Kubernetes 1.36 does not support containerd 1.x; 1.35 is the last release that does.",
                           "action": "Hold the package, then move nodes to containerd 2.x (config version 3, certs.d mirrors, new sandbox image key) at the 1.34 or 1.35 stage.",
                           "refs": [CONTAINERD]})
        summary.append({"severity": "blocker", "title": "containerd 1.x on nodes", "text": "Nodes run containerd 1.x, which 1.36 does not support."})
    for c, r in runtimes.items():
        if len(r) > 1:
            verify.append(f"{c}: containerd versions differ across nodes ({', '.join(r)}); compare config.toml between them.")
    ipvs = [c for c, i in installs.items() if str(i["kubeProxy"].get("mode", "")).startswith("ipvs")]
    if ipvs and vt(final) >= (1, 35):
        node_layer.append({"item": "kube-proxy IPVS", "severity": "required", "neededBy": "before 1.37",
                           "current": f'ipvs on {", ".join(ipvs)}',
                           "problem": "IPVS mode is deprecated in 1.35 and being removed.",
                           "action": "Move to iptables (or nftables with kernel 5.13+). Re-test NodeLocal DNS, which is set up differently per mode.",
                           "refs": [PROXY]})
    if nodefacts:
        v1 = {c: [n["host"] for n in nf if not n.get("cgroupV2")] for c, nf in nodefacts.items()}
        if any(v1.values()) and vt(final) >= (1, 35):
            node_layer.append({"item": "cgroup v1 nodes", "severity": "blocker", "neededBy": "before 1.35",
                               "current": "; ".join(f"{c}: {', '.join(h)}" for c, h in v1.items() if h),
                               "problem": "From 1.35 kubelet refuses to start on cgroup v1.",
                               "action": "Switch these nodes to cgroup v2 before the 1.35 hop.", "refs": [CGROUPS]})
    elif vt(final) >= (1, 35):
        verify.append("cgroup version on every node (run node_facts.sh); kubelet 1.35 refuses cgroup v1.")
    for c, i in installs.items():
        etcd = i.get("etcd", {})
        if etcd.get("topology") == "external" and vt(final) >= (1, 34):
            node_layer.append({"item": f"etcd ({c}, external)", "severity": "required", "neededBy": "before 1.36",
                               "current": f'external ×{etcd.get("members")}, version unknown',
                               "problem": "kubeadm does not upgrade external etcd, and kubeadm 1.36 drops etcd below 3.6.",
                               "action": "Upgrade etcd to 3.5.20+ and then 3.6 through the installer before 1.36. Snapshot first; there is no downgrade.",
                               "refs": [ETCD36]})
        elif etcd.get("topology") == "stacked" and vt(final) >= (1, 34):
            node_layer.append({"item": f"etcd ({c}, stacked)", "severity": "recommended", "neededBy": "1.34 hop",
                               "current": f'stacked ×{etcd.get("members")} {etcd.get("version") or ""}',
                               "problem": "kubeadm 1.34 moves stacked etcd to 3.6, with no downgrade.",
                               "action": "Take an etcd snapshot and back up /etc/kubernetes before the 1.34 hop.", "refs": [ETCD36]})
        if i["installer"]["type"] == "kubeadm":
            node_layer.append({"item": f"kubelet config ({c})", "severity": "required", "neededBy": "every hop",
                               "current": "kube-system/kubelet-config ConfigMap", "problem": "kubeadm upgrade node rewrites /var/lib/kubelet/config.yaml from the ConfigMap, dropping per-node settings applied after join.",
                               "action": "Compare a node's config.yaml with the ConfigMap; put custom settings into the ConfigMap or re-apply them after each hop.",
                               "refs": [{"title": "Reconfiguring a kubeadm cluster", "url": "https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-reconfigure/"}]})
        if i["installer"]["type"] == "kubespray":
            verify.append(f"{c}: the Kubespray version and inventory last used, and who runs it.")
        if i["nodes"]["notReady"]:
            summary.append({"severity": "required", "title": f"{c}: nodes not ready",
                            "text": f'{", ".join(i["nodes"]["notReady"])} must be fixed or removed before upgrading.'})
        verify += [f"{c}: {u}" for u in i.get("unknowns", []) if "cgroup" not in u]

    for hit in apis.get("removedApis", []):
        node_layer.append({"item": f"API {hit['api']}", "severity": "required", "neededBy": f"removed in {hit['removedIn']}",
                           "current": f"{hit['count']} uses in {hit['fileCount']} files, e.g. {hit['files'][0]}",
                           "problem": f"Removed in {hit['removedIn']}. Check whether the files are rendered (templates may be disabled).",
                           "action": f"Move to {hit['replacement']}.", "refs": [K8S_REFS[3]]})
    for hit in apis.get("patterns", []):
        node_layer.append({"item": f"Pattern: {hit['id']}", "severity": hit["severity"], "neededBy": f"since {hit['since']}",
                           "current": f"{hit['count']} matches in {hit['fileCount']} files, e.g. {hit['files'][0]}",
                           "problem": hit["text"], "action": "Review the matches and update them.", "refs": [K8S_REFS[3]]})

    # --- components
    components = []
    for pid in sorted({p for c in plan["clusters"].values() for p in c}):
        per = {c: plan["clusters"][c].get(pid) for c in clusters if plan["clusters"][c].get(pid)}
        any_res = next(iter(per.values()))
        targets_by_phase = {}
        for ph in phases:
            versions = set()
            for res in per.values():
                v = res.get("key") or res.get("current")
                for s in res["steps"]:
                    if vt(s["at"]) <= vt(ph["until"]) or (vt(s["at"]) == vt(ph["until"])):
                        v = s["to"]
                versions.add(str(v) if v else "—")
            targets_by_phase[ph["name"]] = " / ".join(sorted(versions))
        statuses = {r["status"] for r in per.values()}
        early = any(vt(s["at"]) <= vt(targets[0]) for r in per.values() for s in r["steps"])
        severity = ("blocker" if "blocked" in statuses else "required" if early
                    else "recommended" if "upgrade" in statuses or "missing-data" in statuses else "ok")
        notes = []
        for r in per.values():
            notes += [g["text"] for g in r["gaps"]] + [f'{s["at"]}: {s["reason"]}' for s in r["steps"]] + r["notes"]
            if r["status"] == "missing-data":
                notes.append("no compatibility data; look up the official matrix")
        refs = [{"title": f"{pid} compatibility", "url": any_res.get("matrix")}] if any_res.get("matrix") else []
        components.append({"id": pid, "name": pid, "severity": severity,
                           "current": {c: r.get("current") for c, r in per.items()},
                           "targets": targets_by_phase, "notes": "; ".join(dict.fromkeys(notes)), "refs": refs})
        if "missing-data" in statuses:
            verify.append(f"{pid}: no compatibility range data; add it with check_compat.py --extra.")
        low = [s for r in per.values() for s in r["steps"] if s.get("confidence") in ("low", "medium")]
        if low:
            verify.append(f"{pid}: plan uses {low[0]['confidence']}-confidence ranges ({low[0]['to']}); confirm on the official page.")
        if "blocked" in statuses:
            summary.append({"severity": "blocker", "title": f"{pid} has no supported version for the path",
                            "text": next(g["text"] for r in per.values() for g in r["gaps"])})

    for stop in plan.get("eolStops", []):
        if stop.get("isTarget"):
            summary.insert(0, {"severity": "blocker", "title": f"{stop['minor']} is already end of life",
                               "text": f"Support ended {stop['eolFrom']}. Treat it as a stop along the way, not a destination."})

    matrix = {"hops": plan["matrix"]["hops"],
              "rows": [dict(r, id=r["component"]) for r in plan["matrix"]["rows"] if r["steps"] or r["status"] != "ok"]}

    # --- sequence from plan steps
    sequence = []
    for m in path:
        items = []
        for pid in sorted({p for c in plan["clusters"].values() for p in c}):
            for c in clusters:
                for s in (plan["clusters"][c].get(pid) or {}).get("steps", []):
                    if s["at"] == m:
                        items.append(f'{pid} ({c}): {" → ".join([s["from"]] + s["via"])} (possible from {s["earliest"]})')
        nxt = path[path.index(m) + 1] if m != final else None
        title = f"On {m}, before the hop to {nxt}" if nxt else f"On {m} (final)"
        sequence.append({"title": title, "items": sorted(set(items)) + ([f"Hop: upgrade the control plane and nodes to {nxt}"] if nxt else [])})

    release_notes = [{"minor": m, "src": CHANGELOG.format(m), "hot": [], "items": []} for m in path[1:]]
    verify.append("Release notes: fill releaseNotes with only the changelog items that match what was collected.")

    findings = {
        "meta": {"title": args.title, "date": datetime.date.today().isoformat(), "clusters": clusters,
                 "path": path, "phases": phases,
                 "facts": [f'{c} {installs[c].get("serverVersion")} ({installs[c]["installer"]["type"]})' for c in clusters if c in installs]},
        "summary": summary, "snapshot": snapshot, "support": support, "nodeLayer": node_layer,
        "components": components, "matrix": matrix, "releaseNotes": release_notes, "sequence": sequence,
        "verify": list(dict.fromkeys(verify)),
        "references": [{"group": "Kubernetes", "items": K8S_REFS + [CONTAINERD, CGROUPS]},
                       {"group": "Components", "items": [r for c in components for r in c["refs"]]}],
    }
    with open(args.output, "w") as fh:
        json.dump(findings, fh, indent=1)
        fh.write("\n")
    print(f"wrote {args.output}: {len(components)} components, {len(node_layer)} node-layer rows, {len(verify)} items to verify")


if __name__ == "__main__":
    main()
