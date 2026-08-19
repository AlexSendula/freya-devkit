---
id: ADR-006
title: Behavior tests drive the app over its real interface, and coverage follows: observed at unit, static closure at integration
status: accepted
created: 2026-08-19
updated: 2026-08-19
tags:
  - behavior-layer
  - coverage
  - fingerprints
  - execution-contract
---
# ADR-006: Behavior tests drive the app over its real interface, and coverage follows: observed at unit, static closure at integration

## Decision

An integration or e2e behavior test drives the running application over its real interface — HTTP
against a booted app, via a `BeforeAll`/`AfterAll` harness that polls readiness and tears down by
killing the process group — and never imports the app's internals; a unit test importing a plain
library function in-process remains correct and expected. Coverage follows from that: observed
runtime coverage exists only at unit level, in-process, from the runner's native V8 output, while
an integration behavior declares an `entry` whose transitive code-graph import closure is emitted
as `exercises` edges tagged `source: static`. Every edge carries provenance in the trust order
`explicit` (reserved, unimplemented) > `observed` > `static`, plus confidence and freshness, and
fingerprints merge by trust rather than recency. A behavior with no usable coverage is always
emitted as `coverage: unknown` with an empty `exercises` list *and* a `reason`, never a silently
empty observed result and never attributed to a path the runner did not establish. `behavior.json`
is a fully generated projection — of spec frontmatter, coverage runs and static parse — that is
never hand-edited and in which users cannot author `exercises:` edges.

## Rationale

This is one causal chain, and it starts from a failed experiment.

**The execution contract was forced by a plan that did not work.** Plan 1 specified importing the
Next.js route handler in-process from cucumber steps. The testbed — like the production app and
like the `create-next-app` default — is CommonJS-default with no `"type": "module"`, so `tsx` loads
the app's `.ts` files through Node's CommonJS hook and the route then `require()`s its ESM
dependencies (`next/server`, `@simplewebauthn`, `lib/webauthn`). Node 24's `require(esm)` rules
forbid this across `next/server`'s module cycle, and cannot read named ESM exports synchronously
even outside a cycle. Neither `.mts` step files nor `tsx`'s `tsImport` helps, because it is the
app's own `.ts` files being CJS-loaded. Flipping the testbed to `"type": "module"` *did* make the
test pass — which is precisely the trap: a false green bought with a project-wide change to the app
under test, after which the testbed no longer represents the real project, and which no adopter can
be asked to make (`docs/design/behavior-layer/dogfooding-notes.md:113`). The fix was a design
change, not a workaround: boot `next dev` once in `BeforeAll` and drive the route over real HTTP
(`features/steps/support/server.mts`). BEH-003 passes in about 4s including boot, with clean
teardown and `verify` green. The shape is identical for Next, Express, Django, Rails and FastAPI —
only the launch command and base URL differ, and the project supplies both through adapter/runner
config, which is the only project-specific part.

**That propagated into coverage, and the spike killed the obvious path.** Once the app runs in
another process, coverage must be captured from the app process rather than the test process.
Dogfooding finding F11 spiked exactly that: `next dev` booted under `NODE_V8_COVERAGE`, the real
BEH-003 requests fired (HTTP 200, so the behavior demonstrably ran), clean exit — and the resulting
coverage contained only Next's own internals under `next/dist/...`. Zero app code, zero `.next`
chunks, even with a clean non-SIGKILL flush. The cause is structural: App Router runs route
handlers in a separate render worker that does not inherit the env-var capture, and the app code is
bundled (`docs/design/behavior-layer/dogfooding-notes.md:122`). Research confirmed the state of the
art rather than offering an escape: `babel-plugin-istanbul` is a dead end on App Router because
forcing Babel breaks Server Actions (an SWC-only transform), and V8 coverage works only through the
debugger — launch under `--inspect`, collect over CDP at inspector port + 1, remap `.next` bundles
through source maps, which is exactly what `nextcov` does. Solved, but Next-only (Next 16 plus
Turbopack unverified) and in direct conflict with the framework-agnostic execution contract just
adopted.

**Static over-approximates, and over-approximation is the safe direction.** A false "might be
affected" costs one extra test run; a false "not affected" misses a regression
(`docs/design/behavior-layer/02d-phase-2-plan-3-behavior-runner-integration.md:7`). The measurement
bears this out: BEH-002 observed at unit level resolved to exactly one file, `lib/webauthn.ts` —
precise, no incidental sweep — against BEH-003 static at integration level resolving to three
(route plus `lib/prisma.ts` plus `lib/webauthn.ts`), broader as expected and still selective enough
for a false-positive rate of 0 on the representative changes. Confidence encodes the difference:
`STATIC_CONFIDENCE = 0.5` against `OBSERVED_CONFIDENCE = 0.8`
(`skills/freya-behavior-runner/scripts/run_behaviors.py:26`).

