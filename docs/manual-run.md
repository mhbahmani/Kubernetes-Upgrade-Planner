# Running without an agent

Every step of the skill is a script. You can run the whole pipeline by hand
and get the same report.

Set `S=skills/kubernetes-upgrade-planner/scripts`, then:

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

