---
id: ADR-011
title: Scope each governance check by which failure is recoverable: intent-vs-intent always-global and ADR-aware, code-vs-intent blast-radius-scoped
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - governance
  - contradiction-check
  - adr
  - scoping
  - drift
---
# ADR-011: Scope each governance check by which failure is recoverable: intent-vs-intent always-global and ADR-aware, code-vs-intent blast-radius-scoped

## Decision

The contradiction check compares a changed spec against **all** active ADRs and, symmetrically, a
changed ADR against the principles above it and its peer ADRs. ADRs are not scoped at all: there is
no `applies_to` field, the only filter is lifecycle status (`accepted` in; `proposed`, `superseded`
and `deprecated` out), and tags and `related_code` exist on an ADR as optional human navigation,
never as a comparison filter. Resolution follows the authority order — spec-vs-ADR defaults to
fixing the spec, ADR-vs-principle to fixing the ADR, peer-vs-peer to reconcile. The
declarative-drift check takes the opposite scoping: it is limited to declared items whose
`related_code` intersects the change's blast radius (changed files plus transitive dependents via
`code-graph --impact`), degrades to direct-file intersection when code-graph is unavailable and
*says so* via `impact_source: "changed-only"` rather than returning a silently empty blast radius,
and publishes the resulting recall gap through `drift gaps`, an on-demand command listing every
declared decision or ADR that carries intent but no `related_code`.

## Rationale

The scoping rule is chosen per check by asking which failure mode is recoverable, and the two
checks land on opposite answers for good reason.

**Intent-vs-intent: over-scoping is unrecoverable.** A three-lens research pass (prior art, our own
data, adversarial critique) established the asymmetry. Scoping only decides what reaches the LLM;
the LLM still makes the judgment. So over-scoping — a filter that excludes a relevant ADR — is a
silent miss, which is the exact failure this layer exists to prevent, while under-scoping is noise
the LLM dismisses in one line (`docs/superpowers/archive/specs/2026-07-01-p4a-adr-support-design.md:16`).
ADRs are cross-cutting by definition, so forcing them into single-domain categories is a category
error: an author cannot enumerate at write time every future spec category an ADR will matter for,
and if they could, the LLM check would be unnecessary. Volume makes scoping pointless anyway —
single digits today, under 20 realistically, a corpus of a few thousand tokens. Prior art agrees:
Nygard, `adr-tools` and MADR all keep ADRs a flat status-only list with scope expressed in prose,
and categorical or tag scoping is documented as prone to tag rot and to the "cross-cutting decision
has no home" failure.

**ADR-awareness reverses G3's shipped ADR-blindness, whose reasoning was sound at the time.**
`knowledge-base/decisions/` was an empty scaffold with no ADR format, no create flow and no index,
so G3 deliberately did not compare against ADRs — "checking against a structurally-empty set would
fake coverage" — and was built ADR-ready with ADR-awareness named as its successor
(`docs/superpowers/archive/specs/2026-07-01-g3-contradiction-checks-design.md:25`). P4a shipped the
missing half: the `ADR-NNN` format, `adr.py`, `active_adrs`, the `decisions/README.md` index. That
removed the entire basis for the blindness. The symmetry half exists because an ADR now outranks
specs, so an ADR contradicting a principle must be caught or ADRs become the one authoritative
artifact that nothing governs. Reuse was free: `--against` is free-form, so an ADR id slots into the
existing `(spec, against)` keying with no new JSONL field and no new module. Shipped and confirmed —
`contradictions.py` imports `active_adrs`
(`skills/freya-spec-manager/scripts/contradictions.py:37`) and `build_context`'s docstring reads
"ALL active ADRs (always-global, no scoping — design §2)"
(`skills/freya-spec-manager/scripts/contradictions.py:56`).

**Code-vs-intent: the natural scope is the declared intent governing the code that changed.**
Always-global there would re-judge every declared decision against every change — the whole-repo
re-derivation ruled out as too noisy to trust — and noise at that volume destroys credibility
rather than adding recall
(`docs/superpowers/archive/specs/2026-07-01-p4b-declarative-drift-design.md:19`). The resulting gap
is named honestly rather than papered over: a decision with no `related_code` is invisible to the
check, and drift introduced in code that is neither in nor a dependent of `related_code` is not
caught — the same recall gap Direction A already has. The mitigation is not a wider scope but
keeping `related_code` current, promoting testable decisions into guard scenarios (the preferred
long-term path), and `drift gaps` making the un-scopable set inspectable
(`docs/superpowers/archive/specs/2026-07-01-p4b-declarative-drift-design.md:26`,
`skills/freya-spec-manager/SKILL.md:55`). The degradation path is shipped as designed:
`drift.py` returns `"changed-only"` as the `impact_source` when the graph or tool is missing rather
than an empty set (`skills/freya-spec-manager/scripts/drift.py:103`,
`skills/freya-spec-manager/scripts/drift.py:152`).

## Rejected Alternatives

- **Keeping G3 ADR-blind.** Valid only while `decisions/` was an empty scaffold; P4a removed the
  premise.
- **Comparing against ADRs before the format existed.** Would have faked coverage against a
  structurally-empty set.
- **Leaving ADRs ungoverned — checking specs against ADRs but never ADRs against principles.**
  Makes the top intent tier the one artifact nothing checks.
- **A new JSONL field or a separate ADR resolution log.** `--against` is already free-form, so ADR
  comparisons key into the existing log unchanged.
- **A bidirectional spec↔ADR reference index.** Prose links suffice, per prior art; an index is
  another structure to keep current and rot.
- **The original `applies_to`-by-category sketch.** A wrong or incomplete `applies_to` is a silent
  miss — the failure mode this check exists to eliminate.
- **A `CATEGORIES` enum plus ADR-side category validation.** Moot under always-global.
- **Filtering by tags or `related_code` on an ADR.** Explicitly forbidden; those fields are human
  navigation only.
- **Any opt-in narrowing lever.** Opt-in turns the failure mode from noise into silence.
- **An always-global drift mode mirroring the ADR comparison.** Re-judging every decision against
  every change is the whole-repo re-derivation the vision rejects.
- **Falling back to an empty blast radius when code-graph is missing.** A silent false-clean; the
  check degrades to `changed-only` and says so instead.
- **Restricting drift targets to purely-declarative specs.** A behavioral spec's declarative
  decisions are equally untested and equally driftable, so all non-deprecated specs'
  `intentional_decisions` are targets.
- **Making `gaps` part of wrap-up.** Deliberately on-demand: it is a coverage signal, not a gate.
- **An interactive, non-wrap-up drift trigger.** At authoring time nothing in code has changed, so
  there is nothing to compare against.

## Revisit Conditions

- If ADR count crosses roughly 30 and noise becomes a real complaint, reopen — but the only
  permitted change is an opt-out (`skip_for`), never opt-in scoping, because opt-out keeps the
  failure mode "noise" and never "silence".
- If a fourth intent tier appears, the authority ordering must be reopened.
- If dogfooding shows real drift routinely escaping because `related_code` is chronically stale,
  the answer is better authoring ergonomics or promotion to guard scenarios; reopen the drift
  scoping only if both of those fail.
