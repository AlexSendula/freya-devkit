# Migration: `docs/` → `knowledge-base/`

> This recipe is live — it is meant to be run, not read as history — so its commands are
> kept current. As of 0.2.0 that means the `freya-` skill names and the `freya` launcher;
> see [`skill-rename.md`](skill-rename.md) if you are also coming from 0.1.0.

The freya-devkit skills now read and write their generated artifacts under a single
`knowledge-base/` root instead of scattering them under `docs/`. This changes **where** skills
read/write, never **what** they do.

| Old location | New location |
|---|---|
| `docs/specs/` | `knowledge-base/specs/` |
| `docs/project/` | `knowledge-base/reference/` |
| `docs/security-reports/` | `knowledge-base/security/` |
| `docs/.code-graph/` | `knowledge-base/.graph/` |
| `docs/README.md` (generated index) | `knowledge-base/README.md` |
| — (new) | `knowledge-base/principles.md` |
| — (new) | `knowledge-base/decisions/` |

## Migrating an existing project

If a project already has the old layout, move it once. The steps are **idempotent** — each is a
no-op if already done, so the recipe is safe to re-run:

```bash
# From the project root. Each line is safe to skip if the source dir doesn't exist.
mkdir -p knowledge-base
[ -d docs/specs ]            && git mv docs/specs knowledge-base/specs
[ -d docs/project ]          && git mv docs/project knowledge-base/reference
[ -d docs/security-reports ] && git mv docs/security-reports knowledge-base/security
# If you kept a generated index at docs/README.md, move it to knowledge-base/README.md
# by hand — only you can tell it apart from your own docs/README.md.

# The dependency graph is a regenerable cache — delete the old one and rebuild:
rm -rf docs/.code-graph
freya code-graph --build
```

Then seed the two new homes (or just ask your agent for `freya-spec-manager init`, which
creates them if absent):

- `knowledge-base/principles.md` — the project constitution (template:
  `skills/freya-spec-manager/references/principles-template.md`).
- `knowledge-base/decisions/` — home for cross-cutting ADRs (README:
  `skills/freya-spec-manager/references/decisions-readme.md`).

## Notes

- **No behavior change.** Skills resolve the new paths by default. `spec-manager`'s spec search
  keeps a legacy `docs/specs` fallback so a not-yet-migrated project stays readable, but all
  writes go to `knowledge-base/`.
- **The code graph need not be migrated** — it is a cache keyed to a commit; rebuilding is cheaper
  and safer than moving it.
