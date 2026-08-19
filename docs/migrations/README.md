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

> **A note on this repo's own `docs/`.** freya-devkit has deliberately *not* run
> `knowledge-base.md` on itself. This `docs/` tree is hand-authored — design records,
> migration recipes, and the published explainer sites — while `knowledge-base/` is the root
> the toolkit's own skills generate into. Keeping them separate means generated and
> hand-written content never share a directory.