**The `reason` discriminator was added mid-flight, and it is load-bearing.** It was not in the
original design; Plan 2 added it because without it every `unknown` looks the same, and the two
failure modes are silent and exactly opposite. A `level-deferred` behavior would wipe a good
earlier fingerprint, while a red test would keep stale green edges and stay invisible to the
regression gate. The merge rule therefore reads: an incoming `unknown` with `reason: test-failed`
invalidates stored edges, and an `unknown` with any other reason (`level-deferred`, `no-entry`,
`entry-missing`, `no-coverage`, `no-graph`, `not-run`) preserves the prior fingerprint
(`skills/freya-behavior-graph/scripts/behavior_graph.py:37`). The never-falsely-empty rule carries
the highest cost of all: an empty `exercises` list reads to Direction A as "nothing to re-run",
which is the one output that silently disables the regression gate. The dispatch that enforces
this is `fingerprint_behavior` (`skills/freya-behavior-runner/scripts/run_behaviors.py:212`), which
routes by state then level and falls through to `reason="level-deferred"` rather than to an empty
observed result.

**On generation.** Brainstorming initially settled on "Scope B" — explicit plus observed edges —
and dropped the explicit half before any code was written, because users will not maintain edges by
hand and automation is the entire point. Explicit anchors were kept as an evidence-gated lever for
the case where observed proved too noisy; BEH-002's one-file fingerprint answered that in the
negative. Being generated also lets the file live git-ignored under `.graph/` and be rebuilt from
scratch, which is what makes the merge rules safe to change later.

**On cost.** Per-behavior isolation — one scenario or test per `BEH-NNN`, in its own run — is about
attribution granularity, not run volume. Volume is bounded by incremental selection: `--check`
computes Direction A and `--only` re-runs just the behaviors whose exercised code intersects the
diff's blast radius, so a full sweep happens only on first index or explicit rebuild. Measured on
the testbed: a full `--build` running every accepted behavior takes 1.4–2.4s (dominated by vitest
startup), an incremental `--check` on a change touching no exercised code takes 0.07s with zero
re-runs, and read-only `--affected`/`--implements` queries take 0.03–0.06s
(`docs/design/behavior-layer/02-phase-2.md:182`). Cost scales with the change's blast radius, not
with suite size.

## Rejected Alternatives

- **In-process import of the framework route handler.** Planned, attempted, and non-viable on a
  CommonJS-default project — Node 24's `require(esm)` rules forbid it across `next/server`'s module
  cycle.
- **Requiring adopters to convert their app to ESM.** A project-wide change to the app under test,
  a serious adoption barrier, and a false green even where it works, since the testbed then no
  longer represents the real project.
- **A blanket in-process ban at every level.** Banning it for unit throws away the one precise
  coverage path the layer has.
- **Hard-coding the launch command in the harness.** The launch command and base URL are the only
  project-specific part of the contract; hard-coding them makes the harness Next-shaped.
- **`NODE_V8_COVERAGE` capture over the app process.** Spiked and measured: zero app code
  recovered, because App Router's render worker does not inherit the env-var capture.
- **Istanbul instrumentation.** `babel-plugin-istanbul` on App Router requires forcing Babel, which
  breaks Server Actions (SWC-only transform).
- **Adopting `nextcov` or the CDP dance now, as a delivery blocker.** Next-only and unverified on
  Next 16 plus Turbopack; it violates framework-agnosticism, so it is parked in `parking-lot.md` as
  a deferred per-framework adapter rather than a prerequisite.
- **`c8` over the cucumber test-runner process.** Invalidated the moment the HTTP model put the app
  in a different process from the test.
- **Leaving integration behaviors at `coverage: unknown`.** That blanks out Direction A for exactly
  the behaviors that sweep the most code.
- **Attributing coverage to compiled-chunk paths when source-map remap fails.** A falsely-attributed
  edge is worse than no edge; the behavior is marked `unknown` instead.
- **Last-write-wins merge.** A static run would downgrade a prior observed one purely by being more
  recent.
- **Treating all `unknown` results identically.** Always preserving means a red test keeps green
  edges and the gate never fires; always invalidating loses coverage the moment a level goes
  unsupported. Both failures are silent, which is why the `reason` discriminator exists.
- **Emitting an empty observed fingerprint instead of an explicit `unknown` plus reason.** Reads to
  Direction A as "nothing to re-run" — the single output that silently disables the gate.
- **Hand-authored `exercises:` in frontmatter, and the hybrid where users seed edges and observation
  refines them.** Users will not maintain edges by hand; automation is the point.
- **Approach B — one boot with `Profiler.takePreciseCoverage` deltas per scenario.** Deferred by an
  explicit rule ("only if measurement shows A is too slow"), which the 0.07s incremental
  measurement answered; it would also add a CDP dependency.
- **Running the full behavior suite on every wrap-up.** Cost would then scale with suite size,
  collapsing the scaling argument that justifies per-behavior isolation.
- **Sharing one test run across several behaviors.** Destroys per-behavior attribution, which *is*
  the fingerprint.

## Revisit Conditions

- If a framework-agnostic way to get source-remapped runtime coverage out of a running app appears,
  or a per-framework adapter becomes worth building, reopen the integration-coverage half —
  CDP plus source-map remap is the known-good design.
- If a larger suite shows static closures broad enough to raise the false-positive rate above what
  wrap-up can absorb, the static baseline needs narrowing or the explicit tier needs reviving.
- If a coverage source lands with trust between `static` and `observed`, or the reserved `explicit`
  tier returns, restate the ordering rather than extending it ad hoc.
- When enough integration behaviors accumulate that boot cost dominates selection, that is the
  trigger for Approach B.
- The in-process path stays rejected on fidelity grounds even if Node's `require(esm)` restrictions
  relax — the reason it lost is that it does not exercise the app's real interface.
