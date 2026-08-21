---
id: SPEC-020
title: Contradiction comparison sets (G3)
category: features
tags: [governance, contradictions, g3, adr, authority-order, tier-2, spec-manager]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-spec-manager/scripts/contradictions.py
  - skills/freya-spec-manager/scripts/adr.py
  - skills/freya-spec-manager/scripts/principles.py
  - skills/freya-spec-manager/scripts/test_contradictions.py
  - bin/commands.json
  - skills/freya-spec-manager/SKILL.md
intentional_decisions:
  - "Every accepted ADR is compared, whatever the changed spec's category"
  - "Peers are scoped to the same category even though ADRs are not"
  - "An unknown spec or ADR id returns an empty set with a note, never an error"
  - "Malformed ADRs ride along in the payload as adr_warnings instead of vanishing"
  - "The comparison set is assembled; the contradiction judgment is never made here"
behaviors:
  - behavior_id: BEH-096
    title: The set for a changed spec carries the project's principles and its same-category peers' decisions
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_contradictions.py#ContextCase.test_context_has_principles_and_same_category_peers
  - behavior_id: BEH-097
    title: The changed spec itself and specs in other categories are excluded from the peer set
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_contradictions.py#ContextCase.test_context_excludes_self_and_other_categories
  - behavior_id: BEH-098
    title: Every accepted ADR enters the set whatever the spec's category, and a superseded ADR does not
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_contradictions.py#ADRContextCase.test_context_excludes_superseded_adr
  - behavior_id: BEH-099
    title: An unknown spec id yields an empty comparison set carrying a note, not an error
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_contradictions.py#ContextCase.test_context_spec_not_found_is_safe
  - behavior_id: BEH-100
    title: A changed ADR is compared against the principles above it and its peer ADRs, itself excluded
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-spec-manager/scripts/test_contradictions.py#ADRSelfContextCase.test_has_principles_and_peer_adrs
---

# Contradiction comparison sets (G3)

## What

`freya contradictions context` and `adr-context` answer one question: *what does
this changed intent have to be judged against?* They gather; they never compare.

For a **changed spec**, the set is the project's principles, every `accepted` ADR,
and the `intentional_decisions` of same-category peer specs — the spec itself
excluded, and peers that declare no decisions excluded because they carry nothing
to contradict (BEH-096, BEH-097, BEH-098). For a **changed ADR**, the symmetric
set is the principles above it plus its peer ADRs, itself excluded (BEH-100).
Malformed ADRs that could not be parsed come back as `adr_warnings` alongside the
set rather than being dropped in silence. An id that names nothing returns an
empty set and a `note` saying so (BEH-099).

`resolve` and `prior` are the same append-only resolution-log pair described in
[SPEC-019](./SPEC-019-principle-enforcement-surface.md), keyed on `(spec, against)` where
`against` is a free-form `principle:N`, `SPEC-NNN` or `ADR-NNN`.

The authority order the sets encode is principle > ADR > spec, which is what makes
"fix the spec" the default resolution against an ADR, and "fix the ADR" the
default against a principle.

## Why

A new or changed spec that quietly contradicts a principle or an ADR is worse than
one that was never written: it looks like an authoritative record while pointing
the other way. G3 exists to put the higher-authority intent in front of the model
at the moment a spec changes, and the ADR half exists because an ADR now outranks
specs — without the symmetric check, ADRs would be the one authoritative artifact
that nothing governs.

The scoping is a deliberate, researched asymmetry recorded in
`knowledge-base/decisions/ADR-011-governance-check-scoping.md`: intent-vs-intent
is always-global over ADRs because an excluded ADR is a silent miss, while an
irrelevant one costs a line of model output.

**Certainty (85).** The highest in this area, and it is documentary rather than
inferred: `build_context`'s own docstring states "ALL active ADRs (always-global,
no scoping — design §2)", ADR-011 states the same decision and the reasoning behind
it, and `SKILL.md`'s "Contradiction Check (governance G3)" section documents the
returned keys and the always-global rule for the agent that consumes them. Held
below 90 by the peer filter: that peers are same-category *and* must declare
`intentional_decisions` is a real scope limit that no ADR argues for explicitly.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-096 The set for a changed spec carries the project's principles and its same-category peers' decisions | proposed | `test_contradictions.py#ContextCase.test_context_has_principles_and_same_category_peers` (unittest) |
| BEH-097 The changed spec itself and specs in other categories are excluded from the peer set | proposed | `test_contradictions.py#ContextCase.test_context_excludes_self_and_other_categories` (unittest) |
| BEH-098 Every accepted ADR enters the set whatever the spec's category, and a superseded ADR does not | proposed | `test_contradictions.py#ADRContextCase.test_context_excludes_superseded_adr` (unittest) |
| BEH-099 An unknown spec id yields an empty comparison set carrying a note, not an error | proposed | `test_contradictions.py#ContextCase.test_context_spec_not_found_is_safe` (unittest) |
| BEH-100 A changed ADR is compared against the principles above it and its peer ADRs, itself excluded | proposed | `test_contradictions.py#ADRSelfContextCase.test_has_principles_and_peer_adrs` (unittest) |

