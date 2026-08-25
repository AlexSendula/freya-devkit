---
id: SPEC-013
title: Project Stack Detection
category: features
tags: [docs-manager, detection, polyglot, bootstrap, project-shape]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-24
related_code:
  - skills/freya-docs-manager/scripts/detect_project.py
  - skills/freya-docs-manager/scripts/test_detect_project.py
  - skills/freya-spec-manager/scripts/project_shape.py
intentional_decisions:
  - "A source-file census decides the runtime only when no manifest declares one, and the answer is flagged runtime_source: file-extensions so a caller can tell inference from declaration"
  - "Framework detection runs most-specific-first, so branches that look unreachable (react after react-native) are deliberate"
  - "A pnpm-workspace.yaml that declares no packages is not a workspace root"
  - "An unrecognised project reports an empty runtime block rather than a default runtime"
  - "Every existence question over the whole tree goes through walk_project's contained, pruned, capped walk — the extension census keeps its own os.walk, contained only by followlinks=False — and a manifest reachable only through a symlink is deliberately not detected"
behaviors:
  - behavior_id: BEH-061
    title: A repo whose manifest declares its stack reports that runtime and the package manager its lockfile implies
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#RuntimeDetectionTest.test_node
  - behavior_id: BEH-062
    title: A Maven or Gradle repo is reported as the jvm runtime instead of no runtime at all
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#JvmDetectionTest.test_maven
  - behavior_id: BEH-063
    title: A repo with no manifest is classified from the source files present, and the result says it was inferred
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#ManifestlessProjectTest.test_a_python_repo_without_a_manifest_is_still_python
  - behavior_id: BEH-064
    title: A declared manifest outranks the source-file census
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#ManifestlessProjectTest.test_a_manifest_always_beats_the_file_census
  - behavior_id: BEH-065
    title: A repo the detector does not recognise reports an empty runtime block rather than a guess
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#RuntimeDetectionTest.test_an_unrecognised_project_reports_nothing_rather_than_guessing
  - behavior_id: BEH-066
    title: A project with no detectable test tooling reports an empty runner list as an answer, not as a failure
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#TestRunnerDetectionTest.test_a_project_with_no_test_tooling_reports_an_empty_runner_list
  - behavior_id: BEH-154
    title: A directory the walk reads as a symlink is never descended into
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#WalkContainmentTest.test_a_directory_the_walk_reads_as_a_symlink_is_never_descended
  - behavior_id: BEH-155
    title: A manifest reachable only through a symlinked directory is deliberately not detected
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#WalkContainmentTest.test_a_manifest_reached_only_through_a_symlinked_directory_is_not_detected
  - behavior_id: BEH-156
    title: The whole-tree walk stops at its file limit
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#WalkBoundsTest.test_the_walk_stops_at_its_file_limit
  - behavior_id: BEH-157
    title: The ceilings that ship are the ones the bound tests only simulate
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#WalkBoundsTest.test_the_shipped_ceilings_are_the_ones_the_rows_above_only_simulate
  - behavior_id: BEH-158
    title: A YAML file that is not valid UTF-8 is skipped and the scan carries on
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#InfrastructureReadTest.test_a_yaml_that_is_not_valid_utf8_is_skipped_rather_than_fatal
---

# Project Stack Detection

## What

`freya detect-project [dir]` prints one JSON description of a repository: its runtime and
package manager, frontend/backend framework, database and ORM, infrastructure and CI, the
documentation that already exists, the documentation that is still needed, and the test
runners it can see. Every field is derived from files on disk; nothing is asked of the user
and nothing is cached.

The runtime question is answered in two tiers. A manifest (`package.json`, `pyproject.toml`,
`requirements.txt`, `go.mod`, `Cargo.toml`, `composer.json`, `pom.xml`, a Gradle build or
settings file) decides it outright, with the lockfile choosing between the package managers a
runtime allows. Only when no manifest exists does a census of source-file extensions decide,
and that answer is marked as inferred. A repo with neither is described by an empty runtime
block.

The same call also reports whether the repo declares workspaces (npm `workspaces`, or a
`pnpm-workspace.yaml` that actually lists packages) and which test runners are present, with
the evidence for each. Existing-documentation detection is part of the same output and is
specified separately in [SPEC-014](./SPEC-014-existing-docs-detection.md).

