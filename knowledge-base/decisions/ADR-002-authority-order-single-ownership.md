---
id: ADR-002
title: Authority runs principle > ADR > spec > reference, and every fact is owned once
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - knowledge-base
  - information-architecture
  - authority
---
# ADR-002: Authority runs principle > ADR > spec > reference, and every fact is owned once

## Decision

Intent has an explicit authority order — principles above ADRs, above specs, above reference — and the knowledge-base layout reflects it. Specs and behaviors are **forward/authoritative** (code conforms to them); reference docs are **reverse/descriptive** (they mirror the code); the two are never conflated. Every fact is owned exactly once: a *generated projection* (one source, a derived view) is allowed, a *hand-maintained duplicate* (two editable copies that drift) is forbidden.

## Rationale

The two rules are load-bearing together, and the layout encodes them (`docs/design/behavior-layer/00-vision.md:28`, `:29`, `:45`). Direction of truth alone does not stop duplication, and single-ownership alone does not tell you which of two documents wins.

Concretely, ownership is assigned artifact by artifact (`00-vision.md:64`, `:80`):

- A behavior's test lives in the **code tree** — a `.feature` next to its step definitions, or an existing native test in place. It *is* test code. Discovery from the knowledge base runs through the spec's link plus the behavior graph, not through copying the behavior into `specs/`.
- `specs/` stays purely declarative: purpose, scope, rationale, constraints, and non-executable decisions. A spec says *why and within what bounds*; it never restates the step-by-step behavior its test already owns. This is why the inert acceptance-criteria checkbox list was removed from the spec body and replaced with a link table (`docs/design/behavior-layer/01-phase-1.md:101`, `:103`).
- `reference/` links to a decision rather than restating it.

The Postgres case is the worked example (`00-vision.md:67`). A cross-cutting fact like "uses Postgres" is owned once by its ADR — which holds the rationale, the rejected alternatives and the conditions to revisit — and `reference/` merely points at it (`Postgres (see ADR-NNN)`). That keeps `reference/` a generated projection instead of a hand-maintained duplicate, and it turns a later Postgres-to-Mongo swap into a **reviewable event** rather than a silent doc regeneration.

The three-tier ordering refines the vision's earlier flat "specs + decisions" tier, and it exists because the governance checks need something to resolve against (`docs/superpowers/archive/specs/2026-07-01-p4a-adr-support-design.md:93`). Without it, an ADR would be the one authoritative artifact nothing governs (`:90`). The resolution defaults fall straight out of the order: spec contradicts an ADR → fix the spec; ADR contradicts a principle → fix the ADR; spec contradicts a same-category peer spec → reconcile, because peers have no ranking between them (`:95`–`:100`).

## Rejected Alternatives

- **Duplicate the behavior text into `specs/` for discoverability.** Discovery is a solvable problem — the spec's link plus the behavior graph solve it. A second editable copy is not solvable: it always drifts, and then nothing says which copy is the intent.
- **Let `reference/` restate cross-cutting facts like the database choice.** `reference/` is regenerated from code. A regeneration would silently overwrite a decision, destroying the rationale and the revisit conditions along with it.
- **A single flat docs tree with no forward/reverse distinction.** It hides which documents drive the code and which merely mirror it, so a stale reference doc and a violated spec look identical, and neither the drift checks nor the contradiction checks have a rule to apply.
- **Keep the inert acceptance-criteria checkbox list alongside the executable behavior.** Two descriptions of the same *what*, one of them unexecuted — exactly the hand-maintained duplicate the single-source rule forbids, and the checklist is the copy that rots, since nothing fails when it goes wrong.

## Revisit Conditions

If link-plus-graph discovery proves too indirect for humans reading the knowledge base, the answer is a **better generated projection**, not a hand-maintained copy — reopen this only if that projection turns out to be ungeneratable.

If a fourth intent tier appears, or if ADRs and specs need different authority orders in different domains, the flat ordering no longer covers the cases and must be reopened.
