---
id: ADR-029
title: every answer says what the backend could not read, and it is never a refusal
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - code-graph
  - substrate
  - coverage
  - trust
---
# ADR-029: every answer says what the backend could not read, and it is never a refusal

## Decision

Every build or update that writes a graph runs one pruned tree walk over the
project and records what it found at `graph["substrate"]["unmapped_source"]`:
how many in-scope source files the running backend cannot read, which
extensions they are, and which directories to search instead. The walk is
performed in `_finalise` (`skills/freya-code-graph/scripts/graph_ops.py:2686`)
— the single funnel every backend passes through, and the only point after
`update()` has rebuilt `graph['substrate']` wholesale. It is filtered by the
build's *own* scope rule, `CodeGraph._should_exclude` (`graph_ops.py:1411`)
plus the caller's `Exclusions`, which are the two layers `build()` itself
applies, and by a two-tier extension model (`substrate.py:863` and `:890`).

`--build`, `--update`, `--query` and `--impact` carry the block inside their
JSON answer. The first two carry it whole, including a prose `advice` sentence
and a `readable_by` recommendation; the last two carry a structured digest of
`files`, `extensions` and `directories`, plus truncation markers when they are
true (`substrate.unmapped_digest`, `substrate.py:1050`). `--dependents` and
`--dependencies` keep their bare arrays and say the same thing on stderr
(`_announce_unmapped`, `graph_ops.py:3139`). The key is **absent** — not empty
— when there is nothing to say, so a repository the backend reads completely
produces byte-identical output to what it produced before this existed.
`{"files": 0}` means the census ran and found nothing; `{"files": null,
"error": …}` means it could not run.

It is never a refusal. Nothing declines to answer, changes an exit code, or
takes a gate red because of it. The rule is written into
`skills/freya-behavior-runner/scripts/run_behaviors.py:338` as a comment beside
the `degraded_from` refusal it must not join, and pinned by
`test_a_repo_with_unmapped_files_still_fingerprints_static`.

`project_shape.classify` reports blind spots on every branch and prefers the
artifact's block to a fresh walk — but the census's **silence is not
authoritative**. It is trusted when it finds something, or when the graph has
content to be authoritative about; over an empty graph, `_blind_spots`
(`skills/freya-spec-manager/scripts/project_shape.py:217`) falls back to an
open-world walk. An empty graph over a non-empty directory returns `unknown`
with the reason that every file here is outside the graph's scope
(`project_shape.py:290`), never `greenfield`.

## Rationale

The floor backend reads 4 languages across 6 extensions; graphify reads 40
across 93 and has to be installed separately (ADR-019). What made that gap
dangerous is that it is not visible from the outside. `CodeGraph._scan_files`
(`graph_ops.py:1991`) globs by `FILE_PATTERNS`, so a file whose extension the
backend does not handle is never enumerated at Python level at all — it is not
"skipped", it is invisible. `files_scanned` is then `len(graph['files'])`
(`substrate.py:399`): it reads like a denominator and is a numerator. A
repository of twelve `.java` files with three `.ts` files in it reported
`files_scanned: 3` and mentioned Java nowhere — not on stdout, not on stderr,
not in the artifact.

ADR-005 promises the graph never answers "nothing" when it means "I don't
know". That promise had been implemented at the *repository* level — a Java
repo will not call itself greenfield — and never at the **answer** level, and
the two are different claims. "3 dependents" and "3 dependents, and a fifth of
this repo is unread" are not the same sentence. The argument for fixing it in
the payload was already written down in this codebase: `get_impact` returns
`not_in_graph` in the JSON, with the comment that "the caller is usually
another skill reading `--format json`, and stderr is not part of what it
parses" (`graph_ops.py:2538-2421`). It had been applied to "the file you asked
about is unmapped" and never generalised to "this answer is incomplete".