**Every *existence* question over the whole tree goes through one bounded walk — the
extension census at `detect_project.py:98` is the module's other whole-tree walk and keeps its
own, bounded at 5,000 (see "Every existence question over the whole tree goes through one
bounded walk" below).** `walk_project`
(`skills/freya-docs-manager/scripts/detect_project.py:375`) yields this project's files —
contained, pruned, capped and in a stable order — and it replaced five `glob(**/…)` call
sites that had none of those four properties. It refuses to descend a directory that is a
symlink and never yields a file that is one (`_refuses_descent`, `detect_project.py:352`),
prunes `_CENSUS_SKIP` and dot-directories, stops at 20,000 files
(`_WALK_FILE_LIMIT`, `detect_project.py:326`), and sorts both lists so a walk that stops at a
cap examines the same files twice running. `glob_search` survives for root-only patterns and
says in its docstring that a `**` pattern must not come back
(`detect_project.py:307`). Infrastructure detection reads file *bytes* on top of that, under
three further ceilings: 64 KiB per YAML file, 500 files, and a 4 MiB whole-scan budget
(`detect_project.py:347`–`:349`). The caller that shells out to this command bounds it once
more, at 60 seconds (`project_shape.py:87`).

Consumers are `freya-docs-manager` (which doc templates to plan) and
`freya project-shape` (`skills/freya-spec-manager/scripts/project_shape.py:255`), which folds
the stack summary into the greenfield/brownfield recommendation that `spec-manager bootstrap`
shows before it branches.

## Why

Every downstream question the toolkit asks — which doc set a project needs, which test runner
a behavior can be run under, whether a bootstrap should scan or start clean — needs to know
what kind of project it is looking at. Before the polyglot work this detector could not see a
JVM repo at all, so a Maven project produced no runtime and every dependent question had
nothing to answer from; and a repo with source but no manifest (freya-devkit itself is roughly
fifty Python files with no `pyproject.toml`) was equally invisible.

The guiding constraint is that a wrong stack answer is worse than no stack answer: it selects
the wrong doc templates and the wrong runner, and the user has no signal that anything went
wrong. So the detector prefers declared facts, marks inferences as inferences, and returns
nothing when it knows nothing.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-061 Manifest and lockfile decide runtime and package manager | proposed | `test_detect_project.py#RuntimeDetectionTest.test_node` (unittest) |
| BEH-062 A Maven or Gradle repo is the jvm runtime | proposed | `test_detect_project.py#JvmDetectionTest.test_maven` (unittest) |
| BEH-063 No manifest → source-file census, flagged as inferred | proposed | `test_detect_project.py#ManifestlessProjectTest.test_a_python_repo_without_a_manifest_is_still_python` (unittest) |
| BEH-064 A manifest outranks the census | proposed | `test_detect_project.py#ManifestlessProjectTest.test_a_manifest_always_beats_the_file_census` (unittest) |
| BEH-065 An unrecognised repo reports nothing, not a default | proposed | `test_detect_project.py#RuntimeDetectionTest.test_an_unrecognised_project_reports_nothing_rather_than_guessing` (unittest) |
| BEH-066 No test tooling → an explicit empty runner list | proposed | **no test** — `detect_test_runners` is uncovered (manual) |
| BEH-154 A directory the walk reads as a symlink is never descended into | proposed | `test_detect_project.py#WalkContainmentTest.test_a_directory_the_walk_reads_as_a_symlink_is_never_descended` (unittest) |
| BEH-155 A manifest reachable only through a symlinked directory is deliberately not detected | proposed | `test_detect_project.py#WalkContainmentTest.test_a_manifest_reached_only_through_a_symlinked_directory_is_not_detected` (unittest) |
| BEH-156 The whole-tree walk stops at its file limit | proposed | `test_detect_project.py#WalkBoundsTest.test_the_walk_stops_at_its_file_limit` (unittest) |
| BEH-157 The ceilings that ship are the ones the bound tests only simulate | proposed | `test_detect_project.py#WalkBoundsTest.test_the_shipped_ceilings_are_the_ones_the_rows_above_only_simulate` (unittest) |
| BEH-158 A YAML file that is not valid UTF-8 is skipped and the scan carries on | proposed | `test_detect_project.py#InfrastructureReadTest.test_a_yaml_that_is_not_valid_utf8_is_skipped_rather_than_fatal` (unittest) |

BEH-155 is the accepted cost of BEH-154 and is recorded as a behavior rather than as a
caveat, because it is the one user-visible thing this module stopped doing. BEH-157 exists
because the other bound rows all inject their own cap: measured 2026-08-23, setting all
three shipped ceilings to `10 ** 15` left the module's suite green, so without it the
unbounded traversal was one token away with nothing red. Two further containment rows are
covered by the same classes and not listed separately — a file that is itself a symlink is
never opened (`WalkContainmentTest.test_a_file_the_walk_reads_as_a_symlink_is_never_opened`)
and `walk_project`'s own prune is load-bearing independently of `os.walk`'s
`followlinks=False` default
(`WalkContainmentTest.test_the_modules_own_refusal_is_what_prunes_a_symlinked_directory`).

Sibling scenarios already covered by the same test classes, and folded into the behaviors
above rather than listed separately: Python/Go/Rust manifests (`RuntimeDetectionTest`), Gradle
and the Kotlin DSL (`JvmDetectionTest.test_gradle`, `.test_gradle_kotlin_dsl`), the dominant
language winning a mixed census (`ManifestlessProjectTest.test_the_dominant_language_wins`),
and vendored trees being excluded from it
(`ManifestlessProjectTest.test_dependency_trees_do_not_decide_the_runtime`).

## Intentional Design Decisions

### The file census is a fallback, and it labels itself

**Decision**: When no manifest is found, the runtime is inferred by counting source-file
extensions, and the result carries `runtime_source: "file-extensions"`. When a manifest is
found, that key is absent. The census walks the tree but skips vendored and generated
directories (`_CENSUS_SKIP`) and stops after 5,000 source files.

**Rationale**: "This project does not declare a manifest" is not the same as "this project has
no language", and tool, plugin and script repositories routinely have no manifest. The flag
exists so a caller can treat an inference differently from a declaration; without the skip list
a repo's `node_modules` would outvote its own `src/`, and without the cap the walk cost would
scale with a dependency tree rather than with the project.

**Security Scan Note**: The unbounded-looking `os.walk` is bounded by both the skip set and the
5,000-file limit, and it only reads filenames — no file contents are opened during the census.
Read that as a claim about *this* walk and not about the module: the census is one of two
whole-tree walks and the smaller one. The other is `walk_project`, which stops at 20,000
because it answers existence questions where the deciding file can be the last in sorted
order, and the infrastructure detector reads bytes through it under three more ceilings. The
two limits differ on purpose and the difference is argued at `detect_project.py:319`–`:326`.

### Framework checks are ordered most-specific-first

**Decision**: The frontend chain tests `expo`, then `react-native`, then `next`, `nuxt`, and
only then `react`. The later branches are reachable, but never for a project that matched an
earlier one.

**Rationale**: Every Expo app has `expo`, `react-native` *and* `react` in its dependencies, so
testing `react` first would classify a mobile app as a web app and choose web documentation
templates for it. The ordering is the classification, not an accident of writing.

**Security Scan Note**: Not a security decision. A reviewer scanning for dead branches should
read this chain as a precedence table; removing the "redundant" earlier tests changes the
answer for every React Native project.

### JVM build files are read as text, not parsed

**Decision**: `pom.xml`, `build.gradle` and `build.gradle.kts` are read as lowercased text and
matched for substrings (`spring-boot`, `quarkus`, `micronaut`, `io.ktor`) rather than parsed as
XML or Groovy/Kotlin.

**Rationale**: The only question asked of the build file is which framework is on the
classpath. One substring test answers it for all three formats; three real parsers (one of
them for a JVM language) would be a large dependency for the same answer.

**Security Scan Note**: No XML parser is invoked, so the usual XXE/entity-expansion findings
against `pom.xml` handling do not apply here. Read errors are swallowed deliberately — a build
file that cannot be read means "no framework detected", not a crash mid-detection.

### A `pnpm-workspace.yaml` with no packages is not a monorepo

**Decision**: The presence of `pnpm-workspace.yaml` is not sufficient; the file must contain a
top-level `packages:` key with at least one list entry. npm workspaces are read the same way —
the `workspaces` key must be a non-empty list, or an object with a non-empty `packages`.

**Rationale**: `pnpm-workspace.yaml` is also where a single-package repo puts build settings
such as `onlyBuiltDependencies`; the testbed has exactly that file. Treating its presence as a
workspace declaration would make single-package repos claim to be monorepos, and monorepo
documentation describes a different thing.

**Security Scan Note**: Not security-relevant. Note that the YAML is scanned line-wise rather
than parsed, which is why no YAML loader (and no `yaml.load` finding) appears here.

### An empty test-runner list is a result

**Decision**: `detect_test_runners` returns `{"runners": [], "evidence": []}` for a project
with no detectable test tooling, and persists nothing. Callers re-run detection whenever they
need it.

**Rationale**: The behavior layer treats "this project has no test runner" as a loud fact that
changes what can be proposed, not as a missing value to be filled in later. Statelessness
avoids a cached answer surviving the moment a runner is added.

**Security Scan Note**: Not security-relevant.

### Every existence question over the whole tree goes through one bounded walk

**Decision**: `walk_project` is the only way this module answers an *existence* question over
the whole tree — it is not the module's only whole-tree traversal, and the qualifier is load-
bearing. It refuses to descend a directory that is a symlink, never yields a file that is one
(`_refuses_descent`, `skills/freya-docs-manager/scripts/detect_project.py:352`), prunes
`_CENSUS_SKIP` and dot-directories, stops at 20,000 files and sorts both lists. Infrastructure
detection reads *bytes* through it — never text — under a 64 KiB per-file prefix, a 500-file
cap and a 4 MiB whole-scan budget. Errors are caught as `OSError` only, which is sufficient
precisely because the read is bytes. The **extension census keeps its own `os.walk`**
(`infer_runtime_from_sources`, `detect_project.py:98`, walk at `:102`): it prunes the same
`_CENSUS_SKIP` and dot-directories inline, stops at 5,000, and reads filenames only — but it
never calls `_refuses_descent`, so its containment is `os.walk`'s `followlinks=False` default
and nothing else. That default holds today and is not a guarantee this project states
(ADR-022's correction declines to promise library defaults); the census is contained by it,
not by the rule this section names. `glob_search` (`detect_project.py:307`) also survives, and
does not reach the tree only because its one live call site passes root-only patterns
(`detect_project.py:559`) and its docstring forbids a `**`.

**Rationale**: the five `**` globs this replaced descended directory symlinks, pruned nothing
and stopped at nothing, so a committed `vendor -> /` made every one of them walk the
operator's whole filesystem and read files outside the tree it was pointed at (SEC-008). One
link to a big tree is the vector; no cycle is needed. Fixing only the YAML site — which is
the one the finding named — would have left the same denial of service under four other
pattern strings, so the replacement is one bounded walk rather than five patched globs. The
dot-directory skip is the clause that had to be *kept* rather than added: `glob` never
returned anything under `.git`, and `os.walk` walks straight into it, so omitting it would
have widened the read surface to `.git`, `.ssh` and `.aws` — the fix making the finding
worse.

**Security Scan Note**: the byte-reading is deliberate and is not a missed decoding step. The
obvious repair — keep the text read and swap the bare `except:` for `except OSError` — does
not work: one undecodable byte raises `UnicodeDecodeError`, which is a `ValueError`, so that
change would have turned a swallowed error into an uncaught traceback out of
`analyze_project` with no JSON on stdout (BEH-158). Two costs are accepted and stated rather
than hidden: a manifest reachable only through a symlinked directory is no longer detected
(BEH-155), and the case-folding `any_project_file` applies means the four replaced patterns
now match names on POSIX that `glob` did not — a tree whose only model file is `Models.py`
reports the Django ORM where it used to report none.

## Related Specs

- [SPEC-014: Existing Documentation Detection](./SPEC-014-existing-docs-detection.md) — the
  other half of `detect-project`'s output
- [SPEC-015: The Docs Graph](./SPEC-015-docs-graph.md) — the other artifact docs-manager owns

## Notes on Certainty

80. The behaviors are inferred from code plus a test suite whose names state the intent
directly, and three of them (JVM, manifest-less repos, mobile frameworks) carry code comments
naming the bug they fixed, which is strong evidence of deliberateness. Held below 85 because
`detect_test_runners` has no test at all, so the "empty list is an answer" guarantee rests only
on its docstring, and because nothing pins the *shape* of the JSON that `project_shape.py`
reads back out of it.

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred by brownfield scan | Behaviors recorded as `proposed`; no human has confirmed this intent yet |
| 2026-08-24 | Recorded the bounded walk: `walk_project`, its containment/prune/cap rules, the three byte ceilings on infrastructure reads and the 60-second timeout on the shelled-out call. Five behaviors added (BEH-154…BEH-158), and the census's Security Scan Note narrowed to the walk it is actually about. | SEC-008. The module gained one bounded walk in place of five unbounded `**` globs, and the spec described a detector whose only stated bound was the 5,000-file census — which a reader would reasonably have taken as covering the whole module. |
| 2026-08-24 | Narrowed the same decision the same day: "`walk_project` is the only way this module reaches the whole tree" was false and is now scoped to *existence* questions, with the extension census's own `os.walk` and its `followlinks=False`-only containment named in the Decision. Heading and frontmatter entry follow it. | The correction wrote a new false invariant into an authoritative document. `grep -n "os.walk("` on `detect_project.py` returns `:102` inside `infer_runtime_from_sources` as well as `:405` inside `walk_project`, and `:102` never calls `_refuses_descent` — so a reader took away that one guard covers traversals it does not touch. |
