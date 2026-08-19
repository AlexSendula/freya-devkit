# Design Notes

Cross-cutting ideas and deferred investigations that don't belong to a single feature's design folder. Each entry says *what*, *why deferred*, and *when to pick it up*.

## Audit all subagent flows + the generated-docs set (deferred: after portability)

**What:** Several skills orchestrate sub-agents (coordinator + parallel workers) — e.g. `docs-manager` spawns workers to generate documentation, `codebase-security-scan` spawns discovery/analysis workers, and `spec-manager scan` spawns discovery agents. As a later upgrade we should audit **all** of these flows. Specifically for `docs-manager`, review **what documents we actually generate** (ARCHITECTURE / API / DATABASE / …): are they the right set? Do we need more, fewer, or different docs — e.g. varying by project type / stack?

**Why deferred:** it's an upgrade, and it sits downstream of the multi-agent **portability** feature (Track A). Portability is already reshaping *how* these subagent flows are expressed (decoupling the unit-of-work from the scheduler), so it's cheaper to revisit the *content* of the flows afterward. It also ties into the framework-agnostic goal in the polyglot parking-lot (docs-manager's templates are Next/Prisma-flavored today).

**When to pick it up:** after portability ships. Start by enumerating every coordinator/worker flow; then revisit the docs-manager generated-doc set against arbitrary stacks.

> **Status (2026-08-19) — DUE. The gate is open.** Portability shipped as 0.2.0 on
> 2026-08-18 (`CHANGELOG.md`), so "after portability ships" is satisfied and this is no
> longer deferred work. It is also demonstrably not done: `skills/freya-docs-manager/SKILL.md`
> still documents a twelve-way LLM fan-out it schedules in prose, and its generated-doc
> templates are still Next/Prisma-flavoured (`references/templates.md` names `NEXTAUTH_SECRET`
> and "Next.js pages"; `scripts/detect_project.py` checks for Prisma). Portability sharpened
> the item rather than closing it: `portability/phase-7-validation-log.md` measured "Zero
> delegation across a documented twelve-way fan-out" on Copilot and traced it to documented
> host policy — start the audit there. This also ties directly into Track B direction update
> #3 (make the whole plugin framework-agnostic) in `behavior-layer/parking-lot.md`.

## Carried-forward defects rescued from executed plans (2026-08-19)

Each of these was recorded only in the "Carried forward" tail of a plan now under
`../superpowers/archive/`. All three were re-verified against shipped code on 2026-08-19 and
are still true. They live here so that archiving a plan never archives a bug report.

1. **`mitigated` is an unreachable disposition.** `skills/freya-codebase-security-scan/SKILL.md`
   maps `mitigated` → MITIGATED in its disposition table, but `audit_engine.disposition()`
   only ever returns `confirmed`, `intentional-design`, `needs-review` or a drop. Neither the
   original JS engine nor the Python port ever emitted it. *(from `2026-07-31-audit-driver.md`)*
2. **`uninstall` is missing from the conformance checker's `BUILTIN_COMMANDS`.**
   `bin/check_skill_conformance.py` lists only `install`, `update`, `doctor`, `init`, `help`,
   while `bin/freya_cli.py` also ships `uninstall`. The first SKILL.md to mention
   `freya uninstall` trips rule R3 — a trap, not a rule.
   *(from `2026-08-14-update-init-doctor.md` and the phase-5 design §12)*
3. **Three unimplemented phase-6 findings.** (a) A `--copy` install is re-copied on every
   update with no content or HEAD comparison — `bin/updater.py` queues every non-symlink `ok`
   entry unconditionally, and the marker `bin/installer.py` writes contains only the source
   path. (b) Repairing a copy install with `--force` silently converts it to symlinks; the
   orphan remedy in `bin/freya_cli.py` says only "re-run `freya install --force`" with no mode
   warning. (c) Two `doctor` lines read oddly together.
   *(from `portability/phase-6-validation-log.md`)*

Still open and platform-blocked: Windows live-agent validation, `install.ps1` and `--copy`
under Windows (CI covers them on `windows-latest`; no live agent run has), the 60 s fetch
timeout path, and the read-only bypass probe against Copilot CLI 1.0.75.

## `status` and `review` are advertised but undefined (codebase-security-resolver) (2026-08-19)

`skills/freya-codebase-security-resolver/SKILL.md` lists `status` ("Quick count by severity +
last scan date") and `review` ("Show what was fixed in last session") in its Quick Reference
table at lines 34-35, but the Commands section below defines only the default interactive flow,
`list`, `fix <ids...>` and `fix --dry-run`. Neither command has a phase, an example, or any
statement of where it reads prior-session state from — git log, a diff between dated reports,
or something else — so an agent invoked with `review` has to improvise. The published explainer
does not preserve the gap either: `explanations/plugin/reference.html` and `skills.html` list
only the four defined commands, silently dropping two commands the skill still ships. Pick one:
specify both commands with a phase and an example, or remove them from the table.

*(Rescued from the explainer research brief `explanations/plugin/_research/10-skill-security-resolver.md`
before that tree was deleted. Re-verified against shipped code on 2026-08-19. It was the only
finding in all 33 briefs that existed nowhere else — 69 other candidates were checked and each
was already recorded elsewhere, already fixed, or already false.)*