The consumer is not a human. `non_interactive` auto-enables whenever stdin is
not a TTY (`graph_ops.py:3570`), which is every agent-driven run and every
wrap-up run, so a printed warning lands nowhere. Verified: the three
programmatic callers — `behavior_graph.py:279`,
`skills/freya-spec-manager/scripts/drift.py:94` and `run_behaviors.py:351` —
all use `capture_output=True` and read only stdout on success. Stderr is dead
skill-to-skill. It is alive agent-to-CLI, because `bin/freya_cli.py:183` is a
plain `subprocess.call` with inherited streams. That asymmetry is what makes
the split between payload and stderr a design and not a compromise: the
surfaces whose shape cannot change get the channel an agent at a terminal
still sees, and the surfaces that can carry structure carry it.

The census uses the build's own scope rule rather than the `substrate.exclusions`
recorded in the artifact because the recorded set is a strict subset of the
real one. `_should_exclude` applies file-kind patterns, the project's own
directory verdicts (ADR-022), artifact-tree names at any depth, top-level
convention names and `.gitignore`; `Exclusions` carries only directories and
gitignore-style patterns, and on a first build it is computed before directory
classification has run — which is exactly the bootstrap build this exists to
serve. A caveat that cries wolf is worse than no caveat, because an agent
learns to skip the field and then misses the one time it was real.

Two tiers draw the noise line (`substrate.material_extensions`,
`substrate.py:922`). Definite program source is reported unconditionally: one
unreadable `.java` in a 500-file TypeScript repo is precisely the case worth
knowing about. Scripting and data-definition extensions — `.sh`, `.sql`,
`.ps1` — are reported only when their count beats both the graphed file count
and a floor of 2 (`substrate.py:902`), so one build script never fires the
caveat but a repository that genuinely is a PowerShell codebase still does.
Re-measured 2026-08-21 with the shipped code: freya-devkit is silent (two
candidate files, both tier 2, published as `files: 0`); acme-site-testbed
reports 7 files as `{".mjs": 3, ".mts": 2, ".feature": 1, ".prisma": 1}`; the
Java fixture reports `{".java": 6}` under
`src/main/java/com/example/inventory`. The closed-world list is the reason the
signal is quiet enough to be believed, and it is also its known cost — see the
revisit conditions.

`directories`, not just `extensions`, because `{".java": 12}` makes an agent
derive a search target and `{"src/main/java/com/acme": 12}` **is** one. The
paths are already in the walk's hand; both censuses that existed before this
held them and threw them away. `rollup_directories` (`substrate.py:949`)
collapses each top-level root to the deepest common prefix under it, so a
package tree becomes one grep target rather than four.

Build time is where this is free. Re-measured across four real repositories on
2026-08-21, the census walk costs 0.0016s–0.0090s, against 0.018s–2.30s that
`_scan_files` already pays on the same four. The artifact it is written into
is not tracked either way: in an adopting project `.graph/.gitignore` names
the regenerable files by name and leaves `behavior.json` committed (ADR-017),
while in *this* repository the root rule `**/.graph/` at `.gitignore:18`
ignores the whole directory, `behavior.json` included — `git check-ignore -v`
names that rule for both files here. So the block costs no tracked diff on any
machine, which is why
it can be verbose where it is written and terse where it is read.

The last part of this decision was forced by the feature breaking its own
rule. `project_shape` was changed to prefer the census over its own walk, and
treated the census's silence as an answer. But the census answers "what can
this backend not read?" — it does not answer "is there anything here the graph
does not represent?", which is broader, because it includes files that are out
of *scope* rather than out of *coverage*. A real 40-file deployment repository
whose entire codebase is fifteen shell scripts under `scripts/` — a built-in
top-level exclusion, the same rule that once stopped freya graphing itself —
is therefore censused clean, and went from `unknown` to `greenfield`. That is
ADR-005's confidently-empty answer arriving through the mechanism built to
prevent it. The two questions are separated now: the census is believed when
it finds something or when the graph has content, and an empty graph falls
back to the open-world walk, because an empty graph is exactly where a
confident "nothing" is least earned.

## Rejected Alternatives

- **Put a standing instruction in the skill layer.** The zero-code option: tell
  the agent in `SKILL.md` that the floor backend cannot read everything, and let
  it decide when to grep. It would work for every backend and every future
  surface without touching a line of Python. Rejected on ADR-019's rule, and the
  counter-argument was already sitting in this codebase at `backends.py:173`,
  written about the neighbouring hint: an instruction in the skill layer is
  "read on every invocation forever to say nothing on almost all of them". The
  only documentation this feature added is a reference-table row.

