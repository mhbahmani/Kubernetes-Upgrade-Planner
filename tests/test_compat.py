import pytest
import yaml

from conftest import SCRIPTS, load

cc = load("check_compat")
net = load("_net")
CATALOG = yaml.safe_load(open(SCRIPTS.parent / "data" / "components.yaml"))["components"]
CURATED = yaml.safe_load(open(SCRIPTS.parent / "data" / "compat.yaml"))

FYI = """
projects:
  cert-manager:
    versions:
      '1.21':
        dependencies:
          kubernetes:
            ranges: ['>=1.33 <1.38']
            lastVerified: '2099-01-01'
            sources: [{url: https://cert-manager.io/docs/releases/}]
      '1.22':
        dependencies:
          kubernetes:
            ranges: ['>=1.34 <1.38']
            lastVerified: '2099-01-01'
"""


@pytest.mark.parametrize("expr,expected", [
    (">=1.34 <1.37", ["1.34", "1.36"]),
    (">=1.25.0", ["1.25", None]),
    (">1.30 <=1.35", ["1.31", "1.35"]),
    ("=1.33", ["1.33", "1.33"]),
])
def test_parse_range(expr, expected):
    assert cc.parse_range(expr) == expected


def test_merge_prefers_newer_fyi_and_reports_conflicts(monkeypatch, tmp_path):
    monkeypatch.setattr(cc, "fetch", lambda url, cache, offline: (FYI, {"source": "network"}))
    out = cc.merge(CATALOG, CURATED, ["cert-manager", "ingress-nginx"], tmp_path, False)
    cm = out["cert-manager"]
    assert cm["versions"]["1.21"]["k8s"] == ["1.33", "1.37"]
    assert cm["versions"]["1.21"]["from"] == "compatibility.fyi"
    assert cm["versions"]["1.22"]["k8s"] == ["1.34", "1.37"]
    assert cm["versions"]["1.19"]["from"] == "curated"
    assert cm["conflicts"] == [{"version": "1.21", "curated": ["1.33", "1.36"], "fyi": ["1.33", "1.37"]}]
    assert cm["rule"] == {"maxMinorStep": 1}
    assert out["ingress-nginx"]["fyi"] is None


def test_fetch_refuses_other_hosts(tmp_path):
    with pytest.raises(ValueError):
        net.fetch("https://evil.example.com/x", tmp_path)
