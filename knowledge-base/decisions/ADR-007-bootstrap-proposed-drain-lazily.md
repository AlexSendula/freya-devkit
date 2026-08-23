---
id: ADR-007
title: Bootstrap everything as proposed, drain the corpus lazily on hit, and publish the tail
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - adoption
  - onboarding
  - worklists
  - status
  - backlog
---
# ADR-007: Bootstrap everything as proposed, drain the corpus lazily on hit, and publish the tail

## Decision

On adoption a brownfield project gets a full inferred corpus of candidates — one `proposed` behavior per observable behavior, anchored to a route or entry where applicable, run exactly once and additively — and **none of it is reviewed up front**. The queue drains on contact: at wrap-up, after the gated accepted-behavior check, the change's blast radius surfaces the affected `proposed`/`confirmed` behaviors for confirmation and flags touched code that no behavior covers, non-gating and skippable in one action. The cold tail is worked through worklists in `freya-status`, a strictly read-only command that aggregates outstanding work and refreshes a generated, git-tracked `knowledge-base/BACKLOG.md`.

## Rationale

**Inference is cheap; validation is the scarce resource.** The whole architecture follows from decoupling the two (`docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md:16`). Inference runs once at adoption and is trusted with nothing — every candidate is `proposed`. Validation is spent lazily, on the small subset a change actually touches, while the code is already in the engineer's head.

**The flood is real and was measured.** The full brownfield scan was actually run over the ~224-file testbed — coordinator plus 7 parallel discovery agents, ~260k subagent tokens, ~65s wall — and produced **~383 candidates: ~336 executable behaviors plus ~47 declarative decisions across 7 areas** (`docs/design/behavior-layer/dogfooding-notes.md:219`, `:221`, `:227`). Each area was individually manageable at 35–63 candidates, with each agent independently self-reporting so, but the whole-repo total is decisively a pile no human reviews up front (`:224`). That is the number that kills the eager-review design: an upfront gate would strand the entire mechanism at onboarding. The flood dissolves only because nothing is reviewed eagerly — Direction A bounds a wrap-up review to the touched subset, typically 2–3 (`03-adoption-and-intent-lifecycle.md:53`).

Bounding is also what makes **full agent re-inference** affordable. A stale bootstrap guess is worse than useless as a confirmation prompt, so each surfaced candidate is re-inferred against the entry's current code; re-inferring the whole backlog would be unbounded fan-out on a sprawling change (`docs/superpowers/archive/specs/2026-06-30-sp3-validate-on-hit-design.md:25`).

**Grain.** Per-observable-behavior is the grain at which a candidate can be anchored to the code it exercises, which is precisely what makes on-hit surfacing work. It also matches the existing scan classifier's "expressible as a test?" question, so no new inference machinery was needed.

**Hit matching.** A behavior counts as hit when its entry-closure intersects the change's blast radius — changed files plus transitive dependents via `code-graph --impact` — which is provably equivalent to the precise closure match without recomputing closures (`sp3-validate-on-hit-design.md:23`). Dogfood D2 is the proof on real data: a no-op edit to `lib/db-prisma.ts`, with the routes themselves unchanged, surfaced all five post behaviors because both entries sit in `impact` as transitive dependents; the coarse `entry ∈ changed_files` rule would have surfaced nothing (`dogfooding-notes.md:170`). Proposed behaviors stay out of `behavior.json`; their closures are computed on demand behind a prefilter — the candidate's entry or the spec's `related_code` must intersect the impact set first (`sp3-validate-on-hit-design.md:24`).

**Project shape is recommended, not decided silently.** Shape is classified from code-graph counts: internal import edges > 0 = brownfield, 0 = greenfield, missing or unreadable graph = unknown (`skills/freya-spec-manager/scripts/project_shape.py:99`, `:106`). The evidence is printed with the recommendation and the engineer confirms or overrides. Validated on the real testbed: 232 source files / 609 internal import edges → brownfield; a `graph.json` whose imports are all `external:` → greenfield; no `graph.json` → unknown, ask outright (`dogfooding-notes.md:157`, `:158`). Edges rather than file counts, because a bare scaffold carries many boilerplate files and no real wiring (`project_shape.py:33`). The rule stays the simplest explainable one *precisely because* a human confirms it — precision buys little when a person is in the loop, while brittleness would cost a misrouted onboarding.

**Visibility.** "Where do I stand" and "do and sync everything" are different questions, and conflating them means you cannot ask the first without changing state. `status` mutates nothing except, on request, the generated backlog (`skills/freya-status/SKILL.md:15`); `wrap-up` stays the do/sync command and regenerates the backlog inside its artifacts commit. The backlog carries a do-not-edit header so it cannot rot into a lie the way a hand-maintained TODO does, and it is git-tracked — unlike the `.graph` caches — so it diffs in PRs and the team sees "18 behaviors owe tests / 3 open security findings" without running anything. It is to intent and security completeness what a coverage report is to test coverage (`03-adoption-and-intent-lifecycle.md:72`).

**Structured security findings.** The scan writes a machine-readable `findings.json` beside every prose report, with a documented schema (`skills/freya-codebase-security-scan/references/findings-schema.md`), and `status` reads open findings from it. It was built in SP4 before SP5 needed it, because it is the substrate the security-to-behavior cross-reference enriches — `behavior_ref` lands as one more field (`docs/superpowers/archive/specs/2026-06-30-sp4-status-and-backlog-design.md:19`).

