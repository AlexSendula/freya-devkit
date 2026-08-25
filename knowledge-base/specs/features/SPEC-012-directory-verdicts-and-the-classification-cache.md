---
id: SPEC-012
title: Where a Directory Verdict Lives, and What Invalidates the Cache
category: features
tags: [code-graph, settings, classification, cache, configuration, non-interactive]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-24
related_code:
  - skills/freya-code-graph/scripts/settings.py
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/test_graph_ops.py
  - skills/freya-code-graph/scripts/test_settings.py
intentional_decisions:
  - "A verdict declared in settings.json is deliberately never written into the classification cache"
  - "`--clear` keeps classifications.json; RULES_VERSION is the invalidation mechanism instead"
  - "A build with no TTY never prompts and defaults an unrecognised directory to source"
  - "The machine-level ~/.freya/settings.json cannot carry `directories`, and says so on stderr"
  - "Malformed settings degrade to defaults with a warning rather than failing the build"
  - "A `directories` key that names anything outside the project is dropped; naming an out-of-tree directory is the `outside` section's job"
behaviors:
  - behavior_id: BEH-056
    title: A verdict committed in settings.json still applies with the gitignored cache deleted
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestAnOverrideSurvivesAClone.test_it_still_works_with_the_gitignored_cache_deleted
  - behavior_id: BEH-057
    title: Removing a verdict from settings.json takes effect on the next build
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestASettingsVerdictCanBeWithdrawn.test_removing_the_entry_takes_effect_on_the_next_build
  - behavior_id: BEH-058
    title: Every spelling of a directory key names the same directory
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestAnOverrideSurvivesAClone.test_the_spellings_people_actually_type_all_resolve
  - behavior_id: BEH-059
    title: A rules-version change re-derives a stale cached rule verdict
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestStaleRuleClassificationsAreRefreshed.test_a_stale_rule_verdict_is_rediscarded_and_the_dir_is_graphed
  - behavior_id: BEH-060
    title: A build with no terminal classifies an unrecognised directory instead of blocking on it
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestNonInteractiveBuild.test_ambiguous_dir_included_without_stdin
  - behavior_id: BEH-150
    title: A root declared in settings.json resolves a crossing and names it by its alias
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_settings.py#OutsideRootsTest.test_a_relative_declaration_resolves_and_a_crossing_is_named_by_alias
  - behavior_id: BEH-151
    title: Two declared roots that nest name a file the same way in either key order
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_settings.py#OutsideRootsTest.test_two_roots_that_nest_name_a_file_the_same_way_in_either_order
  - behavior_id: BEH-152
    title: A declared root is resolved into and never walked
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestCrossingTheRootIsADeclaredAct.test_the_declared_root_is_resolved_into_and_never_walked
  - behavior_id: BEH-153
    title: Changing a declaration after a build re-resolves every edge on the next update
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestCrossingTheRootIsADeclaredAct.test_a_declaration_changed_after_a_build_reaches_every_edge
---

# Where a Directory Verdict Lives, and What Invalidates the Cache

## What

Directory verdicts (SPEC-011) come from two stores, and the split between them is
the point:

- **`knowledge-base/settings.json`** — committed, hand-written, travels with the
  repository. Its `directories` map is the only store that survives a clone. Each
  entry is loaded as a `user`-tier verdict and is deliberately *never* persisted
  into the cache, which is what makes deleting an entry take effect.
- **`knowledge-base/.graph/classifications.json`** — gitignored, regenerable cache
  holding derived `rule`/`gitignore` verdicts, model `ai` verdicts, and `user`
  verdicts recorded by an interactive confirmation. Committed verdicts are folded
  over it on read, so a build sees both.

Keys are folded to one form on both paths (`normalise_dir_key`,
`_load_classifications`), so `docs`, `docs/`, `./docs`, `/docs/` and `docs\lit` name
what the person meant instead of silently naming nothing.

**Folding is not the whole rule: a key that folds to somewhere outside the project is
dropped.** `normalise_dir_key` returns `''` for it (`settings.py:169`), judged by
`containment.escapes` on the folded text (`settings.py:240`) and therefore in both
POSIX and Windows spellings, so a committed key means the same thing on every host.
Measured on this tree: `../shared`, `..`, `.` and `D:/secrets` all fold to nothing,
while `a/../b` folds to `b`. Every consumer joins a `directories` key onto the project
root or matches it as the prefix of a project-relative path, so a key that escapes has
no reading at all — before the refusal the build did not fail on one, it succeeded
wrongly. `normalise_dir_key`'s own docstring carries that measurement, pinned to
`abd1de3`: a committed `{"directories": {"../shared": "source"}}` graphed the sibling
tree, read its file contents, and re-entered the project through `..` so every
in-project file gained a second node, with `validate_graph` clean. A key that
simply matches nothing is left alone: that is a dead entry, not an escape, and refusing
it would start telling projects their settings file is wrong.

