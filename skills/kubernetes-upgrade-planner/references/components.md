# Components: where the compatibility data lives and how to upgrade

## Contents
- Bridge versions
- Per-component table
- Components with no Kubernetes limit
- Cross-component ordering

## Bridge versions
A component can go straight to its final target only if the target also
supports the Kubernetes version you run *today*. Otherwise pick a bridge version
that supports both sides of the next hop. `plan_hops.py` does this from
`compat.json`. Check its choices against this table.

## Per-component table

`data/compat.yaml` has the curated ranges. The **rule** column is the upgrade
path the project documents or tests.

| Component | Official matrix | Rule | Gotchas |
|---|---|---|---|
| Calico | https://docs.tigera.io/calico/latest/getting-started/kubernetes/requirements (versioned: `/calico/3.30/...`) | one minor at a time | Helm doesn't upgrade CRDs; apply them server-side first. Manifest installs (Kubespray) upgrade through Kubespray |
| cert-manager | https://cert-manager.io/docs/releases/ | one minor at a time (upgrade guides are per minor) | 1.18: private keys rotate by default; ACME HTTP01 uses pathType `Exact` (needs ingress-nginx ≥1.12.6/1.13.2). 1.20: UID/GID 65532 |
| ingress-nginx | https://github.com/kubernetes/ingress-nginx#supported-versions-table | minors may be skipped; read each changelog | Project archived 2026-03-24; the last release supports up to 1.35. Plan a replacement (Gateway API) |
| Istio | https://istio.io/latest/docs/releases/supported-releases/ | in-place: one minor; canary: ≤2 minors | See istio-envoy.md |
| Argo CD | https://argo-cd.readthedocs.io/en/stable/operator-manual/installation/#tested-versions | read every minor's upgrade notes | 3.3: ApplicationSet CRD needs SSA `--force-conflicts`. 3.4: cluster version label `vX.Y.Z` |
| Kyverno | https://kyverno.io/docs/installation/releases/ | one minor at a time | Short support per minor. 1.19 deprecates ClusterPolicy in favour of CEL policies |
| external-secrets | https://external-secrets.io/latest/introduction/stability-support/ | step through majors; read the 1.0 and 2.0 notes | Each release is tested only against the newest k8s |
| velero | https://github.com/vmware-tanzu/velero#velero-compatibility-matrix | n-2 (upgrades from up to 2 minors back are tested) | Restic replaced by Kopia; CSI plugin merged into core in 1.14 |
| kube-state-metrics | https://github.com/kubernetes/kube-state-metrics#compatibility-matrix | any | Each release is built for one client-go version; keep one release ahead of the cluster. Bitnami images are frozen (`bitnamilegacy`) |
| metrics-server | https://github.com/kubernetes-sigs/metrics-server#compatibility-matrix | any | 0.8 needs 1.31+, 0.9 needs 1.34+ |
| gpu-operator | https://docs.nvidia.com/datacenter/cloud-native/gpu-operator/latest/platform-support.html | within a major or to the next major | Newer releases are validated only with containerd 2.x; CDI on by default from 25.10 |
| topolvm | https://github.com/topolvm/topolvm/releases | one minor at a time | Support for new k8s versions is announced in release notes only |
| Kubespray | https://github.com/kubernetes-sigs/kubespray/releases | one release at a time | See kubespray.md |
| kube-prometheus-stack | https://github.com/prometheus-community/helm-charts/blob/main/charts/kube-prometheus-stack/UPGRADE.md | any, but read every major; apply CRDs by hand | Operator 0.84+ only needs k8s 1.25+ (CEL in CRDs) |
| VictoriaMetrics operator | https://docs.victoriametrics.com/operator/changelog/ | any, read the changelog | Always update CRDs |
| VictoriaLogs cluster | https://docs.victoriametrics.com/victorialogs/changelog/ | passes through v1.51.1 | storage nodes first, then select |
| Tempo | https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/migrate-to-3/ | 3.x is a new architecture | Deploy side by side |

## Components with no Kubernetes limit
prometheus-operator, vm-operator, tempo, pyroscope, logging-operator,
otel-collector, flink-operator and the exporters have no upper Kubernetes limit.
They can go to their target at any hop, but still read every major's notes.

## Cross-component ordering
- ingress-nginx ≥1.12.6 before cert-manager 1.18 (ACME pathType `Exact`)
- containerd 2 on GPU nodes before gpu-operator releases that require it
- CRDs before operators (Calico, kube-prometheus-stack, vm-operator, Argo CD)
- Two operators reconciling the same CRDs (for example a provider's
  prometheus-operator next to yours): upgrading the CRDs affects both
