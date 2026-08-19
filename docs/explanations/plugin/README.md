# freya-devkit — the whole-plugin explainer

A self-contained explainer for the **entire freya-devkit plugin**: the philosophy, the
architecture, all ten skills, the patterns and conventions, the behavior layer and its
governance, how to start fresh or adopt on an existing project, and a reference. Written for an
engineer who has never seen the toolkit.

## How to open

No build, no install, no network. Either:

- **Double-click `index.html`** (works on `file://`), or
- serve it: `python3 -m http.server -d docs/explanations/plugin` → http://localhost:8000

Light/dark toggle is in the top-right of the nav.

## The pages, in reading order

| Page | What it covers |
|---|---|
| `index.html` — **Overview** | The coherent story: the problem, the one idea, the five core beliefs, the ten-skill roster, and the honest non-goals. Start here. |
| `architecture.html` — **Architecture** | The five tiers, code-graph as the keystone, composition via on-disk artifacts, the `knowledge-base/` tree, and graceful degradation. Interactive tier explorer. |
| `skills.html` — **The Skills** | All ten skills in depth (filterable): purpose, key commands, what each reads/writes, how they compose, and honest limits. |
| `patterns.html` — **Patterns & Conventions** | The reusable patterns, the integration conventions, and an honest "where the docs lag the code" box. |
| `behavior-layer.html` — **The Behavior Layer** | Intended behavior as a first-class artifact: intent taxonomy, the lifecycle (interactive), adapters, the behavior graph and its two directions, and coverage fingerprints. |
| `governance.html` — **Governance** | Block-on-facts vs resolve-to-proceed, the what-guards-what matrix, the wrap-up Phase 3.5 pipeline (interactive), G1–G3/P4a/P4b, and the resolution logs. |
| `portability.html` — **Portability** | Running on any coding agent: the `freya` launcher, the canonical store + symlink install, per-agent instruction files, and how orchestrated skills degrade from parallel to sequential. |
| `getting-started.html` — **Get Started** | Install, the one entry point (`spec-manager bootstrap`), the internal-edge shape detector (interactive), and the greenfield vs brownfield paths. |
| `reference.html` — **Reference** | Filterable CLI for every skill, the `knowledge-base/` layout, tracking files, cheat-sheets (certainty, lifecycle, coverage, finding statuses), and a glossary. |

The behavior layer also has its own dedicated five-page deep-dive at
[`../behavior-layer-explainer/`](../behavior-layer-explainer/index.html) — this site links to it
for the full narrative and dogfooding evidence.

## Provenance & accuracy

- All examples are generic (passkey/WebAuthn auth mechanics, generic `src/` paths); no proprietary
  content, secrets, or customer data appear. The HTML pages contain no absolute local machine paths.
- Where the prose docs disagree with the shipped code, this site follows the **code** and flags the
  discrepancy (see *Patterns → Where the docs lag the code*).
- Primary sources live in the repo: `.claude-plugin/`, `skills/*/SKILL.md`, `bin/`, and `docs/*.md`.
- This site was authored from a set of sourced research briefs that lived in a `_research/`
  subdirectory. They were deleted on 2026-08-19: nothing linked to them, they had gone stale
  against the 0.2.0 portability release, and because this directory is uploaded verbatim as the
  GitHub Pages artifact they were being served publicly as raw markdown beneath the pages that
  contradicted them. They remain in git history, and the one finding they held that was recorded
  nowhere else was moved to [`../../design/notes.md`](../../design/notes.md) first.
