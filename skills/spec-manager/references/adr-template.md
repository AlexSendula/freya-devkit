# ADR Template

Use this template when creating new Architecture Decision Records. Copy and fill in all sections.

---

```markdown
---
id: ADR-XXX
title: [Decision Title — e.g. "Use PostgreSQL for primary storage"]
status: accepted            # proposed | accepted | superseded | deprecated
created: YYYY-MM-DD
updated: YYYY-MM-DD
tags: [tag1, tag2]          # optional — human navigation only, NOT a G3 filter
supersedes: ADR-NNN         # optional — the ADR this one replaces
superseded_by: ADR-NNN      # optional — set when this ADR is retired
related_code:               # optional — future P4b declarative-drift hook, NOT a G3 filter
  - [path/to/file]
---

# ADR-XXX: [Decision Title]

## Decision

[State the decision clearly and specifically. What was decided? What will the system do or not do
as a result? Be concrete — this is the authoritative single-source statement of the choice.]

## Rationale

[Why was this decision made? Include:
- The problem this decision solves
- Alternatives that were considered (high-level; detail in the next section)
- Trade-offs accepted
- Evidence or prior art that informed the choice]

## Rejected Alternatives

[For each alternative that was seriously considered and rejected, explain:
- What the alternative was
- Why it was not chosen (the specific shortcoming or trade-off that ruled it out)

This section is what turns a later reversal into a reviewable event: a future author who
wants to reconsider must acknowledge and refute the rejection reasoning here, not silently
swap the implementation.]

## Revisit Conditions

[Under what circumstances should this decision be re-examined? Examples:
- "If ADR volumes exceed ~30 and noise becomes a real complaint in G3"
- "If the PostgreSQL instance exceeds 10 TB and partitioning cost exceeds benefit"
- "If a new library removes the dependency that makes this approach costly"

This section is what converts future divergence from a silent drift into a deliberate decision.]
```

---

## Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier (`ADR-NNN` format, sequential across `knowledge-base/decisions/`) |
| `title` | Yes | Human-readable decision name |
| `status` | Yes | `proposed` \| `accepted` \| `superseded` \| `deprecated` — only **`accepted`** is authoritative and compared by G3 |
| `created` | No | ISO date the ADR was authored |
| `updated` | No | ISO date the ADR was last modified |
| `tags` | No | Array of topic tags — **human navigation only, not a G3 filter** |
| `supersedes` | No | The `ADR-NNN` this record replaces; must resolve to a real ADR (`adr verify` checks this) |
| `superseded_by` | No | Set when this ADR is retired; must resolve to a real ADR |
| `related_code` | No | Array of project-relative file paths — **future P4b declarative-drift hook, not a G3 filter** |

> **G3 scoping note.** ADRs are compared **always-global** — the contradiction check shows
> the LLM *all* active (`accepted`) ADRs, regardless of category or tags. `tags` and
> `related_code` are human-navigation and P4b metadata; they are never used to scope
> or filter the G3 comparison set. Over-scoping (excluding a relevant ADR) is a silent
> miss; the LLM dismisses irrelevant noise in one line. Only lifecycle status gates
> inclusion: `proposed`, `superseded`, and `deprecated` ADRs are excluded from G3.

## Lifecycle

| Status | Meaning | G3 comparison |
|--------|---------|---------------|
| `proposed` | Under review — intent not yet authoritative | Excluded |
| `accepted` | Authoritative — constrains specs and is compared by G3 | **Included** |
| `superseded` | Retired — replaced by a newer ADR | Excluded |
| `deprecated` | Abandoned — no successor | Excluded |

A human-authored ADR starts `accepted` (the same way a human-created spec starts at
certainty 100 — human authorship is the confirmation). Use `proposed` only when the
decision is still under team review.

## Authority & Resolution

Authority order: **principle > ADR > spec.**

| Changed item | Contradicts | Resolution |
|---|---|---|
| spec | an ADR | **Fix the spec** (ADR outranks) — or consciously amend the ADR |
| spec | a peer spec | **Reconcile** (fix either side, or refute) |
| ADR | a principle | **Fix the ADR** (or amend the principle) |
| ADR | a peer ADR | **Reconcile** |

## Related

- `decisions-readme.md` — home directory overview and tooling summary
- `spec-template.md` — the spec format that links to ADRs via `Intentional Design Decisions`
- `/freya-devkit:spec-manager adr create <name>` — interactive authoring command
- `/freya-devkit:spec-manager adr verify` — deterministic integrity check
- `/freya-devkit:spec-manager adr list` — print / regenerate the ADR index
