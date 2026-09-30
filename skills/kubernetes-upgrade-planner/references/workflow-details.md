# Workflow details

## Contents
- Step 0: scope
- Step 1: collection edge cases
- Step 4: node facts without SSH
- Step 5: which release notes matter
- Step 7: reading plan.json
- Step 10: publishing

## Step 0: scope
Record for each cluster the context, current minor and patch, targets, and
installer if known. When the user gives a target patch ("1.35.9"), keep it for
the final hop. Every hop in between goes to the latest patch of that minor
(from eol.json).

## Step 1: collection edge cases
- `helm ls -A` hangs on large clusters. `collect_cluster.sh` lists releases from
  secret labels and decodes only the deployed revision.
- If a resource type doesn't exist (for example `tigerastatus` on a manifest
  Calico install), the file holds the error. `detect_install.py` treats that as a signal.
- Every call has a timeout (`KUBECTL_TIMEOUT`, default 60s). A timed-out call is
  written to `errors.txt`; it doesn't stop the run.

## Step 4: node facts without SSH
Give the user the command from `node_facts.sh --print` and ask them to run it
with the `!` prefix (Claude Code) or paste the output. Parse it with
`node_facts.sh --parse FILE`.

## Step 5: which release notes matter
Keep a note only if it matches something collected: runtime and cgroup, kube-proxy
mode, API versions found by scan_apis.py, kubelet flags from kubeadm-flags.env,
etcd, pause, CoreDNS, features the repos use (sidecars, DRA, gitRepo volumes,
externalIPs, AppArmor annotations).

## Step 7: reading plan.json
For each component, `steps` lists `{version, at, earliest, latest}`:
- `at`: the hop plan_hops.py chose (just in time, the fewest changes)
- `earliest` / `latest`: the window in which the step is valid

Put the window in the report so teams can schedule the step. `gaps` lists hops
where no known version fits (a blocker or a missing range), and `eolStops` lists
path minors that are already end of life.

## Step 10: publishing
Publish only the HTML, and only through the harness's own tool (in Claude, the
Artifact tool; the link starts private). Say in the reply that the link is
private until shared, and whether the page has internal IPs or hostnames
(`--redact` at collection time removes them).
