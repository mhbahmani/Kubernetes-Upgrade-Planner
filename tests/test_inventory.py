import pathlib

import yaml

from conftest import FIXTURES, SCRIPTS, load

inv = load("inventory_repo")
scan_apis = load("scan_apis")
CATALOG = yaml.safe_load(open(SCRIPTS.parent / "data" / "components.yaml"))["components"]
RULES = yaml.safe_load(open(SCRIPTS.parent / "data" / "removed-apis.yaml"))


def test_scan_repo_finds_appsets_values_ci_and_apis():
    repo = inv.scan_repo(FIXTURES / "repo")
    charts = {(a["chart"], a["version"], tuple(a["clusters"])) for a in repo["applications"]}
    assert ("cert-manager", "v1.17.4", ("alpha", "beta")) in charts
    assert ("metrics-server", "3.10.0", ("alpha",)) in charts
    assert all(a.get("chart") or a.get("path") for a in repo["applications"])  # ref-only source skipped
    assert repo["values"][0]["images"][0]["tag"] == "0.7.2"
    pins = [p for f in repo["ciPins"] for p in f["pins"]]
    assert {"var": "ISTIO_CHART_VERSION", "value": "1.27.3"} in pins
    assert {"chart": "argo/argo-cd", "value": "9.5.21"} in pins
    assert repo["apiVersions"]["policy/v1beta1"]["count"] == 1
    assert repo["charts"][0]["name"] == "cluster"


def test_resolve_prefers_running_version_and_filters_clusters():
    repo = inv.scan_repo(FIXTURES / "repo")
    comps, unmatched = inv.resolve(CATALOG, [repo], {"alpha": FIXTURES / "cluster-alpha"}, ["alpha"])
    assert comps["cert-manager"]["alpha"]["version"] == "1.17.4"
    assert "beta" not in comps["cert-manager"]
    assert comps["metrics-server"]["alpha"]["version"] == "0.7.2"
    assert comps["metrics-server"]["alpha"]["chartVersion"] == "3.10.0"
    assert unmatched["chartsNotInCatalog"] == []


def test_scan_apis_flags_removed_and_patterns():
    result = scan_apis.scan([FIXTURES / "repo"], "1.36", RULES)
    apis = {h["api"] for h in result["removedApis"]}
    assert "policy/v1beta1" in apis
    ids = {h["id"] for h in result["patterns"]}
    assert {"gitrepo-volume", "master-role", "seccomp-annotation"} <= ids


def test_scan_apis_respects_target():
    result = scan_apis.scan([FIXTURES / "repo"], "1.24", RULES)
    assert not any(h["api"] == "policy/v1beta1" for h in result["removedApis"])
    assert "gitrepo-volume" not in {h["id"] for h in result["patterns"]}
