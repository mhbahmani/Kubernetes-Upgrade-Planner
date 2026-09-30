#!/usr/bin/env bash
# Node facts that kubectl can't see: cgroup version, containerd package state,
# kubelet flags, kernel cmdline. Everything the remote command runs is read-only.
#
#   node_facts.sh --print                          print the remote one-liner
#   node_facts.sh --ansible INVENTORY [--limit PATTERN] [--become] OUT_FILE
#   node_facts.sh --ssh "host1 host2 ..." OUT_FILE
#   node_facts.sh --parse RAW_FILE                 turn NODEFACT lines into JSON
set -uo pipefail

# One line per host: NODEFACT key=value ... (values have no spaces)
read -r -d '' REMOTE <<'EOF'
h=$(hostname); cg=$(stat -fc %T /sys/fs/cgroup 2>/dev/null); ctr=$(containerd --version 2>/dev/null | awk '{print $3}'); cand=$(apt-cache policy containerd 2>/dev/null | awk '/Candidate/{print $2}'); held=$(apt-mark showhold 2>/dev/null | tr '\n' ',' ); pinfra=$(grep -o 'pod-infra-container-image[^ "]*' /var/lib/kubelet/kubeadm-flags.env 2>/dev/null | tr '\n' ','); cmd=$(grep -o 'systemd.unified_cgroup_hierarchy=[0-9]' /proc/cmdline); os=$(. /etc/os-release 2>/dev/null; echo "$VERSION_ID"); echo "NODEFACT host=$h cgroup=${cg:-?} containerd=${ctr:-?} candidate=${cand:-?} held=${held:-none} podinfra=${pinfra:-none} cmdline=${cmd:-none} kernel=$(uname -r) os=${os:-?}"
EOF

case "${1:-}" in
  --print)
    printf '%s\n' "$REMOTE"
    ;;
  --ansible)
    inv="${2:?inventory required}"; shift 2
    limit="all" become=()
    while [[ $# -gt 1 ]]; do
      case "$1" in
        --limit) limit="$2"; shift 2 ;;
        --become) become=(-b); shift ;;
        *) break ;;
      esac
    done
    out="${1:?OUT_FILE required}"
    ansible "$limit" -i "$inv" "${become[@]}" -m shell -a "$REMOTE" 2>&1 | grep '^NODEFACT' > "$out"
    echo "wrote $(wc -l < "$out") hosts to $out"
    ;;
  --ssh)
    hosts="${2:?host list required}"; out="${3:?OUT_FILE required}"
    : > "$out"
    for h in $hosts; do
      ssh -o BatchMode=yes -o ConnectTimeout=10 "$h" "$REMOTE" 2>/dev/null | grep '^NODEFACT' >> "$out" \
        || echo "NODEFACT host=$h error=unreachable" >> "$out"
    done
    echo "wrote $(wc -l < "$out") hosts to $out"
    ;;
  --parse)
    python3 - "${2:?RAW_FILE required}" <<'PY'
import json, sys
rows = []
for line in open(sys.argv[1]):
    line = line.strip()
    if not line.startswith("NODEFACT"):
        continue
    row = dict(kv.split("=", 1) for kv in line.split()[1:] if "=" in kv)
    row["cgroupV2"] = row.get("cgroup") == "cgroup2fs"
    rows.append(row)
json.dump(rows, sys.stdout, indent=1)
print()
PY
    ;;
  *)
    sed -n '2,9p' "$0"; exit 2 ;;
esac
