---
id: ADR-005
title: Repair the parsing substrate in place, stdlib-only, and never return a confidently-empty result
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - substrate
  - code-graph
  - parsing
  - zero-install
  - fail-loud
---
# ADR-005: Repair the parsing substrate in place, stdlib-only, and never return a confidently-empty result

## Decision

Both parsing substrates — spec frontmatter and code-graph import resolution — are fixed in place with the Python standard library, under a bounded capability contract, and neither is allowed to fail silently. Frontmatter is parsed by a scoped, schema-validated parser written for this project's exact versioned, model-authored grammar (scalars, ints, dates-as-strings, quoted strings, block sequences, inline flow arrays, and one level of list-of-mappings for `behaviors:`), which raises a clear error outside that grammar and round-trips unknown fields; the code-graph resolver understands TS/JS `tsconfig`/`jsconfig` `paths` + `baseUrl` (one config only — `extends` is deliberately not followed, `skills/freya-code-graph/scripts/graph_ops.py:641`), uses project-relative file identity, and classifies every edge as internal, `external:<pkg>`, or `unresolved:<imp>`. The governing constraint is under-report certainty, never under-report scope: "couldn't resolve" must never look like "no dependencies".

## Rationale

The old `parse_frontmatter` in `search_specs.py` was a regex hand-roll that silently discarded inline-array fields — `tags: [a, b]` parsed as a string and was then dropped. The schema was about to grow `behaviors` data that would have been corrupted the same way, silently, so the parser was replaced and proven *before* the schema was extended (`docs/design/behavior-layer/01b-phase-1-plan.md:16`, Step 0). A full YAML engine was ruled out by an external constraint rather than by taste: the plugin is stdlib-only and zero-install, so PyYAML adds an install step. The phase spec's §7 originally said "replace with a real YAML parser"; Step 0 of the plan rewrote it to "a strict, schema-validated frontmatter parser that fails loud" before any code landed. The parser shipped as `skills/freya-spec-manager/scripts/frontmatter.py`.

On the resolver, the break was total and measured. The testbed graph had **229 files, 1052 import edges, and 0 internal edges — every edge tagged `external:`** (F7, `docs/design/behavior-layer/dogfooding-notes.md:66`), because every internal import used the `@/` alias and non-relative imports were treated as external. `--dependencies` on the authenticate route returned `[]` despite three `@/lib/*` imports, with no unknown signal. That is worse than incomplete: an empty blast radius looked complete, and every downstream consumer — spec and docs impact updates, all of Phase 2's blast radius — was silently riding on nothing. A `git diff` proved the engine was original and unchanged since published v0.1.0, so this was a long-standing break merely exposed by the first alias-using project; it promoted the vision's capability contract (`docs/design/behavior-layer/00-vision.md:177`) from deferred to blocking.

F9 compounded it: relative imports resolved against the process cwd, so invoking with `--dir` from elsewhere — exactly how wrap-up and the testbed build run — dropped every relative import, not even tagged `external:`. Proven with a 3-file fixture: from a foreign cwd `a.ts`'s `./b` gave `[]`; with cwd equal to the project dir it gave `['src/b.ts']`.

The fix was Route A — patch the homegrown resolver, stdlib-only, no new dependency (`docs/design/behavior-layer/code-graph-substrate-fix.md:5`). It was done under strict TDD, which immediately earned its keep: a naive regex comment-stripper mis-read `/*` inside `@/*` and `*/` inside `**/*.ts`, so a string-aware JSONC parser was needed, and the regression test caught it before shipping. The test file grew from the planned 7 cases to 16. After the fix the testbed rebuild went from 0 internal / 1052 external to **607 internal / 488 external / 0 unresolved**, and the authenticate route resolved `lib/webauthn.ts`, `lib/rate-limit.ts`, `lib/audit.ts` and `lib/prisma.ts`.

