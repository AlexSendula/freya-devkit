# The Behavior Layer — explainer webapp

A self-contained explainer for the **Behavior Layer** (`feat/behavior-layer`): the problem,
the vision, what shipped, how it composes, and what it solved. Written for an engineer who
knows only the original `main`.

## How to open

No build, no install, no network. Either:

- **Double-click `index.html`** (works on `file://`), or
- serve it: `python3 -m http.server -d docs/explanations/behavior-layer-explainer` → http://localhost:8000

Light/dark toggle is in the top-right of the nav.

## The pages, in reading order

| Page | What it covers |
|---|---|
| `index.html` — **The Story** | The coherent narrative: the four failure modes, the one idea, the intent taxonomy, the five non-negotiables, the lifecycle, both blast-radius directions, and the honest status. Start here. |
| `concepts.html` — **How It Works** | The building blocks, interactively: what changed in the toolkit, the behavior record, the lifecycle explorer, adapters, the behavior graph (click nodes to run Direction A/B), coverage fingerprints, the substrate — and the life of one behavior end to end. |
| `governance.html` — **Governance** | How captured intent is enforced: the what-guards-what matrix, block-on-facts vs resolve-to-proceed, the G1 declared-intent walkthrough, principles, contradictions, ADRs, and declarative-drift. |
| `journey.html` — **The Journey & The Proof** | Mechanism-first sequencing, the phase timeline, the wrap-up pipeline explorer, the dogfooding evidence (with its honest limits), the adoption arc, and the parking lot / Phase 5. |
| `reference.html` — **Reference** | Lookup: real per-script CLI flags (filterable), the knowledge-base layout, lifecycle cheat-sheet, G1 trigger rules, coverage-unknown reasons, glossary. |

## Provenance & accuracy

- All examples use the dogfooding testbed's generic passkey-auth spec (`SPEC-001`,
  `BEH-001/002/003`); no proprietary content, secrets, or customer data appear anywhere.
- Dogfooding numbers are quoted with their honest limits (e.g. FP=0 was measured on
  2 behaviors / 3 changes — illustrative, not a benchmark).
- The decisions behind the behavior layer are recorded as ADRs in
  [`../../decisions/`](../../decisions/) — ADR-001 through ADR-006 cover intent as an
  artifact, the lifecycle, adapters, the graph substrate and the coverage model. The
  design documents they were distilled from are in git history.
- This site was authored from a set of sourced research briefs that lived in a `_research/`
  subdirectory, then adversarially fact-checked against the source. The briefs were deleted on
  2026-08-19: nothing linked to them, they had gone stale against the 0.2.0 portability release,
  and because this directory is uploaded verbatim as the GitHub Pages artifact they were being
  served publicly as raw markdown. They remain in git history.
