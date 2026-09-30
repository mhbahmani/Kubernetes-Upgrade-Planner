# Kubespray clusters

## How to recognise one
`detect_install.py` looks for these signs in the collected data:
- `certificatesDir: /etc/kubernetes/ssl` in kubeadm-config (kubeadm itself uses `/etc/kubernetes/pki`)
- `dns-autoscaler` Deployment and `nodelocaldns` / `node-local-dns*` DaemonSets in kube-system
- `etcd.external` with endpoints on dedicated hosts (`etcd_deployment_type: host`)
- `apiserver-count` extraArg; image paths containing `kubespray`
- Calico as plain manifests (`calico-node` DaemonSet in kube-system, no tigera-operator)

## What Kubespray owns
Kubespray runs kubeadm under the hood, but it also pins and upgrades etcd,
containerd, the CNI, CoreDNS, NodeLocal DNS and kube-proxy settings through
inventory variables (`kube_version`, `etcd_version`, `containerd_version`,
`calico_version`, `kube_proxy_mode`, `dns_mode`). kubeadm never touches
external etcd, so plan etcd upgrades through Kubespray.

## Upgrade rules
- Each Kubespray release supports a fixed Kubernetes range and a default
  `kube_version`. Look it up in the release notes:
  https://github.com/kubernetes-sigs/kubespray/releases
- Upgrade one Kubernetes minor per run, with `upgrade-cluster.yml`, and the
  Kubespray release that supports that version. Don't skip Kubespray releases.
  https://github.com/kubernetes-sigs/kubespray/blob/master/docs/operations/upgrades.md
- Before anything else, find the Kubespray version and inventory that were last
  used. If the inventory in git doesn't match the running cluster (for example it
  says 1.26 while the cluster runs 1.31), that is a blocker finding. Find the real
  inventory, or whoever runs it (it may be a provider).

## Things to check
- External etcd: version, DB size, health (`etcdctl endpoint status -w table` on the etcd hosts)
- The kubeadm-config `dns.imageTag` versus the CoreDNS image that is running (Kubespray may manage CoreDNS itself)
- `anonymous-auth`, token-webhook auth and audit flags; carry them forward
- Addons deployed by a provider (namespaces like `<provider>-argo`, `<provider>-gitlab-agent`, second prometheus-operator, extra ingress controllers). Agree who owns them.
