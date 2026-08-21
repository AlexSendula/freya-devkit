# `migrations/` — runnable recipes

These are **live instructions meant to be executed**, not records to be read as history. They are kept current against the shipped
CLI, and each is idempotent — safe to re-run, a no-op if already applied.

They target **adopting projects**, not this repo.

| Recipe | When you need it |
|---|---|
| [`skill-rename.md`](skill-rename.md) | 0.1.0 → 0.2.0. Every skill directory and every `SKILL.md` `name:` gained the `freya-` prefix, and invocation names changed with them. There is no alias — the old names are directories that no longer exist. **Applies to everyone.** |
| [`knowledge-base.md`](knowledge-base.md) | Moves generated artifacts out of `docs/` into a single `knowledge-base/` root (`specs/`, `reference/`, `security/`, `.graph/`). Changes **where** skills read and write, never **what** they do. |

If you are coming from 0.1.0 and need both, run `skill-rename.md` first: the
`knowledge-base.md` commands assume the `freya` launcher and the renamed skills.

> **A note on this repo.** freya-devkit ran the `knowledge-base.md` move on itself on
> 2026-08-21 — this file is inside the result. The recipe's own table is written for a
> project whose generated artifacts sat under `docs/specs/`, `docs/project/` and
> `docs/security-reports/`; this repo had none of those, so what actually happened was the
> other half of the same move: the whole hand-written `docs/` tree became `knowledge-base/`,
> and `docs-manager` now owns `README.md` and `reference/` inside it. Generated and
> hand-written content do share a directory here, and
> [`../README.md`](../README.md) is the table that says which is which.
