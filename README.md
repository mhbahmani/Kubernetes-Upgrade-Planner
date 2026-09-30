# kubernetes-upgrade-planner

An agent skill for Claude Code, Codex and OpenCode that plans upgrades of
self-managed Kubernetes clusters (kubeadm, Kubespray) across several minor
versions. It:

- finds how each cluster was installed
- lists every component and its version, from the GitOps repos and from what actually runs
- checks each version against official compatibility data and end-of-life dates
- works out a **bridge version** for every component at every hop
- writes a sourced `report.md` and `report.html`

It never changes a cluster: every script is read-only, and upgrade commands end
up in the report as steps for a human.

## Requirements

| Tool | Why |
|---|---|
| kubectl | read-only access to the clusters (`get` on nodes, pods, configmaps in kube-system, CRDs, webhooks, PDBs; Secrets only with label `owner=helm` for release metadata) |
| python3 + PyYAML | scripts (`pip install pyyaml`) |
| bash, jq, curl | collection and fetching |
| helm, pluto (optional) | pluto adds a second deprecated-API scan |
| ansible or ssh (optional) | node facts: cgroup version, containerd package |

## Install

Pick one.

**Script, from a clone** (supports every agent, global or per project):

```bash
git clone https://github.com/mhbahmani/Kubernetes-Upgrade-Planner.git
cd Kubernetes-Upgrade-Planner
./install.sh                              # global, for every agent found on PATH
./install.sh --agent claude               # one agent: claude | codex | opencode | all
./install.sh --project ~/src/my-infra     # project-local instead of global
./install.sh --copy                       # copy instead of symlink
./install.sh --dry-run                    # show what would happen
./uninstall.sh                            # remove (same options)
```

**Script, without a clone:**

```bash
curl -fsSL https://raw.githubusercontent.com/mhbahmani/Kubernetes-Upgrade-Planner/master/install.sh \
  | bash -s -- --agent all
```

**[skills CLI](https://github.com/vercel-labs/skills):**

```bash
npx skills add mhbahmani/Kubernetes-Upgrade-Planner -a claude-code -a codex -a opencode      # project
npx skills add mhbahmani/Kubernetes-Upgrade-Planner -g -a claude-code -a codex -a opencode   # global
```

**Claude Code plugin marketplace:**

```
/plugin marketplace add mhbahmani/Kubernetes-Upgrade-Planner
/plugin install kubernetes-upgrade-planner@kubernetes-upgrade-planner
```

**Codex plugin marketplace:**

```bash
codex plugin marketplace add mhbahmani/Kubernetes-Upgrade-Planner
codex plugin install kubernetes-upgrade-planner
```

The script puts the skill in:

| Agent | Global | Project |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `.claude/skills/` |
| Codex | `~/.agents/skills/` | `.agents/skills/` |
| OpenCode | `~/.config/opencode/skills/` | `.opencode/skills/` |

OpenCode also reads the Claude and Codex directories. So when you install for
several agents, the script skips the OpenCode copy (OpenCode 1.18 also
deduplicates identical names on its own).

## Use

Ask the agent, for example:

> Plan the upgrade of prod-a (context `prod-a`) and prod-b (context `prod-b`)
> from 1.31 to 1.33 and then 1.36. Scan ~/src/gitops and ~/src/mesh.

To skip the questions, copy `assets/upgrade-planner.example.yaml` to
`upgrade-planner.yaml` and fill in your clusters, contexts, repos and targets.

The skill walks through a checklist:

1. scope
2. collect
3. detect the installer
4. inventory the repos
5. node facts
6. EOL and release notes
7. compatibility
8. hop plan
9. draft the findings and validate them
10. render
11. publish

In Claude Code, it also publishes the HTML as a private Artifact link.
`references/example-multi-cluster.md` shows what a finished assessment looks like.

You can run the scripts without an agent too (`S=skills/kubernetes-upgrade-planner/scripts`):

```bash
$S/collect_cluster.sh prod-a out/cluster-prod-a                 # read-only, asks to confirm
$S/detect_install.py out/cluster-prod-a > out/install-prod-a.json
$S/inventory_repo.py --repo ~/src/gitops --cluster prod-a=out/cluster-prod-a -o out/components.json
$S/scan_apis.py --repo ~/src/gitops --target 1.36 -o out/apis.json
$S/fetch_eol.py --products kubernetes,istio,cert-manager,argo-cd,calico,containerd -o out/eol.json
$S/check_compat.py --components out/components.json -o out/compat.json
$S/plan_hops.py --from 1.31 --to 1.33 --to 1.36 --components out/components.json \
    --compat out/compat.json --eol out/eol.json [--strategy eager] -o out/plan.json
$S/draft_findings.py --plan out/plan.json --components out/components.json --eol out/eol.json \
    --install prod-a=out/install-prod-a.json --apis out/apis.json -o out/findings.json
$S/plan_hops.py --validate out/findings.json --compat out/compat.json
$S/render_report.py out/findings.json --out out
```

`plan_hops.py` has two strategies:
- **lazy** (default): upgrade a component just before a hop needs it.
- **eager**: upgrade as soon as a version with wider support can be installed.

Every step comes with its `earliest` and `latest` hop, so teams can schedule it.

## Data and sources

- `data/components.yaml`: how each component is recognised (chart names, image
  patterns) and its upgrade-path rule (one minor at a time, n-2, next major).
- `data/compat.yaml`: Kubernetes ranges per component version, curated from
  official pages, with a source and a date. At run time, `check_compat.py` merges
  [compatibility.fyi](https://compatibility.fyi) on top and reports any
  disagreement.
- `data/removed-apis.yaml`: API removals and deprecated patterns, from the
  Kubernetes deprecation guide.
- End-of-life dates come live from [endoflife.date](https://endoflife.date) (cached for a day).

Re-check curated ranges older than about 90 days before relying on them.

## Safety

- `collect_cluster.sh` refuses every kubectl verb except `get`, `version`,
  `api-resources` and `auth can-i`. It confirms the context before it starts.
- Helm release Secrets are decoded in memory; only the chart name, version and app version are kept.
- `--redact` (or `redact.py --domain example.com`) replaces IPs, node names and
  host names with stable placeholders before you share the data.
- Collected data can contain cluster config. Keep it out of git.
- Network access is limited to endoflife.date, compatibility.fyi and raw.githubusercontent.com.

## Develop

```bash
make check      # syntax, skill validation (incl. agentskills validate via uvx), tests
```

`evals/evals.json` has scenarios for the agent: offline kubeadm bridges,
Kubespray routing, Istio bridge versions, and refusing to run upgrades. Run them
in a fresh session after changing SKILL.md or the references.

## Layout

```
skills/kubernetes-upgrade-planner/
  SKILL.md              workflow, iron laws, red flags
  agents/openai.yaml    Codex display metadata
  references/           kubeadm, kubespray, node runtime, components, istio, inventory, report format, example
  scripts/              collector, detection, inventory, API scan, EOL, compat, planner, drafting, renderer
  data/                 component catalog, compatibility ranges, removed APIs
  assets/               report CSS, findings schema, example findings, config template
.claude-plugin/         Claude Code plugin + marketplace manifests
.codex-plugin/          Codex plugin manifest
.agents/plugins/        Codex marketplace manifest
tests/                  pytest with synthetic fixtures
evals/                  agent evaluation scenarios
```
