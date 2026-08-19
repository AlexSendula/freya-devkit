# Archive — executed plans and specs

Every document here was **executed in full and its deliverables verified present** in `bin/`
or `skills/`. None describes outstanding work. Read them as provenance — the *why* behind a
decision — never as instruction.

> **Do not triage this directory by checkbox.** There are 539 unchecked `- [ ]` items and
> zero `- [x]` across the 19 plans. Execution status was verified against shipped code in
> every single case, not from the boxes.

The repo says so in its own words: [`plans/2026-07-28-skillmd-de-claudeify.md`](plans/2026-07-28-skillmd-de-claudeify.md)
exempts `docs/superpowers/plans` from the portability rewrite as "**never** — historical record".

## Read these with care — superseded by a later, named plan

- **[`plans/2026-07-01-g3-contradiction-checks.md`](plans/2026-07-01-g3-contradiction-checks.md)
  and [`specs/2026-07-01-g3-contradiction-checks-design.md`](specs/2026-07-01-g3-contradiction-checks-design.md)**
  are the most misleading files here. Both declare the contradiction check deliberately
  **ADR-blind** and forbid extracting a shared resolution module. Shipped code does both the
  opposite: `contradictions.py` imports `active_adrs` and delegates to `resolution_log`. The
  reversals are P4a and the shared-resolution-log refactor, both in this archive.
- **[`plans/2026-07-28-skillmd-de-claudeify.md`](plans/2026-07-28-skillmd-de-claudeify.md)** and
  **[`plans/2026-07-31-portable-orchestration.md`](plans/2026-07-31-portable-orchestration.md)**
  each allow residual `${CLAUDE_PLUGIN_ROOT}` / "Workflow tool" references in their Definitions
  of Done. Phase 4b removed all of them; both counts are 0 today, so those DoD lines read as
  false.
- **[`plans/2026-07-30-installer.md`](plans/2026-07-30-installer.md)** reversed Design Decision 3
  of the portability design (prefix at install time → rename in the repo), because symlinks make
  install-time rewriting impossible.
- **[`plans/2026-07-31-portable-orchestration.md`](plans/2026-07-31-portable-orchestration.md)**'s
  prose fan-out for `scan` was superseded by Phase 7's driver-owned fan-out.

Every plan predating 0.2.0 names pre-rename skill directories (`skills/spec-manager/`,
`skills/code-graph/`) and direct script invocations. Shipped reality is `skills/freya-*/`
behind the `freya` launcher. That drift is expected in a dated record and is not a defect.

Open defects that were once recorded only in these plans' "Carried forward" tails have been
migrated to [`../../design/notes.md`](../../design/notes.md) and are tracked there.
