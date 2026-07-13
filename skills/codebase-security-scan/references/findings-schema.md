# findings.json schema

A machine-readable index of the current security findings, written **alongside**
the prose report at `knowledge-base/security/codebase-security/findings.json`
whenever a report is generated or updated. It lets other skills (e.g.
`/freya-devkit:status`) read findings without parsing prose. Git-tracked.

```json
{
  "version": 1,
  "scanned_commit": "<git HEAD short hash at scan time>",
  "report": "knowledge-base/security/codebase-security/<YYYY-MM-DD>.md",
  "findings": [
    {
      "id": "SEC-001",
      "title": "Short finding title",
      "severity": "high | medium | low | info",
      "status": "open | resolved | intentional",
      "file": "src/path/to/file.ts",
      "line": 42,
      "spec_ref": "SPEC-001",
      "behavior_ref": "BEH-003"
    }
  ]
}
```

Field rules:
- `id` — stable per finding across re-scans (matches the prose report's finding id).
- `severity` — one of `high`/`medium`/`low`/`info`.
- `status`:
  - `open` — a live finding needing attention.
  - `resolved` — fixed/no longer present (lifecycle RESOLVED).
  - `intentional` — explained by intent, so not outstanding. Either a declarative
    spec decision (`spec_ref` names the spec — a prose claim) **or** an `accepted`,
    test-backed behavior whose intent explains it (`behavior_ref` names the behavior
    — a *verified guarantee*, the stronger evidence). A finding may carry both.
- `file` / `line` — primary location (`line` optional).
- `spec_ref` — the declarative spec marking it intentional, when known (optional).
- `behavior_ref` — the `accepted` behavior (`BEH-NNN`) whose verified intent explains
  the finding, when known (optional). A behavior-explained finding is the strongest
  "intentional" evidence (test-backed, not a prose claim).

Consumers treat any finding whose `status` is not `open` as not outstanding.
The list mirrors the prose report's findings exactly — same ids, same statuses.
