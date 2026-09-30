# findings.json

`render_report.py` turns this into report.md and report.html.
`plan_hops.py --validate` checks it. Start from `assets/example-findings.json`.
The full schema is `assets/findings.schema.json`.

## Top-level keys
| Key | Content |
|---|---|
| `meta` | `title`, `subtitle`, `date` (YYYY-MM-DD), `clusters` (names), `path` (list of minors, e.g. `["1.31","1.32","1.33","1.34","1.35","1.36"]`), `phases` (e.g. `[{"name":"Phase 1","until":"1.33"}]`) |
| `summary` | list of `{severity, title, text}` (severity: `blocker`, `required`, `recommended`, `ok`) |
| `snapshot` | list of `{item, values: {cluster: text}}` rows from the collected data |
| `support` | from eol.json: `{minor, released, eol, latest, isEol, changelog}` (the changelog link is shown in the table) |
| `nodeLayer` | `{item, current, problem, action, neededBy, severity, refs}` |
| `components` | `{name, current: {cluster: version}, targets: {phase: version}, severity, notes, refs}` |
| `matrix` | from plan.json: `{hops, rows: [{component, clusters, cells, steps, final, why, rule, refs}]}`. Rendered as the **Upgrade sequence** table: one row per component, one column per minor, shaded cells for steps. `cells[minor]` is `{from, via, to, first}` or `{gap}`; `why` is plain text you may rewrite |
| `sequence` | preparation and between-hop steps that are not component versions: `{title, items: [...]}` in order, shown under the table |
| `verify` | what is still unverified |
| `references` | `{group, items: [{title, url}]}` |

## Evidence rules (checked by --validate)
- Every `components[]` and `nodeLayer[]` row has at least one `refs[]` entry `{title, url}`.
- Every `matrix.rows[]` row has `refs`, and each version in `steps` is inside
  its range in compat.json at that minor.
- `meta.path` goes one minor at a time.
- No `ok` severity on a component whose current version is EOL or out of range.
- Put the check date in `meta.date`. Ranges taken from compat.json keep their
  own `lastVerified`.

Release notes don't get their own section. Put each changelog item that
matches the collected data into `nodeLayer` or `summary`, with the changelog as
its ref. The support window table links every minor's changelog.

## Writing style
Short, direct sentences. Name things by what the reader recognises. For each
problem, say what goes wrong and what to do. Don't add generic advice that
doesn't come from the collected data.
