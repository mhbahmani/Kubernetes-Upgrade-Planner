import json
import pathlib

import yaml

from conftest import SCRIPTS, load

rr = load("render_report")
ph = load("plan_hops")
cc = load("check_compat")
EXAMPLE = json.loads((SCRIPTS.parent / "assets" / "example-findings.json").read_text())


def test_example_matches_schema_shape():
    schema = json.loads((SCRIPTS.parent / "assets" / "findings.schema.json").read_text())
    for key in schema["required"]:
        assert key in EXAMPLE


def test_example_passes_validation(tmp_path):
    catalog = yaml.safe_load(open(SCRIPTS.parent / "data" / "components.yaml"))["components"]
    curated = yaml.safe_load(open(SCRIPTS.parent / "data" / "compat.yaml"))
    cc.fetch = lambda url, cache, offline: (None, {"source": "none"})
    compat = {"projects": cc.merge(catalog, curated, list(curated["projects"]), tmp_path, True)}
    assert ph.validate(EXAMPLE, compat) == []


def test_render_both_formats(tmp_path):
    md = rr.render_md(EXAMPLE)
    page = rr.render_html(EXAMPLE)
    frag = rr.render_html(EXAMPLE, fragment=True)
    for heading in ("## Summary", "## Upgrade sequence", "## Components", "## Node layer", "## Kubernetes support window"):
        assert heading in md
    assert page.startswith("<!doctype html>") and "</html>" in page
    assert "<html" not in frag and frag.startswith("<title>")
    assert 'id="sequence"' in page and 'class="tbl"' in page and "CHANGELOG-1.33" in page
    assert "Release notes that affect" not in page and "<b>1.19</b>" in page
    for row in EXAMPLE["matrix"]["rows"]:
        assert row["component"] in page and row["component"] in md


def test_render_escapes_html():
    f = {"meta": {"title": "<script>x</script>", "date": "2026-01-01", "path": ["1.31", "1.32"]},
         "summary": [{"severity": "ok", "title": "a & b", "text": "<b>"}], "components": [], "matrix": {"rows": []}}
    page = rr.render_html(f)
    assert "<script>x" not in page and "&lt;script&gt;" in page and "a &amp; b" in page


def test_support_rows_mark_current_target_and_eol():
    f = {"meta": {"title": "t", "date": "2026-01-01", "path": ["1.31", "1.32", "1.33"],
                  "phases": [{"name": "Phase 1", "until": "1.33"}]},
         "support": [{"minor": "1.31", "isEol": True}, {"minor": "1.32", "isEol": False}, {"minor": "1.33", "isEol": False}],
         "components": [], "matrix": {"rows": []}}
    page = rr.render_html(f)
    assert '<tr class="eol current">' in page and 'class="chip now">current' in page
    assert 'class="chip tgt">target' in page and '<tr class="">' in page
    md = rr.render_md(f)
    assert "**1.31** (current)" in md and "1.33 (target)" in md and "⛔ EOL" in md
