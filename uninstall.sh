#!/usr/bin/env bash
# Remove the kubernetes-upgrade-planner skill. Takes the same --agent / --project
# options as install.sh; without them it removes the global install for all agents.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
args=("$@")
[[ " ${args[*]:-} " == *" --agent "* ]] || args+=(--agent all)
exec "$HERE/install.sh" --remove "${args[@]}"