Two adjacent guarantees are proven but unrecorded: a peer that declares no
decisions is left out (`ContextCase.test_context_excludes_peers_without_decisions`)
and an unknown *ADR* id is as safe as an unknown spec id
(`ADRSelfContextCase.test_unknown_adr_is_safe`).

## Intentional Design Decisions

### Every accepted ADR is compared, whatever the changed spec's category

**Decision**: ADRs are not scoped at all. There is no `applies_to` field; the only
filter is lifecycle status, and `tags` / `related_code` on an ADR are human
navigation, never comparison filters. A change to an `auth` spec is shown the
database ADR too. See
`knowledge-base/decisions/ADR-011-governance-check-scoping.md`.

**Security Scan Note**: an ADR appearing in the comparison payload for an
apparently unrelated spec is not a scoping defect and not context leakage. Adding
a category or tag filter here would convert a noisy line of model output into a
silent miss.

### Peers are scoped to the same category even though ADRs are not

**Decision**: peer specs are filtered to the changed spec's own category and must
carry `intentional_decisions`. A contradiction between an `auth` spec and an `api`
spec is not surfaced by this check.

**Rationale**: cross-category intent is expected to have been lifted into an ADR
or a principle, which *are* compared globally — the tier above absorbs the recall
the peer tier gives up, and peer-vs-peer resolution is "reconcile" rather than an
authority ruling, so the cheap scope is the defensible one.

**Security Scan Note**: this is a known, accepted recall gap, not an oversight. Do
not read a clean G3 result as "this spec contradicts nothing in the project" — it
means it contradicts no principle, no accepted ADR, and no same-category peer.

### An unknown spec or ADR id returns a note, never an error

**Decision**: `build_context`/`build_adr_context` return a well-formed payload
with empty peers and a `note` when the id does not resolve — a deleted spec, a
typo, or an ADR that is not `accepted`.

**Rationale**: every governance check fails open on infrastructure trouble rather
than blocking (`ADR-009`); a check that crashes on a renamed file makes wrap-up
unusable exactly when the repo is already in flux.

**Security Scan Note**: exit 0 with an empty set is not a clean bill of health.
Callers must read `note` and `adr_warnings`; treating a successful exit as "no
contradictions" over-reads the tool.

### Malformed ADRs ride along as `adr_warnings`

**Decision**: an ADR whose frontmatter cannot be parsed is excluded from the
comparison set, but the exclusion is reported in the same payload, and the skill
instructs the agent to surface those warnings before judging.

**Rationale**: a silently vanishing ADR is indistinguishable from a project that
never had one — the comparison would look complete while missing its
highest-authority input.

**Security Scan Note**: `adr_warnings` being non-empty means the check ran against
a knowingly incomplete authority set. That is a warning to act on, not a parse
error to suppress.

### The set is assembled; the contradiction judgment is never made here

**Decision**: nothing in `contradictions.py` decides whether two intents conflict.
There is no verdict and no failing exit code — only gather, append and lookup.

**Rationale**: contradiction checking is model judgment, and Tier 2 is
resolve-to-proceed rather than a script exit code
(`knowledge-base/decisions/ADR-009-two-enforcement-tiers.md`).

**Security Scan Note**: the missing comparison logic is the design. Enforcement is
the wrap-up procedure that will not complete while a finding is unresolved.

## Related Specs

- [SPEC-019: Principle enforcement surface (G2)](./SPEC-019-principle-enforcement-surface.md) —
  the tier above, and the source of the `principles` half of every set here
- [SPEC-021: Declarative-drift scope and the gaps view (P4b)](./SPEC-021-declarative-drift-scope.md) —
  the opposite scoping decision, for the opposite direction of check
- [SPEC-016: ADR record integrity and index](./SPEC-016-adr-record-integrity.md) — what makes
  an ADR eligible for the set in the first place

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec (inferred) | Brownfield scan of `skills/freya-spec-manager/scripts/contradictions.py` |
