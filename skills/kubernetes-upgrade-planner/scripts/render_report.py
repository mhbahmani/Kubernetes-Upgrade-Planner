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
        current = path[0] if path else None
        targets = {str(p.get("until")) for p in meta.get("phases") or []}
        body = []
        for r in f["support"]:
            m = str(r.get("minor"))
            tags = ('<span class="chip now">current</span>' if m == current else "") + \
                   ('<span class="chip tgt">target</span>' if m in targets else "")
            cls = " ".join(c for c in ("eol" if r.get("isEol") else "", "current" if m == current else "") if c)
            cells = [f'<span class="minor">{esc(m)}</span>{tags}', esc(r.get("released")), esc(r.get("eol")),
                     esc(r.get("latest")), chip("blocker").replace("Blocker", "EOL") if r.get("isEol") else chip("ok").replace("OK", "Supported"),
                     f'<a href="{esc(changelog(r))}">CHANGELOG-{esc(m)}</a>']
            body.append(f'<tr class="{cls}">' + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
        head = "".join(f"<th>{h}</th>" for h in ["Minor", "Released", "EOL", "Latest patch", "Status", "Release notes"])
        section("support", "Kubernetes support window",
                f'<div class="tbl"><table class="support"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>',
                "From endoflife.date. Red rows are past end of life. kubeadm and Kubespray upgrade one minor at a time; read the urgent upgrade notes of every minor on the path.")

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
    if matrix.get("rows") or f.get("sequence"):
        inner = ""
        if matrix.get("rows"):
            hops_m = matrix.get("hops") or path
            stages, last = hops_m[:-1], hops_m[-1]
            head = [f"On {h} (before hop to {n})" if i == 0 else f"On {h}"
                    for i, (h, n) in enumerate(zip(stages, hops_m[1:]))]
            rows = []
            for r in matrix["rows"]:
                label = esc(r.get("component"))
                if r.get("clusters"):
                    label += f'<br><small>{esc(", ".join(r["clusters"]))}</small>'
                cells = [pipeline_cell((r.get("cells") or {}).get(h), (r.get("steps") or {}).get(h)) for h in stages]
                why = esc(r.get("why") or _rule(r.get("rule"))) + refs_html(r.get("refs"))
                rows.append([f'<span class="name">{label}</span>'] + cells
                            + [f'<span class="v">{esc(r.get("final") or r.get("status"))}</span>', why])
            inner += table(["Component"] + head + [last, "Why, and upgrade-path rule"], rows, "matrix")
        if f.get("sequence"):
            inner += "<h3>Before and between hops</h3>" + '<ol class="steps">' + "".join(
                f'<li><b>{esc(s_.get("title"))}</b><ul>' + "".join(f"<li>{esc(i)}</li>" for i in s_.get("items") or [])
                + "</ul></li>" for s_ in f["sequence"]) + "</ol>"
        section("sequence", "Upgrade sequence", inner,
                "Read each row left to right. A shaded cell is a step to finish while the cluster is on that minor, before the next hop; the bold version is where the step ends. Every version stays inside its supported range on both sides of every hop.")

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


def changelog(row: dict) -> str:
    return row.get("changelog") or f'https://github.com/kubernetes/kubernetes/blob/master/CHANGELOG/CHANGELOG-{row.get("minor")}.md'


def pipeline_cell(cell: dict | None, text: str | None) -> str:
    """One stage of a pipeline row: '3.29 → 3.30 → **3.31**' or '→ **3.32**'."""
    if not cell and not text:
        return ""
    if cell and "gap" in cell or (text and str(text).startswith("GAP")):
        msg = cell["gap"] if cell and "gap" in cell else str(text)[5:]
        return f'<span class="gap" title="{esc(msg)}">no supported version</span><br><small>{esc(msg)}</small>'
    if not cell:  # hand-written findings may only have text
        return f'<span class="stepv">{esc(text)}</span>'
    chain = ([cell["from"]] if cell.get("first") else [""]) + cell.get("via", [])
    body = " → ".join(esc(v) for v in chain).lstrip() + f' → <b>{esc(cell["to"])}</b>'
    return f'<span class="stepv">{body.strip()}</span>'


def pipeline_md(cell: dict | None, text: str | None) -> str:
    if not cell and not text:
        return ""
    if cell and "gap" in cell:
        return "⛔ " + cell["gap"]
    if not cell:
        return str(text)
    chain = ([cell["from"]] if cell.get("first") else [""]) + cell.get("via", [])
    return (" → ".join(chain) + f' → **{cell["to"]}**').strip()


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
table.matrix td { white-space: normal; min-width: 7.5em; }
table.matrix td:has(.stepv), table.matrix td:has(.gap) { background: var(--accent-soft); }
table.matrix td:has(.gap) { background: var(--block-bg); }
table.matrix .stepv, table.matrix span.v { font-family: var(--f-mono); font-size: 0.82rem; }
table.matrix span.gap { color: var(--block); font-weight: 600; font-size: 0.8rem; }
table.matrix small { color: var(--muted); }
table.support tr.eol td { background: color-mix(in srgb, var(--block-bg) 75%, transparent); }
table.support tr.eol td:first-child { box-shadow: inset 3px 0 0 var(--block); }
table.support tr.current td:first-child .minor { font-weight: 700; color: var(--accent); }
table.support .minor { font-family: var(--f-mono); margin-right: 8px; }
table.support .chip { margin-right: 4px; }
.chip.now { color: var(--accent); background: var(--accent-soft); }
.chip.tgt { color: var(--ok); background: var(--ok-bg); }
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
        out += ["## Kubernetes support window", "", md_table(["Minor", "Released", "EOL", "Latest", "Status", "Release notes"],
                [[(f'**{r.get("minor")}** (current)' if path and r.get("minor") == path[0] else str(r.get("minor")))
                  + (" (target)" if str(r.get("minor")) in {str(p.get("until")) for p in meta.get("phases") or []} else ""),
                  r.get("released"), r.get("eol"), r.get("latest"), "⛔ EOL" if r.get("isEol") else "supported",
                  f'[CHANGELOG-{r.get("minor")}]({changelog(r)})'] for r in f["support"]]), ""]
    if f.get("nodeLayer"):
        out += ["## Node layer", "", md_table(["Item", "Current", "Problem", "Action", "Needed by", "Sources"],
                [[r.get("item"), r.get("current"), r.get("problem"), r.get("action"), f'{LABEL.get(r.get("severity"), "")} {r.get("neededBy") or ""}', refs_md(r.get("refs"))] for r in f["nodeLayer"]]), ""]
    if f.get("components"):
        phases = [p.get("name") for p in meta.get("phases") or []] or ["Target"]
        out += ["## Components", "", md_table(["Component"] + clusters + phases + ["Priority", "Why", "Sources"],
                [[r.get("name")] + [(r.get("current") or {}).get(c, "—") for c in clusters] + [(r.get("targets") or {}).get(p, "") for p in phases]
                 + [LABEL.get(r.get("severity"), ""), r.get("notes"), refs_md(r.get("refs"))] for r in f["components"]]), ""]
    matrix = f.get("matrix") or {}
    if matrix.get("rows") or f.get("sequence"):
        out += ["## Upgrade sequence", ""]
        if matrix.get("rows"):
            hops = matrix.get("hops") or path
            stages, last = hops[:-1], hops[-1]
            head = [f"On {h} (before hop to {n})" if i == 0 else f"On {h}" for i, (h, n) in enumerate(zip(stages, hops[1:]))]
            out += ["Read each row left to right: a step is finished while the cluster is on that minor, before the next hop.", "",
                    md_table(["Component"] + head + [last, "Why, and upgrade-path rule"],
                             [[r.get("component") + (f' ({", ".join(r.get("clusters") or [])})' if r.get("clusters") else "")]
                              + [pipeline_md((r.get("cells") or {}).get(h), (r.get("steps") or {}).get(h)) for h in stages]
                              + [str(r.get("final") or r.get("status")), f'{r.get("why") or _rule(r.get("rule"))} {refs_md(r.get("refs"))}']
                              for r in matrix["rows"]]), ""]
        if f.get("sequence"):
            out += ["### Before and between hops", ""]
            for n, s_ in enumerate(f["sequence"], 1):
                out += [f'{n}. **{s_.get("title")}**'] + [f"   - {i}" for i in s_.get("items") or []]
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
