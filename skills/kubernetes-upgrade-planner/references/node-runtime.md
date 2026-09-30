# Node layer: cgroup, containerd, kube-proxy, kernel, OS

## Contents
- cgroup v2
- containerd 1.7 to 2.x
- kube-proxy IPVS
- Kernel minimums
- OS support

## cgroup v2
From 1.35, kubelet defaults to `failCgroupV1: true` and refuses to start on
cgroup v1. Check every node with `stat -fc %T /sys/fs/cgroup` (it should print
`cgroup2fs`) and look for `systemd.unified_cgroup_hierarchy=0` in
`/proc/cmdline`. Nodes upgraded in place from an old OS are the most likely to
still be on v1. https://kubernetes.io/docs/concepts/architecture/cgroups/

## containerd 1.7 to 2.x
- Which containerd versions each Kubernetes release supports:
  https://github.com/containerd/containerd/blob/main/RELEASES.md.
  Kubernetes 1.35 is the last release that supports containerd 1.x.
- 1.7 LTS can jump straight to 2.3 LTS; other upgrades go one minor at a time.
- Distro packages (Ubuntu's `containerd`) can jump from 1.7 to 2.x on a routine
  `apt upgrade`. Look for mixed versions across nodes; hold the package until you
  migrate on purpose.
- What changes in 2.x:
  https://github.com/containerd/containerd/blob/main/docs/containerd-2.0.md
  - config `version = 3`; `containerd config migrate`
  - CRI plugin split: `SystemdCgroup` goes under `io.containerd.cri.v1.runtime`,
    and `pinned_images.sandbox` replaces `sandbox_image`
  - registry mirrors move to `config_path = "/etc/containerd/certs.d"` with `hosts.toml`
  - removed: runtime v1, `io.containerd.runc.v1`, aufs, CRI v1alpha2, schema 1 images
- GPU nodes: check that the NVIDIA toolkit version supports containerd 2 and config v3.

## kube-proxy IPVS
IPVS is deprecated in 1.35, and 1.37 adds a `KubeProxyIPVS` gate in preparation
for removing it. Moving to `iptables` is the lowest-risk option. `nftables` needs
kernel 5.13+ and pairs with Calico's nftables dataplane. NodeLocal DNS is set up
differently in IPVS mode than in iptables mode (in iptables mode it also binds
the kube-dns ClusterIP), so re-render it and test on one node.
https://kubernetes.io/docs/reference/networking/virtual-ips/ and
https://kubernetes.io/docs/tasks/administer-cluster/nodelocaldns/

## Kernel minimums
cgroup v2 needs 5.8+, Calico 3.32 needs 5.10+, nftables kube-proxy needs 5.13+,
and user namespaces want 6.3+.

## OS support
Check the node OS's support dates on endoflife.date (for example `ubuntu`). An OS
that goes out of standard support during the upgrade window is a finding.