**Dogfood evidence.** SP2 verified that inference writes zero `.feature` scaffolds into the code tree, leaves `SPEC-001` untouched (additive), and does not project proposed behaviors into `behavior.json` (`dogfooding-notes.md:159`). SP4 confirmed faithful aggregation and independent degradation: census 6 proposed / 0 confirmed / 2 accepted, intent worklist 6, test-owed 0, 222 coverage gaps, verify 0, stale 0, with security reported as a note (`no findings.json`) rather than an error, and no declared entry leaking into the gaps list; confirming BEH-004 moved the census to 5 proposed / 1 confirmed with test-owed 1 (`:182`, `:183`, `:186`).

**Skill boundary.** A capability extends an existing skill unless it is genuinely cross-skill. Bootstrap became a command inside `spec-manager` (`skills/freya-spec-manager/SKILL.md:40`) because it extends that skill's existing init/scan surface, and spec-manager already orchestrates a sibling (`update` calls code-graph impact). `status` aggregates across behaviors, code-graph gaps, verify and security the way `wrap-up` orchestrates them — genuinely cross-skill — and splitting keeps `wrap-up`'s mutate-and-commit semantics clean against `status`'s read-only report semantics, which never block and always exit zero (`sp4-status-and-backlog-design.md:18`).

## Rejected Alternatives

- **Review the bootstrap corpus eagerly at adoption.** ~383 candidates on a 224-file repo. Nobody reviews that, so the mechanism dies at onboarding.
- **Don't infer on brownfield; require hand-authored intent.** Existing intent then stays invisible forever, because Direction A only surfaces behaviors that already exist — the reason the recall-gap capture exists at all.
- **Let inference produce authoritative intent.** The AI cannot know intent it is reading off the code; asserting it would launder a guess into a gate.
- **Run inference on greenfield/scaffold-only projects.** Boilerplate produces low-certainty noise. Greenfield is the *easier* path — author behaviors forward as you build.
- **Use raw file count as the brownfield signal.** A bare scaffold has many files and no wiring; edges separate real feature code from boilerplate.
- **A coarser per-feature-area grain.** Too coarse to map onto code, so a candidate cannot be anchored to an entry and on-hit surfacing has nothing to match.
- **A per-route or per-function grain.** Finer than the behavior actually is, and it reintroduces the tests-mirror-code smell the behavior layer exists to avoid.
- **An eager re-scan over newly-written code.** A second inference mechanism to keep in sync with the first; the recall-gap prompt already catches new uncovered code in the flow of work.
- **Refuse to run on a partially-onboarded repo.** Bootstrap is additive by construction; refusing punishes exactly the projects that started adopting.
- **Coarse `entry ∈ changed_files` matching.** Misses a change to a dependency the entry imports — demonstrated by dogfood D2, where it would have surfaced nothing.
- **Project proposed behaviors into `behavior.json`.** Turns the graph into a candidate dump and breaks the SP1/SP2 invariant that the graph holds trusted intent only.
- **Show the stale bootstrap description at confirmation time.** A guess made against older code is worse than useless as a prompt — it invites confirming something that is no longer true.
- **Gate wrap-up on unconfirmed candidates.** The corpus is untrusted by definition; blocking on it converts a helpful surface into a wall.
- **Auto-accept a confirmed candidate on hit.** Tests are never auto-authored, so an auto-accept would claim test-backed authority that does not exist. It stays `confirmed` and routes to the test-owed worklist.
- **Tighten `recall_gaps` to exclude files inside proposed closures.** Over-flagging a transitively-covered file is the safe direction; the failure worth avoiding is silently accumulating unguarded intent.
- **Auto-branch on shape using a tuned threshold with no human step.** A misclassification silently misroutes the whole onboarding; a printed recommendation with its evidence costs one keystroke.
- **Make `status` a mode of `wrap-up`.** You then cannot ask "where do I stand" without mutating and committing — the exact conflation the split exists to prevent.
- **A hand-maintained backlog.** It rots into a lie, and nothing detects that it has.
- **Keep the backlog or `findings.json` untracked.** Untracked means invisible: no PR diff, and the team learns nothing without running commands.
- **Fail when an input source is missing.** `status` notes it and degrades — a missing `findings.json` is a note, not an error, or one absent producer blanks the whole report.
- **Parse the prose reports to recover findings.** Fragile against dated, model-authored prose.
- **Build a separate deterministic extractor for `findings.json`.** The scan agent already holds the structured findings when it composes the report; a second pass would re-derive what was just discarded.
- **A new top-level onboarding skill.** Bootstrap extends `spec-manager`'s existing init/scan surface; a new skill would duplicate that surface for one flow.
- **Move the worklists into `spec-manager` because the interaction pattern originated there.** Reuse the one-at-a-time pattern, not the location — the worklists read across behaviors, gaps and security.

## Revisit Conditions

If **per-hit surfacing** — not pile size — becomes the ergonomic bottleneck, or lazily-surfaced candidate quality proves poor, reopen the grain. The known trim lever is already identified: validation-heavy routes produced per-input-branch candidates (one behavior per field-length check) and are the largest single contributor to volume; collapse them into one "validates the payload (rejects: …)" behavior per route (`dogfooding-notes.md:226`).

If `proposed` counts only grow across many wrap-ups, the lazy model has failed and batch review needs reconsidering. Likewise if `confirmed` accumulates without tests ever landing.

If recall-gap over-flagging gets routinely ignored, tighten the definition or dedupe in `status`.

Backlog location was left open (`knowledge-base/BACKLOG.md` vs repo root), and 200+ coverage gaps may make it unreadable despite the capped sample — revisit if the file stops being read.

`findings.json` is agent-emitted, so its fidelity rests on dogfooding; observed schema drift would justify a deterministic emitter after all.

If the >0-edge shape rule misclassifies real repos, tighten it.
