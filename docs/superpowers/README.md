# `superpowers/` — brainstorming outputs

Two live drop zones and one archive.

| Directory | Read it as |
|---|---|
| `specs/` | **Drop zone.** The `superpowers:brainstorming` skill writes new design specs here by hardcoded path (`docs/superpowers/specs/YYYY-MM-DD-<topic>-design.md`). Anything in it is in flight. |
| `plans/` | **Drop zone.** The `superpowers:writing-plans` skill writes new implementation plans here by hardcoded path (`docs/superpowers/plans/YYYY-MM-DD-<feature>.md`). Anything in it is in flight. |
| `archive/` | **Executed history.** 19 plans and 12 specs, all delivered. See [`archive/README.md`](archive/README.md). |

Both drop zones are kept as empty directories on purpose. Do not rename or relocate them: the
paths are hardcoded inside a third-party plugin this repo does not control.

> **Path note (2026-08-19).** Records written before this date cite archived documents at
> `docs/superpowers/plans/…` and `docs/superpowers/specs/…`. Those files now live one level
> deeper, under `docs/superpowers/archive/`. The citations are left as written — they are
> dated records, and CONTRIBUTING.md's convention is to append a correction rather than
> rewrite. Add `archive/` when following one.
