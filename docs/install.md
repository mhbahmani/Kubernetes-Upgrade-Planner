# Install

## Requirements

| Tool | Why |
|---|---|
| kubectl | read-only access to the clusters (`get` on nodes, pods, configmaps in kube-system, CRDs, webhooks, PDBs; Secrets only with label `owner=helm` for release metadata) |
| python3 + PyYAML | scripts (`pip install pyyaml`) |
| bash, jq, curl | collection and fetching |
| helm, pluto (optional) | pluto adds a second deprecated-API scan |
| ansible or ssh (optional) | node facts: cgroup version, containerd package |

## Methods

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