- **Say it on stderr everywhere, and change no payload.** The obvious default,
  and what the pre-existing nudge did. One code path, no schema question, no
  token cost in any answer. It loses on the measurement above: all three
  skill-to-skill callers capture stderr and read only stdout on success, so the
  warning would be discarded in exactly the runs that matter and delivered only
  to the human who is not there. The existing hint had the same defect twice
  over — it also fires only when a better backend is *already installed*
  (`backends.select`), so the nudge appeared precisely when it was least needed.

- **Wrap `--dependencies` in an envelope so it can qualify itself.** One shape
  across every surface, no stderr channel, no asymmetry to explain. Rejected
  because it breaks **closed**: `run_behaviors` validates the answer with
  `isinstance(data, list)` (`run_behaviors.py:367`) and otherwise returns
  `graph-query-failed`, which routes every confirmed and every integration
  behaviour to `coverage: unknown`; `merge_fingerprint`
  (`behavior_graph.py:43`) then freezes `behavior.json` where there is prior
  history and writes empty `exercises` where there is not, and wrap-up's
  direction-A gate runs zero behaviours and exits 0. A repo-wide silent green
  is not a loud failure — it is ADR-005's defect arriving through the door the
  validator was meant to close.

- **Wrap `--dependents` only, since nothing parses it.** Genuinely free: the
  only non-test occurrences of the flag are its own argparse declaration
  (`graph_ops.py:3550`) and the dispatch that reads `args.dependents`
  (`graph_ops.py:3622`). It would have bought the payload signal on one of the
  two bare-array surfaces at no risk at all. Rejected because it buys a shape
  asymmetry inside a trio ADR-021 presents as answering alike, on a surface
  nothing parses; the stderr line gives it the same signal at no shape cost.

- **Express blind spots through the existing `degraded_from` field.** Zero new
  plumbing — `_graph_degraded_from` already refuses on it and every consumer
  already honours that refusal. That is exactly the bug. `degraded_from` means
  "you asked for backend X and got Y", which is abnormal and worth refusing on;
  blind spots mean "the backend this project chose cannot read everything",
  which is the floor's ordinary condition on any polyglot repository. Reusing
  the field would fire the refusal on every such repo and make a routine
  condition behave like a fault.

- **Record it in `behavior.json`, so the fact travels with the clone.**
  `behavior.json` is the one artifact in `.graph/` that is committed
  (ADR-017), so this is the only option that would put the blind spot in front
  of a reviewer in a diff. Rejected because it churns: one added `.java` file
  would rewrite every behaviour's fingerprint for a fact that belongs to none
  of them.

- **Bump `GRAPH_SCHEMA_VERSION` so the census's presence is implied, instead of
  carrying a `files: 0` sentinel.** It would remove the need for a field that
  exists only to say "nothing to report" and make old artifacts
  self-identifying. Rejected on the second-order cost: `is_stale`
  (`substrate.py:267`) then forces a full rebuild on every machine
  (`graph_ops.py:2259-2193`), and that rebuild changes the graph the
  `--dependencies` closures are computed against — closures that are written
  into the **committed** `behavior.json`. Thirty bytes in an untracked file
  make the same distinction with no forced rebuild and no fingerprint churn.

- **Reuse `summarise_coverage` and the `Coverage.blind_spots` it wrapped.**
  These existed, computed something that looked exactly like the wanted answer,
  and their tests passed; reusing them would have been a few lines. They lost
  on the part that was not aggregation: `blind_spots` had no dotfile guard, so
  `.env.local` counted as a `.local` source file; it had no materiality filter;
  and it had no notion of scope at all. The missing half was never the
  aggregation, it was the scope rule. Both have since been deleted — they had
  no production caller and never had one, and a dead function that looks like
  the answer is how the next person reimplements the wrong thing.

