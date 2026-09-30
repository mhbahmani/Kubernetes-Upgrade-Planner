#!/usr/bin/env bash
# Install the kubernetes-upgrade-planner skill for Claude Code, Codex and OpenCode.
#
#   ./install.sh                         global install for every agent found on PATH
#   ./install.sh --agent claude          one agent (claude | codex | opencode | all; repeatable)
#   ./install.sh --project DIR           install into DIR (project-local) instead of $HOME
#   ./install.sh --copy                  copy instead of symlink (default when not run from a clone)
#   ./install.sh --remove                uninstall (same --agent / --project selection)
#   ./install.sh --dry-run               print what would happen
#
# Without a clone (downloads the repo archive from GitHub):
#   curl -fsSL https://raw.githubusercontent.com/mhbahmani/Kubernetes-Upgrade-Planner/master/install.sh | bash
#   curl -fsSL .../install.sh | bash -s -- --agent codex --project .
# Set REPO=owner/name and REF=branch-or-tag to install from a fork or a release.
#
# Where skills go:
#   claude    ~/.claude/skills            DIR/.claude/skills
#   codex     ~/.agents/skills            DIR/.agents/skills
#   opencode  ~/.config/opencode/skills   DIR/.opencode/skills
# OpenCode also reads the claude and codex locations, so when either of those is
# installed in the same scope the OpenCode copy is skipped (OpenCode needs skill
# names to be unique).
set -euo pipefail

SKILL_NAME="kubernetes-upgrade-planner"
REPO="${REPO:-mhbahmani/Kubernetes-Upgrade-Planner}"
REF="${REF:-master}"

AGENTS=() PROJECT_DIR="" LINK="" REMOVE=0 DRY=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --agent) AGENTS+=("${2:?--agent needs a value}"); shift 2 ;;
    --global) PROJECT_DIR=""; shift ;;
    --project) PROJECT_DIR="${2:?--project needs a directory}"; shift 2 ;;
    --copy) LINK="copy"; shift ;;
    --symlink) LINK="symlink"; shift ;;
    --remove) REMOVE=1; shift ;;
    --dry-run) DRY=1; shift ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

say() { echo "$*"; }
act() { if [[ "$DRY" -eq 1 ]]; then echo "[dry-run] $*"; else "$@"; fi; }

# ---- which agents
if [[ ${#AGENTS[@]} -eq 0 ]]; then
  for a in claude codex opencode; do command -v "$a" >/dev/null 2>&1 && AGENTS+=("$a"); done
  [[ ${#AGENTS[@]} -gt 0 ]] || AGENTS=(claude)
fi
if [[ " ${AGENTS[*]} " == *" all "* ]]; then AGENTS=(claude codex opencode); fi
for a in "${AGENTS[@]}"; do
  case "$a" in claude|codex|opencode) ;; *) echo "unknown agent: $a" >&2; exit 2 ;; esac
done

if [[ -n "$PROJECT_DIR" ]]; then
  [[ -d "$PROJECT_DIR" ]] || { echo "error: $PROJECT_DIR is not a directory" >&2; exit 1; }
  BASE="$(cd "$PROJECT_DIR" && pwd)"
  dir_for() { case "$1" in claude) echo "$BASE/.claude/skills" ;; codex) echo "$BASE/.agents/skills" ;; opencode) echo "$BASE/.opencode/skills" ;; esac; }
else
  dir_for() { case "$1" in claude) echo "$HOME/.claude/skills" ;; codex) echo "$HOME/.agents/skills" ;; opencode) echo "$HOME/.config/opencode/skills" ;; esac; }
fi

has_agent() { [[ " ${AGENTS[*]} " == *" $1 "* ]]; }

# ---- remove
if [[ "$REMOVE" -eq 1 ]]; then
  removed=0
  for a in "${AGENTS[@]}"; do
    target="$(dir_for "$a")/$SKILL_NAME"
    if [[ -e "$target" || -L "$target" ]]; then
      act rm -rf "$target"; say "removed $target ($a)"; removed=1
    fi
  done
  [[ "$removed" -eq 1 ]] || say "nothing to remove"
  exit 0
fi

# ---- find the skill source: this clone, or download the repo archive
SELF="${BASH_SOURCE[0]:-}"
HERE=""
[[ -n "$SELF" && -f "$SELF" ]] && HERE="$(cd "$(dirname "$SELF")" && pwd)"
if [[ -n "$HERE" && -f "$HERE/skills/$SKILL_NAME/SKILL.md" ]]; then
  SRC="$HERE/skills/$SKILL_NAME"
  LINK="${LINK:-symlink}"
else
  say "# no local checkout; downloading github.com/$REPO ($REF)"
  [[ "$REPO" != OWNER/* ]] || { echo "error: set REPO=owner/name (the GitHub repo to install from)" >&2; exit 1; }
  TMP="$(mktemp -d)"
  trap 'rm -rf "$TMP"' EXIT
  curl -fsSL "https://codeload.github.com/$REPO/tar.gz/$REF" -o "$TMP/repo.tar.gz" \
    || { echo "error: download failed" >&2; exit 1; }
  tar -xzf "$TMP/repo.tar.gz" -C "$TMP"
  SRC="$(find "$TMP" -maxdepth 4 -type f -path "*/skills/$SKILL_NAME/SKILL.md" -print -quit)"
  [[ -n "$SRC" ]] || { echo "error: unexpected archive layout" >&2; exit 1; }
  SRC="$(dirname "$SRC")"
  LINK="copy"  # the temp dir goes away
fi

# ---- install
installed=()
for a in "${AGENTS[@]}"; do
  if [[ "$a" == "opencode" ]] && { has_agent claude || has_agent codex; }; then
    say "skip opencode: it already reads $(dir_for claude) and $(dir_for codex)"
    continue
  fi
  dest_dir="$(dir_for "$a")"
  target="$dest_dir/$SKILL_NAME"
  act mkdir -p "$dest_dir"
  if [[ -e "$target" || -L "$target" ]]; then
    act rm -rf "$target"
  fi
  if [[ "$LINK" == "symlink" ]]; then
    act ln -s "$SRC" "$target"
    say "linked $target -> $SRC ($a)"
  else
    act cp -R "$SRC" "$target"
    act find "$target" -name __pycache__ -type d -prune -exec rm -rf {} +
    say "copied to $target ($a)"
  fi
  installed+=("$a")
done

# ---- dependency hints (warnings only)
python3 -c 'import yaml' 2>/dev/null || say "warning: python3 with PyYAML is required (pip install pyyaml)"
for bin in kubectl jq curl; do command -v "$bin" >/dev/null 2>&1 || say "warning: $bin not found on PATH"; done
say "done (${installed[*]:-nothing}). Start a new agent session to pick up the skill."
