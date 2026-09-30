# Development

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
