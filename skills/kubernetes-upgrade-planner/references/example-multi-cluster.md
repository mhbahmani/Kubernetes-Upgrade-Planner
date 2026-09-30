# Worked example: one kubeadm and one Kubespray cluster, 1.31 to 1.36

A real assessment, anonymised. Use it to see what a finished plan looks like
and which findings tend to matter. Don't copy its versions; fetch current data.

## Setup
| | cluster-a | cluster-b |
|---|---|---|
| Installer | kubeadm, driven by an ansible role | Kubespray (inventory in git was stale: pinned 1.26 while the cluster ran 1.31) |
| Control plane | 5 masters, stacked etcd 3.5.15 | 6 masters, 3 external etcd hosts |
| Runtime | containerd 1.7.24 / 1.7.27 / 1.7.28 / 2.2.1 (distro package drifted) | containerd 1.7.24 everywhere |
| Network | tigera-operator Calico 3.29, kube-proxy IPVS, NodeLocal DNS | manifest Calico 3.29, kube-proxy IPVS, NodeLocal DNS |
| Repos | ArgoCD ApplicationSets + Helm values; Istio with custom Envoy Go plugins in a second repo; Pulumi for namespaces and Vault | same repos |

## Findings that changed the plan
- The first target (1.33) was already end of life, so it became a stop on the way to 1.36.
- containerd 1.x blocks 1.36; cgroup v1 blocks 1.35; IPVS is deprecated in 1.35.
- On the kubeadm cluster, `kubeadm upgrade node` would have overwritten the kubelet config that an ansible role applied after join (NodeLocal DNS address, static CPU manager, reserved resources).
- On the Kubespray cluster, a provider ran its own addons (a second prometheus-operator on the same CRDs, an old ingress-nginx, an Argo CD instance), which had to be agreed with the provider.
- ingress-nginx had no release supporting 1.36 (the project is retired), so it needed a replacement project.
- Vault login from IaC used a TokenRequest with a hardcoded audience; a change in service-account issuer or audiences would have broken it.
- NetworkPolicies in IaC hardcoded the API server CIDR.
- PDBs with zero allowed disruptions (7 and 18) and many fail-closed webhooks would have stalled drains.

## Bridge versions (eager strategy)
| Component | On 1.31 | Later |
|---|---|---|
| cert-manager 1.17 | 1.18 → 1.19 | 1.20 → 1.21 on 1.33 |
| Calico 3.29 | 3.30 | 3.31 → 3.32 on 1.34 |
| Istio 1.27 | 1.28 → 1.29 (rebuild plugins each step) | 1.30 on 1.32+ |
| Kyverno 1.15 | stays | 1.16 → 1.19 one minor at a time on 1.33 |
| velero 1.11 | 1.13 → 1.15 → 1.17 (n-2) | 1.18 on 1.33 |
| gpu-operator 25.3 | stays | containerd 2 on GPU nodes, then 26.7 on 1.33 |
| ingress-nginx 1.12 | 1.13+ (before cert-manager 1.18) | replacement before 1.36 |
