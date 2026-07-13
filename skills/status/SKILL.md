---
name: status
description: |
  Read-only project status: aggregate outstanding behavior/coverage/security work
  (behaviors to confirm, tests owed, coverage gaps, open security findings) and
  refresh the git-tracked knowledge-base/BACKLOG.md. The check-counterpart of wrap-up.

  TRIGGER when: asking "where do I stand", "what's outstanding", "what's left to do",
  refreshing the backlog, or working the intent/test-owed worklists.
---

# Status

The read-only **check** counterpart of `/freya-devkit:wrap-up` (which *does/syncs*).
`status` mutates nothing except, on request, the generated `knowledge-base/BACKLOG.md`.

## Commands

| Command | Description |
|---------|-------------|
| `status` | Print the status summary and refresh `BACKLOG.md` |
| `status` (summary only) | Print the summary without rewriting `BACKLOG.md` — run `collect_status.py` and omit `--write-backlog` |
| `gaps` | List whole-repo uncovered source files |
| `review intent` | Work the proposed → confirm worklist, one at a time |
| `review tests` | Work the confirmed → write-a-test worklist, one at a time |

### `status`

Run the aggregator and refresh the backlog:
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/status/scripts/collect_status.py" \
  --project . --format text --write-backlog
```
It reports a census (`proposed / confirmed / accepted / quarantined / deprecated`),
the two worklist sizes, coverage gaps, Tier-1 verify failures, stale fingerprints,
and open security findings — each source degrades to a `note` if unavailable, and
the command never blocks. It (re)writes `knowledge-base/BACKLOG.md`. For the
machine-readable form use `--format json`; to skip the backlog write, omit
`--write-backlog`.

### `gaps`

Whole-repo uncovered-code audit (source files no behavior exercises or declares as
an `entry`):
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/behavior-graph/scripts/behavior_graph.py" \
  --gaps --project .
```
Use it to find code with no captured intent — candidates to capture a behavior for.

### `review intent` (proposed → confirm)

Work the **intent worklist** one behavior at a time (certainty-sorted, lowest
first — read `intent_worklist` from `status --format json`). For each `proposed`
behavior: re-read its code, present it, then **confirm** (bump `state`
`proposed → confirmed` in the spec frontmatter), **edit then confirm**,
**quarantine/deprecate**, or **skip**. Stop whenever the engineer wants. This is
how the cold tail (behaviors never touched by work, so never surfaced by wrap-up's
validate-on-hit) gets drained on purpose.

### `review tests` (confirmed → accept)

Work the **test-owed worklist** one behavior at a time (read `test_owed_worklist`).
For each `confirmed` behavior: link or write its test, and once a real passing
linked test exists, bump `state` `confirmed → accepted` (the wrap-up regression
gate then governs it). Never auto-author a test — that is the engineer's work.

## BACKLOG.md

`status` regenerates **`knowledge-base/BACKLOG.md`** — a generated, git-tracked,
never-hand-edited view of what's outstanding (behaviors to confirm, tests owed,
coverage gaps, open security findings). It is to intent+security completeness what
a coverage report is to test coverage: it diffs in PRs so the team sees the
backlog without running anything. `wrap-up` also regenerates it in its artifacts
commit, so it stays current.

## When to use

- After pulling changes, or before planning, to see what intent/tests/findings are outstanding.
- To work the tail deliberately (the worklists) rather than waiting for validate-on-hit.
- `status` is read-only; use `/freya-devkit:wrap-up` to actually sync/commit.