Naming a directory *outside* the project is therefore not something `directories` can
do, and that is not a gap. It is a different power with a different section, `outside`,
in the same committed file — it buys resolution of an import into a declared root and
nothing else: no file under one is opened, and no directory under one is discovered by
walking it. That is
[ADR-031](../../decisions/ADR-031-crossing-the-root-is-a-declared-act.md)'s decision
rather than this spec's; what belongs here is that the two sections live side by side
in one file, and that `..` in `directories` is a refusal rather than a shorthand for
the other one.

Cache invalidation is a `RULES_VERSION` stamp rather than a deletion: on a mismatch
the cached `rule` and `gitignore` verdicts are discarded and re-derived, while `user`
and `ai` verdicts stay. `--clear` removes the graph artifacts and deliberately keeps
this file.

The `outside` section is invalidated on the same principle by a second mechanism. A
declaration is not a per-file change, so per-file incrementality cannot see it:
`CodeGraph.update` compares the roots declared when the artifact was written against
the roots declared now and forces a full rebuild when they differ
(`graph_ops.py:2281`). Without that, an `--update` triggered by any unrelated file
leaves every unchanged file holding edges resolved under the old declarations while
the report is stamped from the new ones — reachable in both directions, and both
artifacts lie. The comparison is over the declarations and not over what they resolve
to: a root whose target is replaced on disk between two runs keeps the same signature
and does not force a rebuild, because git cannot see outside the project.

Unknown directories are classified rules → model → human. When there is no terminal
— `--non-interactive`, or `stdin` is not a TTY, which is how wrap-up and CI invoke
it — the build never prompts, and a directory the model was uncertain about is
recorded as `source` with `source: auto-source-default`.

Malformed input never fails a build: a bad verdict, a non-object section,
unreadable or invalid JSON all degrade to the default and append a warning that is
printed once.

The machine-level `~/.freya/settings.json` (overridable via `FREYA_HOME`) carries
only `substrate.backend` and `substrate.symbols`. A `directories` key there is
dropped and reported.

## Why

A verdict about scope is a decision, and a decision has to survive the two events a
cache does not: a clone and a cache clear. The first version of the override was put
in `classifications.json` — which the toolkit's own `.gitignore` declares
regenerable — and it worked for whoever typed it and vanished for everybody else, so
CI and every colleague silently graphed a smaller codebase and were told the build
succeeded. ADR-019 had already rejected that file as a home for a decision, on
exactly that ground, before the override was put in it.

Keeping the two stores separate needs enforcement in *both* directions: folding
committed verdicts into the cache on save made them outlive the file that declared
them, so withdrawing an entry changed nothing and the only way back was to
hand-edit a file the toolkit calls regenerable.

The `RULES_VERSION` stamp exists because the classifier skips any directory already
present in the cache: without it, a corrected default reached only fresh clones
while every project graphed before the change kept the old answer indefinitely.

The no-TTY default errs toward including for the reason all of this errs toward
including: a graph that silently drops real source keeps answering confidently and
narrowly, and nothing downstream can tell.

## Certainty

80. Every element here — the two stores, the non-persistence rule, the key folding,
the version stamp, the no-TTY default — is deliberate, argued in the code's own
comments and covered by a test named for the defect it closes, and ADR-022 records
the store decision. It is not higher because two nearby pieces are less settled than
they look: nothing in the toolkit ever *writes* `directories` (there is no CLI
surface for it, and `set_classification` writes to the cache rather than the
committed file), so the committed store is a hand-editing path today, and the
`source: auto-source-default` labelling of no-TTY choices is a convention this spec
infers from one call site rather than from a stated contract.

## Behavior

