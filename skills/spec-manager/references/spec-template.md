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

## Acceptance Criteria

- [ ] [Criterion 1 - specific, testable]
- [ ] [Criterion 2 - specific, testable]
- [ ] [Criterion 3 - specific, testable]

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
| `related_code` | No | Array of file paths to related code |
| `intentional_decisions` | No | Array of brief decision descriptions (for search indexing) |

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
