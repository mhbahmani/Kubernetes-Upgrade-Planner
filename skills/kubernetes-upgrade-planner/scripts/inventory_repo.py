#!/usr/bin/env python3
"""Inventory components from GitOps / IaC repos and (optionally) what runs.

    inventory_repo.py --repo PATH [--repo PATH ...]
                      [--cluster NAME=COLLECT_DIR ...] [--clusters a,b]
                      [-o components.json]

Reads ArgoCD ApplicationSets/Applications, in-repo Chart.yaml, image tags in
values files, version pins in CI files, and apiVersion counts. With --cluster it
also reads helm-releases.json and images.txt from collect_cluster.sh output and
resolves each catalog component (data/components.yaml) to a running version.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict

import yaml

SKILL = pathlib.Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", "node_modules", "vendor", ".venv", "venv", "__pycache__", ".terraform", ".codegraph",
             ".local-go-cache", ".cache", "testdata", "third_party", ".pytest_cache"}
YAML_EXT = {".yaml", ".yml"}
TEXT_EXT = YAML_EXT | {".j2", ".tpl", ".py", ".json", ".ts"}
API_RE = re.compile(r"""apiVersion["']?\s*[:=]\s*["']?([a-z0-9.\-]+/v[0-9a-z]+|v1)\b""")
CI_VERSION_RE = re.compile(r"""^\s*([A-Z0-9_]*VERSION[A-Z0-9_]*)\s*[:=]\s*["']?([vV]?[\w.\-]+)["']?\s*$""", re.M)
HELM_VERSION_RE = re.compile(r"helm\s+(?:upgrade|install)\b[^\n]*?\s(\S+/\S+)[^\n]*?--version[= ]\s*([\w.\-]+)")
GOMOD_RE = re.compile(r"^\s*(github\.com/envoyproxy/envoy|k8s\.io/client-go|k8s\.io/api|istio\.io/api)\s+(v[\w.\-]+)", re.M)
IMAGE_RE = re.compile(r"""(?:^\s*(?:image|FROM)\s*:?\s+|^FROM\s+)["']?([\w.\-/]+:[\w.\-]+)""", re.M)


def walk(root: pathlib.Path):
    for path in root.rglob("*"):
        parts = path.relative_to(root).parts
        if any(part in SKIP_DIRS or part.startswith("upgrade-data-") or part == "k8s-upgrade-plan" for part in parts):
            continue  # also skip collected cluster data left inside a repo
        if path.is_file():
            yield path


def load_docs(path: pathlib.Path) -> list:
    try:
        return [d for d in yaml.safe_load_all(path.read_text(errors="replace")) if isinstance(d, dict)]
    except (yaml.YAMLError, ValueError):
        return []  # Helm templates and Jinja files are not plain YAML


def cluster_values(generators: list) -> list[str]:
    """Cluster names from cluster-generator selectors and list generators."""
    names: list[str] = []
    for gen in generators or []:
        for kind, spec in (gen or {}).items():
            spec = spec or {}
            if kind == "clusters":
                for expr in (spec.get("selector") or {}).get("matchExpressions", []) or []:
                    if expr.get("operator") == "In":
                        names += [str(v) for v in expr.get("values", [])]
                for v in ((spec.get("selector") or {}).get("matchLabels") or {}).values():
                    names.append(str(v))
            elif kind == "list":
                for el in spec.get("elements", []) or []:
                    for key in ("cluster", "name"):
                        if key in el:
                            names.append(str(el[key]))
            elif kind in ("matrix", "merge"):
                names += cluster_values(spec.get("generators"))
    return sorted(set(names))


def app_sources(doc: dict) -> tuple[str, list[dict], list[str]]:
    kind = doc.get("kind")
    spec = doc.get("spec") or {}
    if kind == "ApplicationSet":
        tmpl = (spec.get("template") or {}).get("spec") or {}
        clusters = cluster_values(spec.get("generators"))
    else:
        tmpl = spec
        dest = spec.get("destination") or {}
        clusters = [dest["name"]] if dest.get("name") else []
    sources = tmpl.get("sources") or ([tmpl["source"]] if tmpl.get("source") else [])
    return (doc.get("metadata") or {}).get("name", "?"), sources, clusters


def scan_repo(root: pathlib.Path) -> dict:
    apps, charts, values, ci = [], [], [], []
    apis: dict[str, dict] = {}
    for path in walk(root):
        rel = str(path.relative_to(root))
        suffix = path.suffix.lower()
        name = path.name
        if suffix in TEXT_EXT or name in ("Dockerfile", "Makefile", "go.mod") or name.startswith("Dockerfile"):
            try:
                text = path.read_text(errors="replace")
            except OSError:
                continue
            if suffix in TEXT_EXT:
                for m in API_RE.finditer(text):
                    entry = apis.setdefault(m.group(1), {"count": 0, "files": []})
                    entry["count"] += 1
                    if rel not in entry["files"] and len(entry["files"]) < 5:
                        entry["files"].append(rel)
        else:
            continue

        if name == "Chart.yaml":
            for doc in load_docs(path):
                charts.append({"path": rel, "name": doc.get("name"), "version": str(doc.get("version")),
                               "appVersion": str(doc.get("appVersion")) if doc.get("appVersion") else None,
                               "dependencies": [{k: str(d.get(k)) for k in ("name", "version", "repository")}
                                                for d in doc.get("dependencies") or []]})
            continue

        if suffix in YAML_EXT and "kind:" in text and ("ApplicationSet" in text or "kind: Application" in text):
            for doc in load_docs(path):
                if doc.get("kind") not in ("ApplicationSet", "Application"):
                    continue
                app_name, sources, clusters = app_sources(doc)
                for src in sources:
                    entry = {"file": rel, "app": app_name, "kind": doc["kind"], "clusters": clusters,
                             "repoURL": src.get("repoURL")}
                    if src.get("chart"):
                        entry.update(chart=src["chart"], version=str(src.get("targetRevision")))
                    elif src.get("path"):
                        entry.update(path=src["path"], version=str(src.get("targetRevision")))
                    else:
                        continue  # a bare `ref:` source for value files
                    apps.append(entry)
            continue

        if suffix in YAML_EXT and "/values" in f"/{rel}":
            found = []
            for doc in load_docs(path):
                found += image_refs(doc)
            if found:
                values.append({"file": rel, "cluster": path.stem, "images": found})
            continue

        if name == "go.mod":
            pins = [{"module": m.group(1), "value": m.group(2)} for m in GOMOD_RE.finditer(text)]
            if pins:
                ci.append({"file": rel, "pins": pins})
            continue

        if name in (".gitlab-ci.yml", "Makefile") or name.startswith("Dockerfile") or suffix == ".sh":
            pins = [{"var": m.group(1), "value": m.group(2)} for m in CI_VERSION_RE.finditer(text)]
            pins += [{"chart": m.group(1), "value": m.group(2)} for m in HELM_VERSION_RE.finditer(text)]
            pins += [{"image": m.group(1)} for m in IMAGE_RE.finditer(text)]
            if pins:
                ci.append({"file": rel, "pins": pins})
    return {"path": str(root), "applications": apps, "charts": charts, "values": values,
            "ciPins": ci, "apiVersions": dict(sorted(apis.items(), key=lambda kv: -kv[1]["count"]))}


def image_refs(node, trail: str = "") -> list[dict]:
    """Find {repository, tag} pairs and "repo:tag" image strings in a values tree."""
    out = []
    if isinstance(node, dict):
        repo = node.get("repository") or node.get("image")
        tag = node.get("tag")
        if isinstance(repo, str) and tag not in (None, "", "~") and not isinstance(tag, (dict, list)):
            out.append({"key": trail or ".", "repository": repo, "tag": str(tag)})
        for k, v in node.items():
            if k == "image" and isinstance(v, str) and ":" in v.rsplit("/", 1)[-1]:
                repo_s, _, tag_s = v.rpartition(":")
                out.append({"key": f"{trail}.image".lstrip("."), "repository": repo_s, "tag": tag_s})
            elif isinstance(v, (dict, list)):
                out += image_refs(v, f"{trail}.{k}".lstrip("."))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            out += image_refs(v, f"{trail}[{i}]")
    return out


def version_key(raw: str | None) -> str | None:
    """'v1.17.4' -> '1.17.4'; keeps only the numeric dotted prefix."""
    if not raw:
        return None
    m = re.match(r"v?(\d+(?:\.\d+)*)", str(raw).strip())
    return m.group(1) if m else None


def resolve(catalog: dict, repos: list[dict], running: dict[str, pathlib.Path], wanted: list[str]) -> tuple[dict, dict]:
    components: dict[str, dict] = defaultdict(dict)
    matched_charts: set[str] = set()
    chart_to_id = {c: cid for cid, spec in catalog.items() for c in spec.get("charts", [])}

    # repo side: ApplicationSets per cluster
    for repo in repos:
        for app in repo["applications"]:
            cid = chart_to_id.get(app.get("chart", ""))
            if not cid:
                continue
            matched_charts.add(app["chart"])
            for cluster in app["clusters"] or ["*"]:
                if wanted and cluster not in wanted and cluster != "*":
                    continue
                slot = components[cid].setdefault(cluster, {"evidence": []})
                slot["evidence"].append({"from": "repo", "file": f'{pathlib.Path(repo["path"]).name}/{app["file"]}',
                                         "chart": app["chart"], "chartVersion": app["version"]})
                slot.setdefault("chartVersion", version_key(app["version"]))

    # running side: helm releases and images
    for cluster, cdir in running.items():
        try:
            releases = json.loads((cdir / "helm-releases.json").read_text())
        except (OSError, ValueError):
            releases = []
        for rel in releases:
            cid = chart_to_id.get(rel.get("chart") or "")
            if not cid:
                continue
            matched_charts.add(rel["chart"])
            slot = components[cid].setdefault(cluster, {"evidence": []})
            slot["evidence"].append({"from": "helm", "release": f'{rel["namespace"]}/{rel["release"]}',
                                     "chartVersion": rel.get("version"), "appVersion": rel.get("appVersion")})
        images = (cdir / "images.txt").read_text() if (cdir / "images.txt").exists() else ""
        for cid, spec in catalog.items():
            for pattern in spec.get("images", []):
                counts = Counter()
                for line in images.splitlines():
                    parts = line.split()
                    if len(parts) != 2:
                        continue
                    ref = parts[1].split("@", 1)[0]
                    m = re.search(pattern, ref)
                    if m:
                        counts[version_key(m.group(1))] += int(parts[0])
                if counts:
                    slot = components[cid].setdefault(cluster, {"evidence": []})
                    slot["evidence"].append({"from": "image", "versions": dict(counts)})
                    slot["running"] = counts.most_common(1)[0][0]

    # pick one version per component and cluster
    for cid, per_cluster in components.items():
        by_chart = catalog[cid].get("version") == "chart"
        for slot in per_cluster.values():
            helm = [e for e in slot["evidence"] if e["from"] == "helm"]
            if by_chart:
                slot["version"] = slot.get("chartVersion") or (version_key(helm[0]["chartVersion"]) if helm else None) or slot.get("running")
            else:
                slot["version"] = slot.get("running") or (version_key(helm[0].get("appVersion")) if helm else None)
            if not slot["version"]:
                slot["version"] = None
                slot["note"] = "only the chart version is known; app version comes from the running image or the chart's appVersion"
            versions = {e.get("chartVersion") for e in slot["evidence"] if e.get("chartVersion")}
            if len(versions) > 1:
                slot["drift"] = sorted(versions)

    unmatched = sorted({a["chart"] for r in repos for a in r["applications"] if a.get("chart")} - matched_charts)
    return dict(components), {"chartsNotInCatalog": unmatched}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", action="append", default=[], help="repo to scan (repeatable)")
    ap.add_argument("--cluster", action="append", default=[], help="NAME=collect_cluster.sh output dir")
    ap.add_argument("--clusters", default="", help="only keep these ApplicationSet cluster names (comma list)")
    ap.add_argument("--catalog", default=str(SKILL / "data" / "components.yaml"))
    ap.add_argument("-o", "--output", default="-")
    args = ap.parse_args()
    if not args.repo and not args.cluster:
        ap.error("give at least one --repo or --cluster")

    catalog = yaml.safe_load(open(args.catalog))["components"]
    repos = [scan_repo(pathlib.Path(p).expanduser().resolve()) for p in args.repo]
    running = {}
    for item in args.cluster:
        name, _, cdir = item.partition("=")
        if not cdir:
            ap.error(f"--cluster expects NAME=DIR, got {item}")
        running[name] = pathlib.Path(cdir).expanduser()
    wanted = [c for c in args.clusters.split(",") if c] or list(running)
    components, unmatched = resolve(catalog, repos, running, wanted)
    result = {"clusters": wanted, "components": components, "unmatched": unmatched, "repos": repos}
    out = sys.stdout if args.output == "-" else open(args.output, "w")
    json.dump(result, out, indent=1)
    out.write("\n")


if __name__ == "__main__":
    main()