The steps belong to each test; this table only links them.

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-056 A verdict committed in `settings.json` still applies with the gitignored cache deleted | proposed | `test_graph_ops.py#TestAnOverrideSurvivesAClone.test_it_still_works_with_the_gitignored_cache_deleted` (unittest) |
| BEH-057 Removing a verdict from `settings.json` takes effect on the next build | proposed | `test_graph_ops.py#TestASettingsVerdictCanBeWithdrawn.test_removing_the_entry_takes_effect_on_the_next_build` (unittest) |
| BEH-058 Every spelling of a directory key names the same directory | proposed | `test_graph_ops.py#TestAnOverrideSurvivesAClone.test_the_spellings_people_actually_type_all_resolve` (unittest) |
| BEH-059 A rules-version change re-derives a stale cached `rule` verdict | proposed | `test_graph_ops.py#TestStaleRuleClassificationsAreRefreshed.test_a_stale_rule_verdict_is_rediscarded_and_the_dir_is_graphed` (unittest) |
| BEH-060 A build with no terminal classifies an unrecognised directory instead of blocking on it | proposed | `test_graph_ops.py#TestNonInteractiveBuild.test_ambiguous_dir_included_without_stdin` (unittest) |
| BEH-150 A root declared in `settings.json` resolves a crossing and names it by its alias | proposed | `test_settings.py#OutsideRootsTest.test_a_relative_declaration_resolves_and_a_crossing_is_named_by_alias` (unittest) |
| BEH-151 Two declared roots that nest name a file the same way in either key order | proposed | `test_settings.py#OutsideRootsTest.test_two_roots_that_nest_name_a_file_the_same_way_in_either_order` (unittest) |
| BEH-152 A declared root is resolved into and never walked | proposed | `test_graph_ops.py#TestCrossingTheRootIsADeclaredAct.test_the_declared_root_is_resolved_into_and_never_walked` (unittest) |
| BEH-153 Changing a declaration after a build re-resolves every edge on the next update | proposed | `test_graph_ops.py#TestCrossingTheRootIsADeclaredAct.test_a_declaration_changed_after_a_build_reaches_every_edge` (unittest) |

Four of the nine are the `outside` section, and they are the four this spec can honestly
claim: the token a declaration produces (BEH-150), that it is a function of the
declarations rather than of their key order (BEH-151), that the grant stops at
resolution (BEH-152), and that changing a declaration invalidates the cached graph
(BEH-153) — which is this spec's own subject and the reason the set is recorded here
rather than only under ADR-031. The rest of the feature's suite — the containment
question answered in both path flavours, the fail-closed property an untaught consumer
gets, and the `files`-key rule staying unconditional — is ADR-031's and
`SPEC-008`'s ground, and is deliberately not duplicated into this table.

## Intentional Design Decisions

### A committed verdict is deliberately absent from the cache that reads it

**Decision**: `_load_classifications` folds `settings.json` verdicts over the cached
ones so a build sees both, and `_save_classifications` then strips them back out — by
key for what is declared now, and by the `declared in knowledge-base/settings.json`
marker for what an older version already baked in.

**Rationale**: a copy in the cache outranks every rule, survives the `RULES_VERSION`
discard and survives `--clear`, so it outlives the file that declared it and the
committed store stops being the source of truth. That inverts ADR-019 exactly.

**Security Scan Note**: an audit that compares the two files will find the committed
verdicts missing from `classifications.json`. That is the invariant, not drift — and
the marker check means a stale entry written by an older release is removed rather
than honoured.

### `--clear` does not clear the classification cache

**Decision**: `clear()` deletes `graph.json` and every per-backend
`graph.<backend>.json`, and leaves `classifications.json` in place.

**Rationale**: the graphs are a parse cache; the classifications hold judgements a
person or a model made about which directories are source, and a cache clear has no
business discarding those. `RULES_VERSION` is the mechanism that refreshes the
*derivable* half — verified in both directions:
`TestStaleRuleClassificationsAreRefreshed.test_a_user_verdict_survives_a_rules_change`
and `.test_an_ai_verdict_survives_a_rules_change` assert the judgements stay.

**Security Scan Note**: a command called "clear cache" that leaves a file behind
reads as a bug. It is deliberate. A reviewer chasing a stale-scope problem should
look at the `rules_version` field and the verdict `source` values rather than at the
file's existence.

### A no-TTY build widens scope rather than dropping a directory

**Decision**: with `--non-interactive`, or with `stdin` not a TTY (auto-detected — the
path wrap-up and CI take), the build never prompts, and a directory the model was
not confident about is recorded as `source`, not `exclude`.

