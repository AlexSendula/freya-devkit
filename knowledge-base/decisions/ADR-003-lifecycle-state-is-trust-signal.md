---
id: ADR-003
title: Lifecycle state, not a certainty score, is the trust signal
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - behavior-layer
  - lifecycle
  - trust
  - ids
---
# ADR-003: Lifecycle state, not a certainty score, is the trust signal

## Decision

A behavior carries a discrete lifecycle state — `proposed` → `confirmed` → `accepted`, plus `quarantined` and `deprecated` — and trust is never a numeric score. Only `accepted, non-quarantined` is authoritative: only it requires a real linked test, only it can block wrap-up, and only it can downgrade a security finding. `confirmed` means a human confirmed the intent and the test is still owed; `proposed` is a review-queue candidate, and a scaffold or link enters the code tree only on human acceptance.

## Rationale

`state` replaced `behavior_status` (`none`/`scaffolded`/`authored`), which conflated "text exists" with "approved as intent". A scaffold with words in it is not an approved intent. Intent cannot be reliably inferred from code — code reveals candidate behavior at best — so auto-generating authoritative scaffolds from the implementation would reintroduce the "tests mirror code" problem the behavior layer exists to fix. That is why scan and inference never write authoritative-looking artifacts into the code tree, and why commit class follows state rather than location: a proposed/TODO scaffold sitting in the code tree is still an artifacts commit.

Four states shipped first and were amended on 2026-06-30 because confirming intent and writing a test are different acts. Collapsing them forces test-writing mid-feature; leaving the gap untracked silently accumulates unguarded intent (`docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md:26`). Before `confirmed` existed, `validate_behaviors` demanded an adapter and a locator in every state, so a behavior had nowhere to live between "guessed" and "verified".

The certainty model failed on exactly this seam. In dogfooding finding F4, an agent drafted SPEC-001 from the code and a human confirmed the intent; neither "100 = user wrote it" nor a low scan score fit, and the session settled on an arbitrary `certainty: 90` (`docs/design/behavior-layer/dogfooding-notes.md:46`). The resolution was to make certainty stop meaning trust, not to redesign provenance. `certainty` survives only as the prioritizer of the proposed pile, the confidence attached to declarative decisions that the security scan consults, and backward compatibility.

`confirmed` is non-gating structurally, not by convention. `fingerprint_behavior` routes on state **before** level and adapter (`skills/freya-behavior-runner/scripts/run_behaviors.py:227`), so a confirmed behavior only ever gets a static fingerprint from its `entry` (or `unknown`/`no-entry` with none), can never be `test-failed`, and a gate on it is unreachable rather than merely forbidden. `verify_links` mirrors this: a missing locator is an error only when the state is `accepted`, while a locator that *is* present is resolved in every state so a typo fails loud (`skills/freya-spec-manager/scripts/verify_links.py:99`).

The `confirmed` stage validated first try in SP1: BEH-004 as `confirmed`, level `integration`, `entry` present, no adapter or locator → `verify_links` exit 0, projected with `coverage: static` and the entry's code-graph closure; a no-op touch of the entry route returned affected `[BEH-003, BEH-004]`, failed `[]`, exit 0. Shipped as `BEHAVIOR_STATES = ("proposed", "confirmed", "accepted", "quarantined", "deprecated")` at `skills/freya-spec-manager/scripts/frontmatter.py:93`, with four scripts citing "design 03 §3" by name. Ids are stable across renames, allocated by SKILL.md convention, with deterministic collision detection in `verify_links.py` (`skills/freya-spec-manager/scripts/verify_links.py:71`).

## Rejected Alternatives

- **`behavior_status` with `none`/`scaffolded`/`authored`.** Describes the artifact, not the approval. "Authored" text is not confirmed intent, so the field could not carry trust.
- **Scan writing scaffolds into the code tree, or marking inferred candidates `accepted`.** Code-derived intent in an authoritative costume — it makes the tests mirror the implementation, which is the failure mode the layer exists to prevent.
- **Classifying commits by directory.** A TODO scaffold under review would land in the code commit purely because of where the file sits. State decides the commit class instead.
- **A two-state `proposed` → `accepted` lifecycle.** Accepting keeps meaning "write the test now", so intent capture stalls mid-feature and the proposed queue never drains.
- **Redesigning certainty/provenance to express "agent-drafted, human-confirmed".** The F4 problem was dissolved rather than redesigned: once state carries trust, the score no longer has to encode who wrote what.
- **Requiring `entry` or a locator at confirm time.** Entry-less `confirmed` is legal, at the stated cost that Direction A cannot surface it — such a behavior appears only in the worklist.
- **Letting `confirmed` gate wrap-up.** There is no test to fail, so a gate could only produce false blocks.
- **Dispatching on level/adapter before state.** A confirmed record may name a vitest locator for a test that does not exist yet. Pinned by `test_confirmed_with_unit_adapter_is_still_not_executed` (`skills/freya-behavior-runner/scripts/test_run_behaviors.py:979`) under the rule "state wins over level/adapter".
- **Skipping adapter/locator validation where they are optional.** They are still type- and enum-checked in every state, so a typo fails loud instead of being silently ignored in the pre-test states.
- **Hiding `confirmed` from `behavior.json`.** Surfacing it is the point; the safety guarantee comes from never executing it, not from concealing it.
- **A `BEH-NNN` allocator script.** No other id type has one — `search_specs.py` only reads ids and SKILL.md says "next sequential number" — so only collision detection is coded.

## Revisit Conditions

- If model-proposed candidates become reliable enough that human acceptance is ceremony rather than judgment, the `proposed` gate is dead weight.
- If a sixth state is needed — a test written but failing by design. The 2026-06-30 amendment already showed four states were too few.
- If entry-less `confirmed` behaviors accumulate to the point that the worklist is the only place they are ever seen, require `entry` at confirm time.
- If advisory static fingerprints make Direction A/B noisy enough that projecting `confirmed` into the graph stops paying for itself.
