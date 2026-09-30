#!/usr/bin/env python3
"""Render findings.json to report.md and report.html from the same data.

    render_report.py findings.json [--out DIR]

Writes:
  report.md             Markdown
  report.html           standalone page (open locally)
  report.fragment.html  the same page without <html>/<head>/<body>, for tools
                        that wrap content themselves (e.g. Claude's Artifact tool)
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib

SKILL = pathlib.Path(__file__).resolve().parents[1]
CHIP = {"blocker": "block", "required": "req", "recommended": "rec", "ok": "ok"}
LABEL = {"blocker": "Blocker", "required": "Required", "recommended": "Recommended", "ok": "OK"}


def esc(value) -> str:
    return html.escape("" if value is None else str(value))


def md_esc(value) -> str:
    return ("" if value is None else str(value)).replace("|", "\\|").replace("\n", " ")


def refs_html(refs) -> str:
    if not refs:
        return ""
    links = "".join(f'<a href="{esc(r.get("url"))}">{esc(r.get("title") or r.get("url"))}</a>' for r in refs)
    return f'<span class="refs">{links}</span>'


def refs_md(refs) -> str:
    return " ".join(f'[{md_esc(r.get("title") or "source")}]({r.get("url")})' for r in refs or [])


def chip(sev) -> str:
    if not sev:
        return ""
    return f'<span class="chip {CHIP.get(sev, "rec")}">{esc(LABEL.get(sev, sev))}</span>'


def clusters_of(f: dict) -> list[str]:
    return (f.get("meta") or {}).get("clusters") or []


# ---------------------------------------------------------------- HTML parts
def table(headers: list[str], rows: list[list[str]], cls: str = "") -> str:
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>" + "".join(f"<td>{c}</td>" for c in r) + "</tr>" for r in rows)
    return f'<div class="tbl"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'


def html_body(f: dict) -> str:
    meta = f.get("meta") or {}
    clusters = clusters_of(f)
    path = meta.get("path") or []
    out = []
    sections = []

    def section(sid: str, title: str, inner: str, lede: str = "") -> None:
        if inner:
            sections.append((sid, title))
            p = f"<p>{esc(lede)}</p>" if lede else ""
            out.append(f'<section id="{sid}"><h2>{esc(title)}</h2>{p}{inner}</section>')

    # summary
    hops = "".join(
        f'<div class="hop {"now" if i == 0 else ("phase1" if _phase(meta, m) == 0 else "phase2")}" role="listitem">'
        f'<span class="eyebrow">{"Now" if i == 0 else esc(_phase_name(meta, m))}</span>'
        f'<span class="v">{esc(m)}</span><span class="d">{esc(_eol_of(f, m))}</span></div>'
        for i, m in enumerate(path))
    cards = "".join(
        f'<div class="finding">{chip(s.get("severity"))}<h3>{esc(s.get("title"))}</h3><p>{esc(s.get("text"))}</p></div>'
        for s in f.get("summary") or [])
    section("summary", "Summary",
            (f'<div class="path" role="list">{hops}</div>' if hops else "") + (f'<div class="findings">{cards}</div>' if cards else ""))

    if f.get("snapshot"):
        rows = [[f'<span class="name">{esc(r.get("item"))}</span>'] + [esc((r.get("values") or {}).get(c, "")) for c in clusters]
                for r in f["snapshot"]]
        section("snapshot", "Cluster snapshot", table(["Item"] + clusters, rows))

    if f.get("support"):
        rows = [[esc(r.get("minor")), esc(r.get("released")), esc(r.get("eol")), esc(r.get("latest")),
                 chip("blocker") if r.get("isEol") else chip("ok")] for r in f["support"]]
        section("support", "Kubernetes support window", table(["Minor", "Released", "EOL", "Latest patch", "Status"], rows),
                "From endoflife.date. kubeadm and Kubespray upgrade one minor at a time.")

    if f.get("nodeLayer"):
        rows = [[f'<span class="name">{esc(r.get("item"))}</span>', esc(r.get("current")), esc(r.get("problem")),
                 esc(r.get("action")) + refs_html(r.get("refs")), chip(r.get("severity")) + f' {esc(r.get("neededBy"))}']
                for r in f["nodeLayer"]]
        section("nodes", "Node layer", table(["Item", "Current", "Problem", "Action", "Needed by"], rows))

    if f.get("components"):
        phases = [p.get("name") for p in meta.get("phases") or []] or ["Target"]
        rows = [[f'<span class="name">{esc(r.get("name"))}</span>']
                + [esc((r.get("current") or {}).get(c, "—")) for c in clusters]
                + [esc((r.get("targets") or {}).get(p, "")) for p in phases]
                + [chip(r.get("severity")), esc(r.get("notes")) + refs_html(r.get("refs"))]
                for r in f["components"]]
        section("components", "Components", table(["Component"] + clusters + phases + ["Priority", "Why"], rows))

    matrix = f.get("matrix") or {}
    if matrix.get("rows"):
        hops_m = matrix.get("hops") or path
        rows = []
        for r in matrix["rows"]:
            cells = []
            for h in hops_m:
                text = (r.get("steps") or {}).get(h, "")
                cls = "gap" if str(text).startswith("GAP") else ("step" if text else "")
                cells.append(f'<span class="{cls}">{esc(text)}</span>' if text else "")
            label = esc(r.get("component")) + (f'<br><small>{esc(", ".join(r.get("clusters") or []))}</small>' if r.get("clusters") else "")
            rows.append([f'<span class="name">{label}</span>', esc(r.get("current"))] + cells
                        + [esc(r.get("final") or r.get("status")), esc(_rule(r.get("rule"))) + refs_html(r.get("refs"))])
        section("path", "Versions at each hop", table(["Component", "Now"] + [f"On {h}" for h in hops_m] + ["Final", "Rule"], rows, "matrix"),
                "Each step must be done while the cluster is on the minor shown, before the next hop. Every version stays inside its supported range on both sides of every hop.")

    if f.get("releaseNotes"):
        cards = "".join(
            f'<article><div class="relhead"><h3>{esc(r.get("minor"))}</h3>'
            f'<a class="src" href="{esc(r.get("src"))}">changelog</a></div><ul>'
            + "".join(f'<li class="hot">{esc(i)}</li>' for i in r.get("hot") or [])
            + "".join(f"<li>{esc(i)}</li>" for i in r.get("items") or []) + "</ul></article>"
            for r in f["releaseNotes"])
        section("k8s", "Release notes that affect these clusters", f'<div class="rel">{cards}</div>')

    if f.get("sequence"):
        items = "".join(f'<li><b>{esc(s.get("title"))}</b><ul>' + "".join(f"<li>{esc(i)}</li>" for i in s.get("items") or [])
                        + "</ul></li>" for s in f["sequence"])
        section("sequence", "Upgrade sequence", f'<ol class="steps">{items}</ol>')

    if f.get("verify"):
        section("verify", "Still to verify", '<ul class="reflist">' + "".join(f"<li>{esc(v)}</li>" for v in f["verify"]) + "</ul>")

    if f.get("references"):
        groups = "".join(f'<div><h3>{esc(g.get("group"))}</h3><ul class="reflist">'
                         + "".join(f'<li><a href="{esc(i.get("url"))}">{esc(i.get("title"))}</a></li>' for i in g.get("items") or [])
                         + "</ul></div>" for g in f["references"])
        section("refs", "References", f'<div class="cols">{groups}</div>')

    nav = "".join(f'<a href="#{sid}">{esc(t)}</a>' for sid, t in sections)
    head = (f'<header><span class="eyebrow">{esc(meta.get("eyebrow", "Upgrade assessment"))}</span>'
            f'<h1>{esc(meta.get("title", "Kubernetes upgrade plan"))}</h1>'
            + (f'<p class="lede">{esc(meta.get("subtitle"))}</p>' if meta.get("subtitle") else "")
            + '<div class="meta">' + "".join(f"<span>{esc(m)}</span>" for m in meta.get("facts") or [])
            + f'<span>Assessed <b>{esc(meta.get("date"))}</b></span></div>'
            + f'<nav class="toc" aria-label="Sections">{nav}</nav></header>')
    foot = f'<footer>{esc(meta.get("footer", "Generated by the kubernetes-upgrade-planner skill from read-only data."))}</footer>'
    return f'<div class="wrap">{head}{"".join(out)}{foot}</div>'


def _phase(meta: dict, minor: str) -> int:
    for i, p in enumerate(meta.get("phases") or []):
        if tuple(map(int, minor.split("."))) <= tuple(map(int, str(p.get("until", "99.99")).split("."))):
            return i
    return len(meta.get("phases") or [])


def _phase_name(meta: dict, minor: str) -> str:
    phases = meta.get("phases") or []
    i = _phase(meta, minor)
    return phases[i]["name"] if i < len(phases) else "Target"


def _eol_of(f: dict, minor: str) -> str:
    for r in f.get("support") or []:
        if r.get("minor") == minor:
            return f'EOL {r.get("eol")}' if r.get("eol") else ""
    return ""


def _rule(rule) -> str:
    if rule in (None, "any"):
        return "no documented path rule"
    if isinstance(rule, dict):
        if "maxMinorStep" in rule:
            return "one minor at a time" if rule["maxMinorStep"] == 1 else f'up to {rule["maxMinorStep"]} minors per step'
        if "maxMajorStep" in rule:
            return "within a major or to the next one"
    return str(rule)


EXTRA_CSS = """
table.matrix td { white-space: normal; min-width: 7em; }
table.matrix span.step { display: inline-block; background: var(--accent-soft); padding: 2px 6px; border-radius: 3px; font-family: var(--f-mono); font-size: 0.8rem; }
table.matrix span.gap { display: inline-block; color: var(--block); background: var(--block-bg); padding: 2px 6px; border-radius: 3px; font-size: 0.8rem; }
.rel .relhead { display: flex; justify-content: space-between; align-items: baseline; gap: 8px; }
span.name { font-weight: 600; }
"""


def render_html(f: dict, fragment: bool = False) -> str:
    css = (SKILL / "assets" / "report.css").read_text() + EXTRA_CSS
    title = esc((f.get("meta") or {}).get("title", "Kubernetes upgrade plan"))
    head = (f"<title>{title}</title>\n"
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500'
            '&family=IBM+Plex+Sans+Condensed:wght@500;600;700&family=IBM+Plex+Sans:wght@400;500;600&display=swap">\n'
            f"<style>\n{css}</style>\n")
    body = html_body(f)
    if fragment:
        return f"{head}{body}\n"
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">\n'
            f"{head}</head>\n<body>\n{body}\n</body>\n</html>\n")


# ------------------------------------------------------------------- Markdown
def md_table(headers: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
    lines += ["| " + " | ".join(md_esc(c) if not str(c).startswith("[") else str(c) for c in r) + " |" for r in rows]
    return "\n".join(lines)


def render_md(f: dict) -> str:
    meta = f.get("meta") or {}
    clusters = clusters_of(f)
    path = meta.get("path") or []
    out = [f'# {meta.get("title", "Kubernetes upgrade plan")}', ""]
    if meta.get("subtitle"):
        out += [meta["subtitle"], ""]
    out += [" · ".join((meta.get("facts") or []) + [f'Assessed {meta.get("date")}']), ""]
    if path:
        out += ["**Path:** " + " → ".join(path), ""]
    if f.get("summary"):
        out += ["## Summary", ""] + [f'- **{LABEL.get(s.get("severity"), "")}: {s.get("title")}** {s.get("text")}' for s in f["summary"]] + [""]
    if f.get("snapshot"):
        out += ["## Cluster snapshot", "", md_table(["Item"] + clusters, [[r.get("item")] + [(r.get("values") or {}).get(c, "") for c in clusters] for r in f["snapshot"]]), ""]
    if f.get("support"):
        out += ["## Kubernetes support window", "", md_table(["Minor", "Released", "EOL", "Latest", "Status"],
                [[r.get("minor"), r.get("released"), r.get("eol"), r.get("latest"), "EOL" if r.get("isEol") else "supported"] for r in f["support"]]), ""]
    if f.get("nodeLayer"):
        out += ["## Node layer", "", md_table(["Item", "Current", "Problem", "Action", "Needed by", "Sources"],
                [[r.get("item"), r.get("current"), r.get("problem"), r.get("action"), f'{LABEL.get(r.get("severity"), "")} {r.get("neededBy") or ""}', refs_md(r.get("refs"))] for r in f["nodeLayer"]]), ""]
    if f.get("components"):
        phases = [p.get("name") for p in meta.get("phases") or []] or ["Target"]
        out += ["## Components", "", md_table(["Component"] + clusters + phases + ["Priority", "Why", "Sources"],
                [[r.get("name")] + [(r.get("current") or {}).get(c, "—") for c in clusters] + [(r.get("targets") or {}).get(p, "") for p in phases]
                 + [LABEL.get(r.get("severity"), ""), r.get("notes"), refs_md(r.get("refs"))] for r in f["components"]]), ""]
    matrix = f.get("matrix") or {}
    if matrix.get("rows"):
        hops = matrix.get("hops") or path
        out += ["## Versions at each hop", "", "Do each step while the cluster is on the minor shown, before the next hop.", "",
                md_table(["Component", "Now"] + [f"On {h}" for h in hops] + ["Final", "Rule", "Sources"],
                         [[r.get("component") + (f' ({", ".join(r.get("clusters") or [])})' if r.get("clusters") else ""), r.get("current")]
                          + [(r.get("steps") or {}).get(h, "") for h in hops] + [r.get("final") or r.get("status"), _rule(r.get("rule")), refs_md(r.get("refs"))]
                          for r in matrix["rows"]]), ""]
    if f.get("releaseNotes"):
        out += ["## Release notes that affect these clusters", ""]
        for r in f["releaseNotes"]:
            out += [f'### {r.get("minor")} ([changelog]({r.get("src")}))', ""] + [f"- **{i}**" for i in r.get("hot") or []] + [f"- {i}" for i in r.get("items") or []] + [""]
    if f.get("sequence"):
        out += ["## Upgrade sequence", ""]
        for n, s in enumerate(f["sequence"], 1):
            out += [f'{n}. **{s.get("title")}**'] + [f"   - {i}" for i in s.get("items") or []]
        out += [""]
    if f.get("verify"):
        out += ["## Still to verify", ""] + [f"- {v}" for v in f["verify"]] + [""]
    if f.get("references"):
        out += ["## References", ""]
        for g in f["references"]:
            out += [f'**{g.get("group")}**', ""] + [f'- [{i.get("title")}]({i.get("url")})' for i in g.get("items") or []] + [""]
    return "\n".join(out).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("findings")
    ap.add_argument("--out", default=".")
    args = ap.parse_args()
    f = json.load(open(args.findings))
    out = pathlib.Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(render_md(f))
    (out / "report.html").write_text(render_html(f))
    (out / "report.fragment.html").write_text(render_html(f, fragment=True))
    print(f"wrote {out / 'report.md'}, {out / 'report.html'}, {out / 'report.fragment.html'}")


if __name__ == "__main__":
    main()