**Rationale**: the two failure modes are not symmetric. Including a directory that
turns out to be noise shows up in the artifact and can be corrected with a verdict;
excluding real source produces a smaller graph under a successful build, and every
blast radius computed from it afterwards is confidently narrow. The choice is written
into the cache entry (`source: auto-source-default`, with the model's suggestion in
its reasoning) so it is auditable rather than invisible.

**Security Scan Note**: an unattended run can therefore graph directories a human
would have excluded — including, on a project with unusual layout, generated or
vendored trees the name lists did not recognise. This widens scope and never narrows
it, so it costs noise rather than coverage. It is not a mechanism for pulling in a
recognised artifact tree: those are answered by the rules before the model is asked.

### Scope cannot be set machine-wide

**Decision**: `GLOBAL_KEYS` admits only `substrate.backend` and `substrate.symbols`
in `~/.freya/settings.json`. A `directories` key there is dropped, and a warning
naming the key is printed rather than the value being silently honoured.

**Rationale**: scope is a fact about one project; a parser preference is a fact about
the person. A global `docs: source` would apply to repositories nobody has looked at,
and a global `node_modules: source` would be a vendored tree in every graph on the
machine.

**Security Scan Note**: this is a deliberate limit on how far one configuration file
can reach, not an unimplemented feature. The warning is the intended behaviour for
that key — silence was the previous behaviour and was treated as the defect.

### Malformed configuration degrades visibly instead of failing

**Decision**: unreadable JSON, a non-object section, a verdict outside
`source`/`exclude`, a key that folds to nothing, and a hand-edited shorthand in the
cache (`"docs": "source"` where an object was expected) all fall back to the default
and append a warning; none of them raises. `_read_object` is the deliberate
exception — it refuses to *overwrite* a settings file it could not parse.

**Rationale**: a build must not fail because configuration is missing or typo'd — the
whole point of the defaults is that a project works before anyone configures
anything. But a typo dropped in silence is how a project ends up convinced it is
graphing a scope it is not, so the warnings are collected eagerly, in the
constructor, after a lazily-parsed version left every caller printing nothing.

**Security Scan Note**: broad exception handling around configuration reads is
intentional fail-open behaviour for a *read-only analysis* tool, and each path emits a
warning. The write path is deliberately fail-closed: freya will refuse to replace a
settings file it cannot understand rather than discard hand-written content.

### A `directories` key that escapes the project is dropped, not honoured

**Decision**: `normalise_dir_key` folds a key and then refuses it outright when the
folded text could name anything but a path under the project root — `..` in either
spelling, a POSIX-absolute path that survives the leading-slash fold, a Windows drive
or root. The entry beside it still takes effect; only the escaping key is dropped.

**Rationale**: the keys of `directories` are project-relative by construction, because
every consumer either joins one onto the project root or matches it as the prefix of a
project-relative path. A key that escapes has no such reading, and the build did not
fail on one — it succeeded wrongly. Naming an out-of-tree directory is a real need and
it has its own answer, `outside`, which grants resolution only; conflating the two
would have made a scope verdict into a licence to read.

**Security Scan Note**: this is a refusal, not a third verdict, and it is
non-overridable — no tier in SPEC-011 or ADR-022 reaches it. One acknowledged cost,
stated in the code rather than hidden: the Windows-drive rule is judged on every host,
so a POSIX project with a top-level directory literally named `x:` or `a:b` is told
that key does not name a directory inside the project. The boundary is exactly one
character before the colon, so `docs:v2` and `src/C:x` survive.

## Related Specs

- [SPEC-010: Default Graph Scope](./SPEC-010-default-graph-scope.md)
- [SPEC-011: A Project Can Overrule Any Exclusion Default](./SPEC-011-two-tier-exclusion-override.md)
- ADR-022 — every built-in exclusion default is arguable, in two tiers (owns the store decision)
- ADR-019 — the floor and choosing a backend (why `knowledge-base/` is the home for a project decision)
- ADR-031 — crossing the project root is a declared act (owns the `outside` section this file now also carries)

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code during brownfield scan | Candidate behaviors recorded as `proposed` for lazy review (ADR-007) |
| 2026-08-24 | Recorded the escaping-key refusal in `normalise_dir_key`, added the `outside` section as the committed file's second half, and added the declared-roots comparison as a second cache-invalidation trigger. Four behaviors added (BEH-150…BEH-153). | SEC-021 closed the escaping-key hole, and ADR-031 put a second section in the file this spec is about. The *What* section documented key folding without saying that `..` is refused there and belongs in `outside`, which reads as an unstated gap rather than a boundary. |