The never-confidently-empty rule is the general lesson from F7, and it is enforced in code: an import that is relative or alias-matched but fails to resolve is recorded as `unresolved:<imp>`, distinct from `external:` (`skills/freya-code-graph/scripts/graph_ops.py:429`). A `coverage_unknown` indicator on `--impact`/`--dependencies` was claimed here and never existed — the identifier appeared nowhere but in this sentence. What ships instead is `substrate.unmapped_source` (ADR-029): a build records the in-scope source files its backend could not read, and `--build`/`--update`/`--query`/`--impact` carry that block in their answers, absent entirely when there is nothing to say. It extends this rule from the repository level, where it was implemented, to the *answer* level, where it was not: "3 dependents" and "3 dependents, and a fifth of this repo is unread" are different claims. The same principle drove the build's interactivity fix (F6): builds run non-interactively when stdin is not a TTY, and an uncertain directory defaults to include-as-source with the auto-classified set reported.

The out-of-scope list is deliberate and is part of the decision: no per-edge confidence scoring, no alias systems beyond TS/JS, no full TS module resolution (barrel re-exports, conditional exports), no graphify adoption. The defect table and out-of-scope list in `docs/design/behavior-layer/code-graph-substrate-fix.md:24` are the accurate statement of what the homegrown substrate does and does not do.

## Rejected Alternatives

- **PyYAML or any real YAML engine.** Correct in isolation, but it breaks the zero-install property the plugin sells. The spec's own wording was changed to match the constraint rather than the constraint bent to match the spec.
- **Patching the regex frontmatter hand-roll.** It silently drops what it does not understand — that *is* the bug class. A parser that fails loud on the unsupported case was the point.
- **Extending the spec schema first and fixing the parser after.** The new `behaviors` data would have been silently corrupted on write-and-read-back, with no error to notice.
- **Adopting graphify.** A whole dependency taken on for a defect a bounded stdlib patch fixed. It remains the named fallback, not a rejection on the merits.
- **Leaving the substrate as-is and building Phase 2 on it.** Blast radius would have ridden on nothing; F7 made the failure invisible, which is precisely why it could not be deferred.
- **A naive regex JSONC comment-stripper.** Failed the TDD suite on `@/*` and `**/*.ts` before it shipped; replaced with a string-aware parser.
- **Taking on full TS module resolution, per-edge confidence, or multi-language aliases in the same pass.** Unbounded scope attached to an urgent unblock; explicitly deferred to a reopened contract.
- **Returning `None` from resolution and falling through to `external:`, or dropping the edge.** Both make an unresolved import indistinguishable from a real answer — the exact failure `unresolved:` exists to prevent.
- **Interactive stdin directory classification.** It deadlocks as a pipeline subprocess: on a real Next.js project the build prompted on many `app/` subdirs and even prompted to classify its own generated `.graph/` output dir, so wrap-up could not complete unattended.
- **Defaulting uncertain directories to exclude in non-interactive mode.** Silently drops real source — the same failure mode with a different shape. Include-as-source with the auto-classified set reported is the fail-loud default.
- **Editing the project root `.gitignore` for the regenerable cache.** The build writes a self-contained `knowledge-base/.graph/.gitignore` instead, so adopting projects are not modified outside their knowledge base. (It originally contained `*`; ADR-017 replaced that with an explicit list, because `behavior.json` later landed in the same directory and must be committed.)

## Revisit Conditions

- If the plugin ever gains a dependency-install story, or the frontmatter grammar outgrows a scoped parser, revisit the stdlib-only constraint and the hand-written parser together.
- ~~If `unresolved:` counts stay high on real projects, or edge cases accrue faster than the patch absorbs them, adopt graphify — that is the stated trigger for the fallback.~~ **Triggered, and resolved differently, 2026-08-21.** The trigger fired for a reason this record did not anticipate: not unresolved counts, but languages the resolver cannot see at all. The outcome was neither "patch further" nor "adopt graphify" — the graph is now produced through a contract, this resolver is the always-installed floor behind it, and graphify is one opt-in backend. The out-of-scope line above ("no graphify adoption") is superseded; everything else in this record still describes the floor. See ADR-018, ADR-019.
- Reopen the resolver capability contract when `extends` chains, barrel re-exports, per-edge confidence, or a non-TS/JS alias system are actually needed, not before.
