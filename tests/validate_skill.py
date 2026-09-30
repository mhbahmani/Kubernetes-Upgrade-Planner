#!/usr/bin/env python3
"""Check a skill folder against the Agent Skills spec and our own rules.

    validate_skill.py skills/<name>
"""
import pathlib
import re
import sys

import yaml

ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}


def main() -> int:
    root = pathlib.Path(sys.argv[1])
    text = (root / "SKILL.md").read_text()
    errors = []
    m = re.match(r"^---\n(.*?)\n---\n(.*)$", text, re.S)
    if not m:
        print("error: SKILL.md has no frontmatter")
        return 1
    meta, body = yaml.safe_load(m.group(1)), m.group(2)
    name = meta.get("name", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append(f"name {name!r} must be lowercase words joined by single hyphens, max 64 chars")
    if name != root.name:
        errors.append(f"name {name!r} must match the folder name {root.name!r}")
    if "claude" in name or "anthropic" in name:
        errors.append("name must not contain 'claude' or 'anthropic'")
    desc = meta.get("description", "")
    if not 1 <= len(desc) <= 1024:
        errors.append(f"description must be 1-1024 chars (has {len(desc)})")
    if len(meta.get("compatibility", "")) > 500:
        errors.append("compatibility must be at most 500 chars")
    extra = set(meta) - ALLOWED
    if extra:
        errors.append(f"non-standard frontmatter fields (not portable): {sorted(extra)}")
    if isinstance(meta.get("metadata"), dict) and not all(isinstance(v, str) for v in meta["metadata"].values()):
        errors.append("metadata values must be strings")
    lines = body.count("\n")
    if lines > 500:
        errors.append(f"SKILL.md body has {lines} lines; keep it under 500")
    for link in re.findall(r"\]\(((?:references|scripts|assets|data)/[^)#]+)\)", body):
        if not (root / link).exists():
            errors.append(f"broken link: {link}")
        if link.count("/") > 1:
            errors.append(f"reference nested more than one level: {link}")
    for script in re.findall(r"scripts/([\w.-]+\.(?:py|sh))", body):
        if not (root / "scripts" / script).exists():
            errors.append(f"SKILL.md mentions missing script: scripts/{script}")
    if "\\" in "".join(re.findall(r"`[^`]*`", body)).replace("\\\n", ""):
        errors.append("use forward slashes in paths")
    for e in errors:
        print(f"error: {e}")
    print("skill ok" if not errors else f"{len(errors)} error(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
