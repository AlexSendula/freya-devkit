# Spec Template

Use this template when creating new specifications. Copy and fill in all sections.

---

```markdown
---
id: SPEC-XXX
title: [Feature Name]
category: [auth|api|data|features|infra|integration|ui]
tags: [tag1, tag2]
status: draft
certainty: 100
created: YYYY-MM-DD
updated: YYYY-MM-DD
related_code:
  - [path/to/file]
intentional_decisions:
  - "[Brief description of intentional decision]"
behaviors:
  - behavior_id: BEH-XXX
    title: [Observable behavior, e.g. "Successful passkey login"]
    state: proposed            # proposed | confirmed | accepted | quarantined | deprecated
    adapter: cucumber          # cucumber | behave | pytest-bdd | jest | playwright | ... | manual
    locator: [features/<cat>/<name>.feature#<scenario>  OR  path/to/test#case]
---

# [Feature Name]

## What

[What does this feature do? Be specific and measurable. Include:
- Core functionality
- Key behaviors
- Edge cases handled
- User interactions]

## Why

[Why is this feature needed? Include:
- Problem being solved
- User pain points addressed
- Business value
- Design goals]

## Behavior

The observable acceptance behavior is owned by each behavior's **test**, not by
this spec — link to it here, never copy the scenario steps (single source of
truth). Add one row per `BEH-NNN` in the frontmatter `behaviors:` list.

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-XXX [Observable behavior] | proposed | `[features/<cat>/<name>.feature]` (cucumber) |

Declarative decisions that are *not* executable are recorded under **Intentional
Design Decisions** below, not here. A spec with no testable behavior may leave
the `behaviors:` list empty and this table out — it is then a purely declarative
spec (still requires `related_code`, see frontmatter notes).

## Intentional Design Decisions

### [Decision Title]

**Decision**: [What was decided - be specific about what the code does/doesn't do]

**Rationale**: [Why this decision was made - include trade-offs considered]

**Security Scan Note**: [What to tell security tools if they flag this]
- Example: "This is intentional - see [SPEC-XXX]. The system uses X instead of Y because Z."

### [Additional Decision - if any]

**Decision**: [What was decided]

**Rationale**: [Why]

**Security Scan Note**: [Guidance for security tools]

## Related Specs

- [SPEC-XXX: Related Feature](./path/to/spec.md)
- [SPEC-XXX: Dependency](../category/spec.md)

## Change History

| Date | Change | Reason |
|------|--------|--------|
| YYYY-MM-DD | Initial spec | Feature planning |
```

---

## Frontmatter Fields

| Field | Required | Description |
|-------|----------|-------------|
| `id` | Yes | Unique identifier (SPEC-NNN format) |
| `title` | Yes | Human-readable feature name |
| `category` | Yes | One of: auth, api, data, features, infra, integration, ui |
| `tags` | Yes | Array of relevant tags for searchability |
| `status` | Yes | draft, in-progress, implemented, or deprecated |
| `certainty` | Yes | 0-100 confidence score (100 for user-created) |
| `created` | Yes | ISO date when spec was created |
| `updated` | Yes | ISO date when spec was last modified |
| `related_code` | Recommended | Array of file paths to related code. **Expected on declarative specs too** (not just behavioral ones): it is the key the declarative-drift check uses to decide whether a change's blast radius can affect this decision. A declarative spec with no `related_code` is invisible to that check. |
| `intentional_decisions` | No | Array of brief decision descriptions (for search indexing) |
| `behaviors` | No | List of first-class `Behavior` records (`behavior_id`, `title`, `state`, `adapter`, `locator`). Empty/absent ⇒ the spec is purely declarative. See **Behavior record fields** below. |

### Behavior record fields

Each entry in `behaviors:` is a stable, intent-bearing record linked to an executable test:

| Field | Required | Description |
|-------|----------|-------------|
| `behavior_id` | Yes | `BEH-NNN`, stable across renames (never renumber) |
| `title` | Yes | The observable behavior, in plain language |
| `state` | Yes | `proposed` \| `confirmed` \| `accepted` \| `quarantined` \| `deprecated`. `confirmed` = intent confirmed, test owed (advisory); only **accepted** is authoritative and blocks on failure |
| `level` | Yes | Test level: `unit` \| `component` \| `integration` \| `e2e`. Used by behavior-runner to select the coverage capture mechanism |
| `adapter` | Required for `accepted`; optional for `proposed`/`confirmed` | How it is verified: `cucumber`/`behave`/`pytest-bdd` (Gherkin), a native runner (`jest`, `playwright`, `pytest`, …), or `manual` |
| `locator` | Required for `accepted` (except `manual`); optional for `proposed`/`confirmed` | Where the test lives — `features/<cat>/<name>.feature#<scenario>` for Gherkin, or `path/to/test#case` for a native test |
| `entry` | Required for `level: integration` | Project-relative path to the route/handler file the integration test drives (e.g. `app/api/auth/route.ts`). behavior-runner uses it to derive the static code-graph transitive import closure (`source: static` edges). Omitting it on an integration behavior yields `coverage: unknown, reason: no-entry` |
| `spec_id` | No | Inherited from this spec's `id`; if given, must match |

## Section Guidelines

### What Section
Be specific enough that someone unfamiliar with the codebase can understand what the feature does. Include:
- Core functionality and behaviors
- User interactions and flows
- Edge cases and error handling
- Integration points with other features

### Why Section
Explain the reasoning so future readers (human or AI) understand the design intent:
- What problem necessitated this feature
- What alternatives were considered
- What trade-offs were accepted
- How this fits into the larger system

### Intentional Design Decisions
This is the key section for preventing false positives in security scans and code reviews. For each decision:

1. **Decision**: State exactly what the code does (or doesn't do) that might be surprising
2. **Rationale**: Explain why this is the right choice despite seeming unusual
3. **Security Scan Note**: Give specific guidance for tools/auditors

**Example good decisions to document:**
- "No password authentication" - intentional security choice
- "Allows all CORS origins" - public API design
- "No rate limiting on health endpoint" - monitoring requirement
- "Stores data in localStorage" - offline-first architecture
- "No CSRF token" - using SameSite cookies instead

### Change History
Keep this updated so readers can understand how the spec evolved:
- When the spec was created
- When major changes were made
- Why changes were made (especially if reversing a previous decision)
