#!/usr/bin/env python3
"""Classify how a cluster was installed from a collect_cluster.sh directory.

    detect_install.py CLUSTER_DIR > install.json

Reports installer (kubeadm, kubespray, managed, k3s, rke2), etcd topology, CNI
and how it is installed, kube-proxy mode, CoreDNS / NodeLocal DNS, runtime,
OS and kernel spread, API server auth flags, and node health. Anything it
cannot decide goes to "unknowns" instead of being guessed.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

import yaml


def load_json(d: pathlib.Path, name: str, default=None):
    try:
        return json.loads((d / name).read_text())
    except (OSError, ValueError):
        return default


def load_cm(d: pathlib.Path, name: str) -> dict:
    """Return the data section of a ConfigMap dumped with -o yaml."""
    try:
        doc = yaml.safe_load((d / f"cm-{name}.yaml").read_text()) or {}
    except (OSError, yaml.YAMLError):
        return {}
    return doc.get("data") or {}


def sub_yaml(text: str | None) -> dict:
    if not text:
        return {}
    try:
        return yaml.safe_load(text) or {}
    except yaml.YAMLError:
        return {}


def image_tag(image: str | None) -> str | None:
    if not image:
        return None
    image = image.split("@", 1)[0]
    last = image.rsplit("/", 1)[-1]
    return last.split(":", 1)[1] if ":" in last else None


def flag_map(command: list[str]) -> dict[str, str]:
    flags = {}
    for part in command or []:
        if part.startswith("--"):
            key, _, value = part[2:].partition("=")
            flags[key] = value
    return flags


def extra_args(section: dict) -> dict[str, str]:
    """kubeadm v1beta4 extraArgs is a list of {name, value}; v1beta3 a map."""
    args = (section or {}).get("extraArgs") or {}
    if isinstance(args, list):
        return {a.get("name"): str(a.get("value")) for a in args if isinstance(a, dict)}
    return {k: str(v) for k, v in args.items()}


def detect(d: pathlib.Path) -> dict:
    unknowns: list[str] = []
    manifest = load_json(d, "manifest.json", {})
    version = load_json(d, "version.json", {})
    nodes = load_json(d, "nodes.json", []) or []
    workloads = load_json(d, "kube-system-workloads.json", []) or []
    cp_pods = load_json(d, "control-plane.json", []) or []
    kubeadm = sub_yaml(load_cm(d, "kubeadm-config").get("ClusterConfiguration"))
    kubelet_cm = sub_yaml(load_cm(d, "kubelet-config").get("kubelet"))
    proxy_cm = sub_yaml(load_cm(d, "kube-proxy").get("config.conf"))
    by_name = {w["name"]: w for w in workloads}
    ws_names = set(by_name)

    # --- installer --------------------------------------------------------
    evidence: list[str] = []
    labels = Counter(k for n in nodes for k in (n.get("labels") or {}))
    kubelet_versions = Counter(n.get("kubelet") for n in nodes)
    installer = "unknown"
    if any("eks.amazonaws.com" in k for k in labels) or any("-eks-" in (v or "") for v in kubelet_versions):
        installer, evidence = "managed-eks", ["EKS node labels or kubelet version"]
    elif any("cloud.google.com/gke" in k for k in labels) or any("gke" in (v or "") for v in kubelet_versions):
        installer, evidence = "managed-gke", ["GKE node labels or kubelet version"]
    elif any("kubernetes.azure.com" in k for k in labels):
        installer, evidence = "managed-aks", ["AKS node labels"]
    elif any("+k3s" in (v or "") for v in kubelet_versions):
        installer, evidence = "k3s", ["kubelet version suffix +k3s"]
    elif any("+rke2" in (v or "") for v in kubelet_versions):
        installer, evidence = "rke2", ["kubelet version suffix +rke2"]
    elif kubeadm:
        spray = []
        if kubeadm.get("certificatesDir") == "/etc/kubernetes/ssl":
            spray.append("certificatesDir /etc/kubernetes/ssl (kubeadm default is /etc/kubernetes/pki)")
        if "dns-autoscaler" in ws_names:
            spray.append("dns-autoscaler Deployment")
        if "nodelocaldns" in ws_names:
            spray.append("nodelocaldns DaemonSet")
        if any("kubespray" in img for w in workloads for img in w.get("images", [])):
            spray.append("image path contains kubespray")
        if "apiserver-count" in extra_args(kubeadm.get("apiServer")):
            spray.append("apiserver-count extraArg")
        if len(spray) >= 2:
            installer, evidence = "kubespray", spray
        else:
            installer = "kubeadm"
            evidence = ["kubeadm-config ConfigMap present"] + spray
    else:
        unknowns.append("installer: no kubeadm-config ConfigMap and no managed/k3s/rke2 markers")

    # --- control plane and etcd ------------------------------------------
    cp_nodes = [n["name"] for n in nodes if "control-plane" in n.get("roles", []) or "master" in n.get("roles", [])]
    apiserver = next((p for p in cp_pods if p.get("component") == "kube-apiserver"), {})
    api_flags = flag_map(apiserver.get("command", []))
    etcd_pods = [p for p in cp_pods if p.get("component") == "etcd"]
    etcd_cfg = kubeadm.get("etcd") or {}
    if etcd_cfg.get("external"):
        etcd = {"topology": "external", "members": len(etcd_cfg["external"].get("endpoints", [])),
                "version": None, "managedBy": "installer (kubeadm does not upgrade external etcd)"}
        unknowns.append("etcd version: external etcd, check on the etcd hosts (etcdctl version)")
    elif etcd_pods:
        etcd = {"topology": "stacked", "members": len(etcd_pods),
                "version": image_tag(etcd_pods[0].get("image")), "managedBy": "kubeadm"}
    else:
        etcd = {"topology": "unknown"}
        unknowns.append("etcd topology")
    if etcd.get("members") and etcd["members"] % 2 == 0:
        etcd["note"] = "even number of members: no extra fault tolerance over n-1"

    # --- CNI --------------------------------------------------------------
    cni: dict = {"name": "unknown"}
    calico_ds = by_name.get("calico-node")
    installation = d / "calico-installation.yaml"
    installation_text = installation.read_text() if installation.exists() else ""
    if "kind: Installation" in installation_text:
        cni = {"name": "calico", "install": "tigera-operator"}
        status = (d / "tigerastatus.txt").read_text() if (d / "tigerastatus.txt").exists() else ""
        degraded = [l.split()[0] for l in status.splitlines()[1:] if len(l.split()) >= 3 and l.split()[1] == "False"]
        if degraded:
            cni["notAvailable"] = degraded
    elif calico_ds:
        cni = {"name": "calico", "install": "manifest", "version": image_tag(calico_ds["images"][0])}
    elif "cilium" in ws_names:
        cni = {"name": "cilium", "version": image_tag(by_name["cilium"]["images"][0])}
    elif any(n.startswith("kube-flannel") for n in ws_names):
        cni = {"name": "flannel"}
    if cni["name"] == "calico" and "version" not in cni:
        images = (d / "images.txt").read_text() if (d / "images.txt").exists() else ""
        m = re.search(r"calico/node:(v[\d.]+)", images)
        cni["version"] = m.group(1) if m else None
    if cni["name"] == "unknown":
        unknowns.append("CNI")

    # --- kube-proxy, DNS --------------------------------------------------
    kp = by_name.get("kube-proxy")
    proxy = {"mode": proxy_cm.get("mode") or ("iptables (default)" if proxy_cm else None),
             "version": image_tag(kp["images"][0]) if kp else None}
    if not kp:
        proxy["note"] = "no kube-proxy DaemonSet (eBPF CNI replacement or managed)"
    coredns = by_name.get("coredns")
    dns = {
        "coredns": image_tag(coredns["images"][0]) if coredns else None,
        "replicas": coredns.get("replicas") if coredns else None,
        "kubeadmPinnedTag": (kubeadm.get("dns") or {}).get("imageTag"),
        "nodeLocalDNS": sorted(n for n in ws_names if "nodelocaldns" in n or n.startswith("node-local-dns")),
        "kubeletClusterDNS": kubelet_cm.get("clusterDNS"),
    }

    # --- nodes ------------------------------------------------------------
    def spread(key: str, clean=lambda v: v) -> dict[str, list[str]]:
        groups: dict[str, list[str]] = defaultdict(list)
        for n in nodes:
            groups[clean(n.get(key)) or "?"].append(n["name"])
        return {k: sorted(v) for k, v in sorted(groups.items())}

    runtime = spread("runtime")
    not_ready = [n["name"] for n in nodes if n.get("ready") != "True"]
    cordoned = [n["name"] for n in nodes if n.get("unschedulable")]
    master_taint = [n["name"] for n in nodes if any(t.startswith("node-role.kubernetes.io/master") for t in n.get("taints", []))]

    return {
        "context": manifest.get("context"),
        "collectedAt": manifest.get("collectedAt"),
        "serverVersion": (version.get("serverVersion") or {}).get("gitVersion"),
        "kubeletVersions": dict(kubelet_versions),
        "installer": {"type": installer, "evidence": evidence},
        "controlPlane": {
            "nodes": len(cp_nodes),
            "kubeadmConfigVersion": kubeadm.get("kubernetesVersion"),
            "certificatesDir": kubeadm.get("certificatesDir"),
            "imageRepository": kubeadm.get("imageRepository"),
        },
        "etcd": etcd,
        "cni": cni,
        "kubeProxy": proxy,
        "dns": dns,
        "kubelet": {k: kubelet_cm.get(k) for k in ("cgroupDriver", "cpuManagerPolicy", "maxPods", "failSwapOn") if k in kubelet_cm},
        "apiServerFlags": {k: api_flags[k] for k in sorted(api_flags) if re.search(
            r"issuer|audiences|authorization|authentication|oidc|feature-gates|anonymous|token-webhook|admission", k)},
        "runtimeByNode": runtime,
        "runtimeMixed": len(runtime) > 1,
        "osByNode": {k: len(v) for k, v in spread("os").items()},
        "kernelByNode": {k: len(v) for k, v in spread("kernel").items()},
        "nodes": {"total": len(nodes), "notReady": not_ready, "cordoned": cordoned, "masterTaint": master_taint},
        "unknowns": unknowns + ["cgroup version per node (run node_facts.sh)"],
    }


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    json.dump(detect(pathlib.Path(sys.argv[1])), sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
