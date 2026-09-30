#!/usr/bin/env bash
# Collect read-only cluster data for upgrade planning.
#
#   collect_cluster.sh [--yes] [--redact] [--skip-helm] CONTEXT OUT_DIR
#
# Every kubectl call goes through kc(), which refuses anything but
# get / version / api-resources / auth can-i. Nothing here changes the cluster.
# Secret *contents* are never written: Helm release secrets are decoded in
# memory and only chart name/version/app version are kept.
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TIMEOUT="${KUBECTL_TIMEOUT:-60}"
YES=0 REDACT=0 SKIP_HELM=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1; shift ;;
    --redact) REDACT=1; shift ;;
    --skip-helm) SKIP_HELM=1; shift ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    -*) echo "unknown option: $1" >&2; exit 2 ;;
    *) break ;;
  esac
done
CTX="${1:?usage: collect_cluster.sh [--yes] [--redact] [--skip-helm] CONTEXT OUT_DIR}"
OUT="${2:?OUT_DIR required}"

for bin in kubectl jq python3; do
  command -v "$bin" >/dev/null || { echo "error: $bin not found" >&2; exit 1; }
done

kc() {
  # the verb is the first word that isn't a flag or a flag's value
  local args=("$@") i=0 verb="" next=""
  while [[ $i -lt ${#args[@]} ]]; do
    case "${args[$i]}" in
      -n|--namespace|-l|--selector|-o|--output) i=$((i + 2)) ;;
      -*) i=$((i + 1)) ;;
      *) verb="${args[$i]}"; next="${args[$((i + 1))]:-}"; break ;;
    esac
  done
  case "$verb" in
    get|version|api-resources) ;;
    auth) [[ "$next" == "can-i" ]] || { echo "refused: kubectl $*" >&2; return 97; } ;;
    *) echo "refused: kubectl $* (read-only collector)" >&2; return 97 ;;
  esac
  timeout "$((TIMEOUT + 5))" kubectl --context "$CTX" --request-timeout="${TIMEOUT}s" "$@"
}

