import pytest
import yaml

from conftest import SCRIPTS, load

ph = load("plan_hops")
cc = load("check_compat")

CATALOG = yaml.safe_load(open(SCRIPTS.parent / "data" / "components.yaml"))["components"]
CURATED = yaml.safe_load(open(SCRIPTS.parent / "data" / "compat.yaml"))
EOL = {
    "kubernetes": {"releases": [{"name": "1.31", "isEol": True, "eolFrom": "2025-11-11"},
                                {"name": "1.33", "isEol": True, "eolFrom": "2026-06-28"}]},
    "cert-manager": {"releases": [{"name": v, "isEol": True} for v in ("1.17", "1.18", "1.19")]},
    "calico": {"releases": [{"name": v, "isEol": True} for v in ("3.29", "3.30")]},
    "istio": {"releases": [{"name": "1.27", "isEol": True}]},
}
CURRENT = {
    "cert-manager": "1.17.4", "calico": "3.29.1", "ingress-nginx": "1.12.1", "istio": "1.27.3",
    "kyverno": "1.15.2", "velero": "1.11.0", "gpu-operator": "25.3.4", "metrics-server": "0.7.2",
    "prometheus-operator": "0.60.1", "tempo": "2.9.0",
}


@pytest.fixture(scope="module")
def compat(tmp_path_factory):
    cc.fetch = lambda url, cache, offline: (None, {"source": "none"})  # curated data only
    projects = cc.merge(CATALOG, CURATED, list(CURRENT), tmp_path_factory.mktemp("c"), True)
    return {"projects": projects}


def plan(compat, strategy="lazy"):
    comps = {pid: {"c1": {"version": v}} for pid, v in CURRENT.items()}
    return ph.build_plan("1.31", ["1.33", "1.36"], comps, compat, EOL, strategy)["clusters"]["c1"]


def steps(result):
    return [(s["at"], s["from"], s["via"]) for s in result["steps"]]


def test_path_and_eol_stops(compat):
    p = ph.build_plan("1.31", ["1.33", "1.36"], {}, compat, EOL)
    assert p["path"] == ["1.31", "1.32", "1.33", "1.34", "1.35", "1.36"]
    assert {s["minor"] for s in p["eolStops"]} == {"1.31", "1.33"}
    assert [s for s in p["eolStops"] if s["minor"] == "1.33"][0]["isTarget"]


def test_lazy_bridges(compat):
    r = plan(compat)
    assert steps(r["cert-manager"]) == [("1.33", "1.17", ["1.18", "1.19", "1.20", "1.21"])]
    assert steps(r["calico"]) == [("1.32", "3.29", ["3.30", "3.31"]), ("1.35", "3.31", ["3.32"])]
    assert steps(r["istio"]) == [("1.31", "1.27", ["1.28", "1.29"]), ("1.35", "1.29", ["1.30"])]
    assert steps(r["istio"])[0] and r["istio"]["steps"][0]["reason"] == "current version is end of life"
    assert steps(r["kyverno"])[0] == ("1.33", "1.15", ["1.16", "1.17", "1.18"])
    assert steps(r["gpu-operator"]) == [("1.33", "25.3", ["26.7"])]


def test_velero_moves_two_minors_at_a_time(compat):
    r = plan(compat)["velero"]
    assert steps(r)[0] == ("1.31", "1.11", ["1.13", "1.15", "1.17"])
    assert "transient" in r["steps"][0]  # 1.13 is not tested on 1.31


def test_gaps_where_nothing_supports_the_hop(compat):
    r = plan(compat)
    assert r["ingress-nginx"]["status"] == "blocked"
    assert r["ingress-nginx"]["gaps"][0]["at"] == "1.35"
    assert len(r["ingress-nginx"]["gaps"]) == 1  # not repeated for the final minor
    assert r["velero"]["gaps"][0]["next"] == "1.36"


def test_components_without_limit_or_needing_nothing(compat):
    r = plan(compat)
    assert r["tempo"]["status"] == "no-k8s-limit"
    assert r["metrics-server"]["status"] == "ok"
    assert r["metrics-server"]["newestForFinal"] == "0.9"
    assert r["prometheus-operator"]["status"] == "ok"


def test_eager_moves_early(compat):
    r = plan(compat, "eager")
    assert steps(r["cert-manager"])[0] == ("1.31", "1.17", ["1.18", "1.19"])
    assert steps(r["calico"])[0] == ("1.31", "3.29", ["3.30"])


def test_expand_rules():
    keys = ["1.11", "1.13", "1.14", "1.15", "1.16", "1.17"]
    assert ph.expand("1.11", "1.17", keys, {"maxMinorStep": 2})[0] == ["1.13", "1.15", "1.17"]
    assert ph.expand("1.11", "1.17", keys, "any")[0] == ["1.17"]
    assert ph.expand("25.3", "26.7", ["25.3", "25.10", "26.3", "26.7"], {"maxMajorStep": 1})[0] == ["26.7"]
    via, notes = ph.expand("0.36", "0.41", ["0.36", "0.38", "0.39", "0.41"], {"maxMinorStep": 1})
    assert via == ["0.38", "0.39", "0.41"] and notes


def test_validate(compat):
    good = {"meta": {"date": "2026-09-30", "path": ["1.31", "1.32", "1.33"]},
            "components": [{"name": "cert-manager", "id": "cert-manager", "severity": "required",
                            "current": {"c1": "1.17.4"}, "refs": [{"title": "x", "url": "https://cert-manager.io"}]}],
            "matrix": {"rows": [{"id": "cert-manager", "steps": {"1.31": "1.17 → 1.19"},
                                 "refs": [{"title": "x", "url": "https://cert-manager.io"}]}]}}
    assert ph.validate(good, compat) == []
    bad = {"meta": {"date": "30/09", "path": ["1.31", "1.33"]},
           "components": [{"name": "velero", "id": "velero", "severity": "ok", "current": {"c1": "1.11.0"}, "refs": []}],
           "matrix": {"rows": [{"id": "cert-manager", "steps": {"1.31": "→ 1.21"}}]}}
    errors = " | ".join(ph.validate(bad, compat))
    for expected in ("skips a minor", "meta.date", "no refs", "1.21 supports", "marked ok"):
        assert expected in errors