- **Reuse `backends.extension_census` (`backends.py:244`).** Structurally the
  right walk, already written, already invoked at build time, and its result
  already thrown away. Rejected for the same two reasons the nudge beside it
  fails: it honours only `Exclusions`, a strict subset of the build's real
  scope rule, and `select()` runs it only when a second backend is already
  available — so on the machine that most needs the census it never runs at
  all.

- **Capture the census at query time, or from inside `build()`.** A query-time
  walk would always be current and would need no field in the artifact; writing
  it from inside `build()` is where a backend author would naturally put it.
  The first pays a new per-query cost where build-time capture is free, and
  answers about a *different instant* than the graph does, conflating
  "unreadable" with "not rebuilt yet". The second is silently dropped by the
  very next `--update`, because `CodeGraph.update` rebuilds `graph['substrate']`
  wholesale from a fresh `graph_metadata()`. `_finalise` is the one place that
  is after both.

- **Rename `files_scanned` to `files_graphed` and add a `files_in_scope`
  denominator.** This attacks the misreading at its source, and the name really
  is wrong. The rename churns test assertions and `format_summary` for no
  in-repo reader; `files_in_scope` requires walking *every* extension, which
  re-admits the cost the candidate short-circuit removes, and it produces a new
  misleading denominator. Measured on this repository 2026-08-21: 62 files
  graphed against 92 in-scope files of any extension — a 33% apparent blind
  spot on a repository whose material unmapped count is zero. Putting
  `unmapped_source.files` in the same object as `files_scanned` fixes the
  misreading at the point of confusion instead.

- **Filter the census by whether some installed backend could read the files.**
  It would guarantee the caveat never names a blind spot nobody can fix, which
  is a real ergonomic argument. Rejected because a Ruby repository on a machine
  with no Ruby backend would then report nothing — ADR-005's confidently-empty
  failure wearing a principled hat. It survives as `readable_by`
  (`backends.py:207`), a recommendation that is deliberately availability-blind
  and never a filter.

- **Delete `project_shape.unreadable_files` and read only the artifact.** One
  walk instead of two, and one definition of a blind spot instead of two that
  can disagree. Rejected first on blast radius — it regresses every pre-census
  graph to "no blind spots at all" and breaks fixture tests, where preferring
  the artifact and keeping the walk as fallback is six lines and breaks
  nothing. It then turned out to be load-bearing for a different reason: that
  fallback walk is what stops a censused-clean *empty* graph from reading as
  greenfield. Deleting it would have removed the fix for the regression before
  the regression was found.

## Revisit Conditions

- **An adopter reports a blind spot the census did not name.** The tier lists
  are curated and closed-world (`substrate.py:863`, `:890`), so a language
  nobody listed produces silence — a narrower instance of the hole this closes,
  accepted as the price of a signal quiet enough to be believed. One-off
  additions are the right fix. If it happens repeatedly, the model is wrong and
  the lists should invert: walk everything the backend does not cover, minus a
  known-not-source list.

- **`SCRIPT_MATERIALITY_FLOOR = 2` starts hiding something real.** It is a
  tuned guess with a number on it, chosen to silence a single `.sh` without
  silencing a twelve-file PowerShell project. A repository whose genuine
  codebase is a handful of SQL migrations under a large graphed tree will be
  told nothing about them. When that arrives, the answer is a ratio or a
  per-project override, not a larger constant.

- **In-coverage-but-out-of-scope files start mattering.** Extension is
  structurally the wrong key for the third category: a `.ts` file under a
  directory the scope rule excludes is read by the backend, absent from the
  graph, and appears in no census, because its extension is covered.
  `project_shape`'s empty-graph fallback catches only the extreme case where
  the scope rule excluded *everything*. If "why is this file not in the blast
  radius" turns out to be answered by scope more often than by coverage,
  `unmapped_source` needs a second count keyed on path.

- **`--dependencies` gains a caller that can accept an object**, or
  `run_behaviors` stops validating it with `isinstance(data, list)`. The
  stderr channel for the bare-array surfaces is forced by that one validator
  and by the three callers that discard stderr; change either fact and the
  trio can become symmetric, which is what ADR-021 would prefer. Recheck
  `run_behaviors.py:367`, `behavior_graph.py:279` and `drift.py:94` before
  assuming the split still has to exist.