SERVER="$(kubectl config view -o jsonpath="{.clusters[?(@.name==\"$(kubectl config view -o jsonpath="{.contexts[?(@.name==\"$CTX\")].context.cluster}")\")].cluster.server}" 2>/dev/null)"
[[ -n "$SERVER" ]] || { echo "error: context '$CTX' not found in kubeconfig" >&2; exit 1; }
echo "context: $CTX"
echo "server:  $SERVER"
echo "output:  $OUT"
if [[ "$YES" -ne 1 ]]; then
  if (exec 3< /dev/tty) 2>/dev/null; then
    printf "Collect read-only data from this cluster? [y/N] "
    IFS= read -r answer < /dev/tty || answer=""
    [[ "$answer" == [yY]* ]] || { echo "aborted"; exit 1; }
  else
    echo "error: no terminal to confirm; pass --yes after checking the context" >&2; exit 1
  fi
fi

mkdir -p "$OUT"
ERR="$OUT/errors.txt"; : > "$ERR"
# run NAME CMD...: write stdout to OUT/NAME, record failures without stopping
run() {
  local name="$1"; shift
  if ! "$@" > "$OUT/$name" 2>> "$ERR"; then
    echo "failed: $name ($*)" >> "$ERR"
  fi
}

# Each collector is a function so pipelines keep normal quoting.
nodes_json() {
  kc get nodes -o json | jq '[.items[] | {
    name: .metadata.name,
    roles: [.metadata.labels | to_entries[] | select(.key | startswith("node-role.kubernetes.io/")) | .key | sub("node-role.kubernetes.io/"; "")],
    labels: (.metadata.labels | with_entries(select(.key | test("eks.amazonaws.com|cloud.google.com|kubernetes.azure.com|node.kubernetes.io/instance-type|k3s.io|rke2.io|nvidia.com/gpu.present")))),
    kubelet: .status.nodeInfo.kubeletVersion,
    runtime: .status.nodeInfo.containerRuntimeVersion,
    os: .status.nodeInfo.osImage,
    kernel: .status.nodeInfo.kernelVersion,
    internalIP: ([.status.addresses[]? | select(.type == "InternalIP") | .address][0]),
    ready: ([.status.conditions[]? | select(.type == "Ready") | .status][0]),
    unschedulable: (.spec.unschedulable // false),
    taints: [.spec.taints[]? | "\(.key)=\(.value // ""):\(.effect)"]
  }]'
}
kube_system_json() {
  kc -n kube-system get ds,deploy,sts -o json | jq '[.items[] | {
    kind, name: .metadata.name,
    replicas: (.spec.replicas // .status.desiredNumberScheduled),
    ready: (.status.readyReplicas // .status.numberReady // 0),
    nodeSelector: .spec.template.spec.nodeSelector,
    images: [.spec.template.spec.containers[].image]
  }]'
}
control_plane_json() {
  kc -n kube-system get pods -l tier=control-plane -o json | jq '[.items[] | {
    name: .metadata.name, node: .spec.nodeName,
    component: .metadata.labels.component,
    image: .spec.containers[0].image,
    command: ((.spec.containers[0].command // []) + (.spec.containers[0].args // []))
  }]'
}
images_txt() {
  kc get pods -A -o jsonpath='{range .items[*]}{range .spec.initContainers[*]}{.image}{"\n"}{end}{range .spec.containers[*]}{.image}{"\n"}{end}{end}' \
    | sort | uniq -c | sort -rn
}
pods_by_image() {
  kc get pods -A -o json | jq -r '[.items[] | .metadata.namespace as $ns | .spec.containers[].image | [$ns, .]] | unique[] | @tsv'
}
helm_releases() {
  # helm ls -A decodes every revision of every release and hangs on big
  # clusters; read only deployed revisions and keep chart metadata.
  TIMEOUT=$((TIMEOUT * 5)) kc get secrets -A -l owner=helm,status=deployed -o json | python3 "$HERE/_helm_decode.py"
}
crds_json() {
  kc get crd -o json | jq '[.items[] | {name: .metadata.name, group: .spec.group,
    served: [.spec.versions[] | select(.served) | .name], stored: .status.storedVersions}]'
}
webhooks_json() {
  kc get validatingwebhookconfigurations,mutatingwebhookconfigurations -o json | jq '[.items[] | {
    kind, name: .metadata.name,
    webhooks: [.webhooks[] | {name, failurePolicy,
      service: (.clientConfig.service | if . then "\(.namespace)/\(.name)" else null end)}]}]'
}
pdb_blocking() {
  kc get pdb -A -o json | jq '[.items[] | select((.status.disruptionsAllowed // 0) == 0) | {
    namespace: .metadata.namespace, name: .metadata.name,
    expected: .status.expectedPods, healthy: .status.currentHealthy}]'
}
deprecated_apis() {
  kc get --raw /metrics | grep '^apiserver_requested_deprecated_apis' || true
}
argocd_json() {
  kc get deploy,sts -A -l app.kubernetes.io/part-of=argocd -o json | jq '[.items[] | {
    namespace: .metadata.namespace, name: .metadata.name, image: .spec.template.spec.containers[0].image}]'
}
gpu_json() {
  kc get clusterpolicies.nvidia.com -o json | jq '[.items[] | {name: .metadata.name,
    driver: .spec.driver.version, toolkit: .spec.toolkit.version,
    devicePlugin: .spec.devicePlugin.version, cdi: .spec.cdi.enabled, state: .status.state}]'
}

echo "collecting..."
run version.json            kc version -o json
run api-resources.txt       kc api-resources -o wide
for cm in kubeadm-config kubelet-config kube-proxy coredns; do
  run "cm-$cm.yaml"         kc -n kube-system get cm "$cm" -o yaml
done
run nodes.json              nodes_json
run kube-system-workloads.json kube_system_json
run control-plane.json      control_plane_json
run images.txt              images_txt
run pods-by-image.tsv       pods_by_image
[[ "$SKIP_HELM" -eq 1 ]] || run helm-releases.json helm_releases
run calico-installation.yaml kc get installation default -o yaml
run tigerastatus.txt        kc get tigerastatus
run storageclasses.txt      kc get storageclass -o wide
run crds.json               crds_json
run apiservices.txt         kc get apiservices
run webhooks.json           webhooks_json
run pdb-blocking.json       pdb_blocking
run deprecated-apis.txt     deprecated_apis
run argocd.json             argocd_json
run gpu-clusterpolicy.json  gpu_json

python3 - "$OUT" "$CTX" "$SERVER" <<'EOF'
import json, subprocess, sys, datetime, pathlib
out, ctx, server = sys.argv[1:]
def v(cmd):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
    except Exception:
        return None
errors = [l for l in pathlib.Path(out, "errors.txt").read_text().splitlines() if l.startswith("failed:")]
json.dump({
    "context": ctx, "server": server,
    "collectedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "kubectl": v(["kubectl", "version", "--client"]),
    "failedCalls": errors,
}, open(pathlib.Path(out, "manifest.json"), "w"), indent=2)
EOF

if [[ "$REDACT" -eq 1 ]]; then
  python3 "$HERE/redact.py" "$OUT"
fi

failed="$(grep -c '^failed:' "$ERR" || true)"
echo "done: $OUT ($failed calls failed, see errors.txt; missing CRDs are expected)"
echo "reminder: this directory holds cluster config; keep it out of git"
