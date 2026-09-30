# Kubernetes Upgrade Planner

An agent skill that turns "we need to get from 1.31 to 1.36" into a plan you can
act on. It works in **Claude Code**, **Codex** and **OpenCode**.

Point it at your clusters and GitOps repos, and it tells you:

- how each cluster was installed (kubeadm, Kubespray, managed)
- which components block which hop, and which versions are already end of life
- the **bridge version** each component needs at each hop, in upgrade order
- what to fix on the nodes first: containerd, cgroup v2, kube-proxy mode, etcd

The result is a `report.md` and a `report.html` where every version has a
source. In Claude Code, the HTML is also shared as a private link.

The skill only reads. It never changes a cluster; upgrade commands go in the
report for a human to run.

## Install

```bash
git clone https://github.com/mhbahmani/Kubernetes-Upgrade-Planner.git
cd Kubernetes-Upgrade-Planner
./install.sh            # every agent on your PATH, global
```

To install for one agent or one project, use `--agent codex` or `--project DIR`.
You can also install with `npx skills` or through the Claude and Codex plugin
marketplaces; see [docs/install.md](docs/install.md).

The skill needs `kubectl`, `python3` with PyYAML, `jq` and `curl`.

## Use

Ask your agent:

> Plan the upgrade of prod-a and prod-b from 1.31 to 1.33, then 1.36.
> Scan ~/src/gitops and ~/src/mesh.

The report has these sections:

- **Summary**: the blockers
- **Cluster snapshot**: how each cluster is installed and what it runs
- **Support window**: end-of-life dates, with links to each changelog
- **Node layer**: runtime, cgroup, kube-proxy, etcd, API removals
- **Components**: current and target versions
- **Upgrade sequence**: a per-hop table showing the version each component must reach before each hop

Here is part of an upgrade sequence table:

| Component | On 1.31 | On 1.32 | On 1.33 | … | 1.36 |
|---|---|---|---|---|---|
| cert-manager | 1.17 → 1.18 → **1.19** | | → 1.20 → **1.21** | | 1.21 |
| calico | 3.29 → **3.30** | | | → 3.31 → **3.32** | 3.32 |
| ingress-nginx | 1.12 → **1.15** | | | ⛔ nothing supports 1.36 | blocked |

## More

- [docs/install.md](docs/install.md): every install method, requirements, where the files go
- [docs/manual-run.md](docs/manual-run.md): run the scripts yourself, data sources, safety
- [docs/development.md](docs/development.md): tests, evals, repo layout

MIT licensed.
