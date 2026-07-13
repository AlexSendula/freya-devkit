# Decisions (ADRs)

This directory is the home for **cross-cutting architectural decision records** — declarative
intent that is not bound to a single feature (e.g. "we use Postgres, not Mongo"; "hexagonal
architecture"). Each ADR owns its decision once: the choice, the rejected alternatives, the
rationale, and the conditions to revisit. `reference/` docs **link** to an ADR rather than
restating it.

> **ADR tooling is live (P4a).** Use `/freya-devkit:spec-manager adr create <name>` to author a
> new record; `adr list` to print/regenerate this index; `adr verify` to run deterministic
> integrity checks (duplicate IDs, dangling supersedes links, bad status). Records follow the
> `ADR-NNN` format — see `adr-template.md` for the full schema and lifecycle. **Only `accepted`
> ADRs are authoritative and compared by the governance contradiction check (G3).**

Feature-local decisions do **not** belong here — they live in the owning feature spec's
*Intentional Design Decisions* section.
