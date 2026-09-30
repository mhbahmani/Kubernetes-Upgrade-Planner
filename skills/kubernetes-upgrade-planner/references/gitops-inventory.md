# Inventory: GitOps repos, Helm, IaC

## What inventory_repo.py reads
- `ApplicationSet` / `Application` YAML: each Helm source (`chart`, `repoURL`,
  `targetRevision`), the clusters from `clusters.selector.matchExpressions[].values`,
  and a `# app version` comment if present.
- `Chart.yaml` in the repo (in-repo charts: `version`, `appVersion`).
- Values files (`values/<cluster>.yaml`, `base.yaml`, `production.yaml`):
  `image.tag` / `repository` pairs, keyed by file.
- CI files (`.gitlab-ci.yml`, `Makefile`): `helm upgrade ... --version X` lines
  and `*_VERSION:` variables.
- apiVersion counts across all YAML.

## Compare with what runs
Helm releases and images from `collect_cluster.sh` are the truth. Look for:
- components that run but aren't in any repo (deployed by hand or by a provider)
- stale Helm releases left behind after a move to ArgoCD (chart version doesn't match the running image)
- image tags pinned in values that override the chart's appVersion
- the same component on different versions per cluster

## IaC that talks to the cluster (Pulumi, Terraform)
- Vault Kubernetes auth depends on the service-account issuer, `--api-audiences`,
  the signing key and sometimes a pinned CA or API URL. Record these before the
  first hop and compare after each hop. A TokenRequest with a hardcoded audience
  (`https://kubernetes.default.svc.cluster.local`) breaks if audiences change.
- Legacy `kubernetes.io/service-account-token` Secrets that were created by hand
  keep working. They are a hygiene finding, not a blocker.
- NetworkPolicies with hardcoded API server or node CIDRs break if a master is
  rebuilt on a new IP.
- Provider versions (pulumi-kubernetes, the kubernetes python client) and unpinned
  kubectl in CI images: pin kubectl to the cluster minor (skew ±1).
