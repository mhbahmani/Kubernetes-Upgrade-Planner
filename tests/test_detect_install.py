from conftest import FIXTURES, load

detect = load("detect_install").detect


def test_kubeadm_stacked_etcd_operator_calico():
    r = detect(FIXTURES / "kubeadm")
    assert r["installer"]["type"] == "kubeadm"
    assert r["etcd"] == {"topology": "stacked", "members": 3, "version": "3.5.15-0", "managedBy": "kubeadm"}
    assert r["cni"]["install"] == "tigera-operator"
    assert r["cni"]["version"] == "v3.29.1"
    assert r["cni"]["notAvailable"] == ["calico"]
    assert r["kubeProxy"]["mode"] == "ipvs"
    assert r["runtimeMixed"] is True
    assert r["nodes"]["notReady"] == ["w-1"]
    assert r["nodes"]["masterTaint"] == ["cp-1"]
    assert r["apiServerFlags"]["service-account-issuer"].startswith("https://")


def test_kubespray_external_etcd_manifest_calico():
    r = detect(FIXTURES / "kubespray")
    assert r["installer"]["type"] == "kubespray"
    assert len(r["installer"]["evidence"]) >= 2
    assert r["etcd"]["topology"] == "external"
    assert r["etcd"]["members"] == 3
    assert r["cni"] == {"name": "calico", "install": "manifest", "version": "v3.29.1"}
    assert r["dns"]["kubeadmPinnedTag"] == "v1.11.1"
    assert r["dns"]["coredns"] == "v1.11.3"
    assert any("etcd version" in u for u in r["unknowns"])


def test_missing_dir_reports_unknowns(tmp_path):
    r = detect(tmp_path)
    assert r["installer"]["type"] == "unknown"
    assert any(u.startswith("installer") for u in r["unknowns"])
