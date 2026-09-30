import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
NAME = "kubernetes-upgrade-planner"


def run(home, *args):
    env = dict(os.environ, HOME=str(home), PATH="/usr/bin:/bin")  # no agents on PATH
    return subprocess.run([str(ROOT / "install.sh"), *args], env=env, capture_output=True, text=True, check=True).stdout


def test_default_is_claude_global_symlink(tmp_path):
    out = run(tmp_path)
    target = tmp_path / ".claude/skills" / NAME
    assert target.is_symlink() and (target / "SKILL.md").exists()
    assert "linked" in out


def test_all_agents_skip_duplicate_opencode(tmp_path):
    out = run(tmp_path, "--agent", "all", "--copy")
    assert (tmp_path / ".claude/skills" / NAME / "SKILL.md").exists()
    assert (tmp_path / ".agents/skills" / NAME / "SKILL.md").exists()
    assert not (tmp_path / ".config/opencode/skills" / NAME).exists()
    assert "skip opencode" in out
    assert not list((tmp_path / ".agents/skills" / NAME).rglob("__pycache__"))


def test_opencode_alone_and_project_scope(tmp_path):
    proj = tmp_path / "proj"
    proj.mkdir()
    run(tmp_path, "--agent", "opencode", "--project", str(proj))
    assert (proj / ".opencode/skills" / NAME / "SKILL.md").exists()
    run(tmp_path, "--agent", "codex", "--project", str(proj))
    assert (proj / ".agents/skills" / NAME / "SKILL.md").exists()
    assert not (tmp_path / ".claude/skills" / NAME).exists()


def test_dry_run_changes_nothing(tmp_path):
    out = run(tmp_path, "--agent", "all", "--dry-run")
    assert "[dry-run]" in out
    assert not (tmp_path / ".claude").exists()


def test_remove(tmp_path):
    run(tmp_path, "--agent", "all")
    env = dict(os.environ, HOME=str(tmp_path), PATH="/usr/bin:/bin")
    out = subprocess.run([str(ROOT / "uninstall.sh")], env=env, capture_output=True, text=True, check=True).stdout
    assert "removed" in out
    assert not (tmp_path / ".claude/skills" / NAME).exists()
    assert not (tmp_path / ".agents/skills" / NAME).exists()


def test_piped_install_requires_repo(tmp_path):
    env = dict(os.environ, HOME=str(tmp_path), PATH="/usr/bin:/bin")
    script = (ROOT / "install.sh").read_text()
    proc = subprocess.run(["bash", "-s", "--", "--agent", "claude"], input=script, env=env,
                          capture_output=True, text=True, cwd=tmp_path)
    assert proc.returncode != 0 and "set REPO=owner/name" in proc.stderr
