# The Behavior Layer — explainer webapp

A self-contained explainer for the **Behavior Layer** (`feat/behavior-layer`): the problem,
the vision, what shipped, how it composes, and what it solved. Written for an engineer who
knows only the original `main`.

## How to open

No build, no install, no network. Either:

- **Double-click `index.html`** (works on `file://`), or
- serve it: `python3 -m http.server -d docs/behavior-layer-explainer` → http://localhost:8000

Light/dark toggle is in the top-right of the nav.

## The pages, in reading order

| Page | What it covers |
|---|---|
| `index.html` — **The Story** | The coherent narrative: the four failure modes, the one idea, the intent taxonomy, the five non-negotiables, the lifecycle, both blast-radius directions, and the honest status. Start here. |
| `concepts.html` — **How It Works** | The building blocks, interactively: what changed in the toolkit, the behavior record, the lifecycle explorer, adapters, the behavior graph (click nodes to run Direction A/B), coverage fingerprints, the substrate — and the life of one behavior end to end. |
| `governance.html` — **Governance** | How captured intent is enforced: the what-guards-what matrix, block-on-facts vs resolve-to-proceed, the G1 declared-intent walkthrough, principles, contradictions, ADRs, and declarative-drift. |
| `journey.html` — **The Journey & The Proof** | Mechanism-first sequencing, the phase timeline, the wrap-up pipeline explorer, the dogfooding evidence (with its honest limits), the adoption arc, and the parking lot / Phase 5. |
| `reference.html` — **Reference** | Lookup: real per-script CLI flags (filterable), the knowledge-base layout, lifecycle cheat-sheet, G1 trigger rules, coverage-unknown reasons, glossary. |

## What `_research/` is

Thirteen verified research briefs, mined from the branch's design docs, specs, plans, and
code by a multi-agent research pass. They are the **sourced backing** for every claim on the
site (each brief names its primary sources) — kept as a "go deeper" layer and as citations.
The webapp was authored from these briefs and then adversarially fact-checked against the
actual source.

## Provenance & accuracy

- All examples use the dogfooding testbed's generic passkey-auth spec (`SPEC-001`,
  `BEH-001/002/003`); no proprietary content, secrets, or customer data appear anywhere.
- Dogfooding numbers are quoted with their honest limits (e.g. FP=0 was measured on
  2 behaviors / 3 changes — illustrative, not a benchmark).
- Primary sources live in the repo: `docs/design/behavior-layer/` (vision, phase designs,
  dogfooding notes, parking lot) and `docs/superpowers/specs|plans/`.
