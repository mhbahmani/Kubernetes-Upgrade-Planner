# kubeadm clusters

## Contents
- Hop procedure
- Things kubeadm overwrites
- Version-specific kubeadm changes
- Checks before each hop

## Hop procedure (one minor per hop)

Put these in the report as steps for a human. Never run them yourself.

1. Switch the package repo to `pkgs.k8s.io/core:/stable:/v1.X/deb` (the repo is per minor).
2. On the first control-plane node: upgrade kubeadm, run `kubeadm upgrade plan`, then `kubeadm upgrade apply v1.X.Y`.
3. On the other control-plane nodes, one at a time, run `kubeadm upgrade node`.
4. On each node: drain, upgrade kubelet and kubectl, restart kubelet, uncordon.
5. Workers follow. kubelet may be up to 3 minors behind the API server
   (https://kubernetes.io/releases/version-skew-policy/), but don't let it drift that far.

Source: https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-upgrade/

## Things kubeadm overwrites

- **`/var/lib/kubelet/config.yaml`**. `kubeadm upgrade node` rewrites it from the
  `kube-system/kubelet-config` ConfigMap. If nodes have custom settings applied
  after joining (for example by an ansible role: NodeLocal DNS clusterDNS,
  `cpuManagerPolicy: static`, reserved resources, eviction, maxPods), they are lost.
  Compare the ConfigMap with a node's file. Then either put the settings into the
  ConfigMap, or re-apply them after `kubeadm upgrade node` and before restarting
  kubelet. Changing `cpuManagerPolicy` also needs
  `/var/lib/kubelet/cpu_manager_state` removed.
  https://kubernetes.io/docs/tasks/administer-cluster/kubeadm/kubeadm-reconfigure/
- **CoreDNS**. `upgrade apply` replaces the image and can reset Deployment
  changes such as replicas. It skips migrating a Corefile it doesn't recognise.
  Back up the Deployment and ConfigMap and compare after each hop. Mirror the new
  image if you use a private registry (`dns.imageRepository`).
- **Static pod manifests** are regenerated from ClusterConfiguration. Hand edits
  to `/etc/kubernetes/manifests` are lost; extraArgs must be in kubeadm-config.

## Version-specific kubeadm changes (from the official changelogs)

| Minor | Change |
|---|---|
| 1.32 | `upgrade apply/node` gain phases; EtcdLearnerMode GA |
| 1.34 | Stacked etcd moves to 3.6 (no downgrade; needs 3.5.20+ first). pause 3.10.1. NodeLocalCRISocket on by default |
| 1.35 | Kubelet refuses cgroup v1 (`failCgroupV1: true`); kubeadm preflight fails too. Removes `--pod-infra-container-image` (strip it from extraArgs). Warns when the runtime lacks `RuntimeConfig` (containerd 1.7) |
| 1.36 | Drops etcd below 3.6 and flex-volume support. pause 3.10.2 |
| 1.37 | Removes the v1beta3 config API. Explicitly sets kube-proxy `iptables` mode when none is given, and warns about IPVS |

Check the changelog of every hop yourself; this table is a starting point, not
a complete list.

## Checks before each hop

- `kubeadm certs check-expiration` (certificates are renewed by `upgrade apply`)
- Snapshot etcd (`etcdctl snapshot save`) and back up `/etc/kubernetes`
- The pause image in the containerd config matches what kubeadm expects
- Custom taints: kubeadm stopped using `node-role.kubernetes.io/master` in 1.25; look for mixed taints across masters
- Deprecated API metric: `kubectl get --raw /metrics | grep apiserver_requested_deprecated_apis` (it resets when the API server restarts)
