---
id: SPEC-010
title: Default Graph Scope — What a Build Reads Before Anyone Configures Anything
category: features
tags: [code-graph, scope, exclusions, gitignore, substrate]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/substrate.py
  - skills/freya-code-graph/scripts/test_graph_ops.py
intentional_decisions:
  - "Artifact-tree names are matched at every path depth; convention names only at the repository root"
  - "freya's own knowledge-base/ and a backend's graphify-out/ are excluded from the graph they produce"
  - "File-kind patterns (*.d.ts, *.min.js, *.map) are excluded unconditionally — a claim about a file, not about scope"
  - ".gitignore is read as a scope input, approximated rather than implemented, with patterns kept narrow"
  - "Config-as-code (YAML, compose, manifests) is out of scope by construction and silently so — ADR-027"
behaviors:
  - behavior_id: BEH-046
    title: An artifact tree is excluded wherever its name appears in the path
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestSourceBearingDirsAreNotExcludedByName.test_build_and_dependency_trees_are_still_excluded
  - behavior_id: BEH-047
    title: A convention name at the repository root is excluded
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestSourceBearingDirsAreNotExcludedByName.test_a_top_level_convention_dir_is_still_excluded
  - behavior_id: BEH-048
    title: The same convention name below the root is graphed
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestSourceBearingDirsAreNotExcludedByName.test_the_same_name_below_the_root_is_kept
  - behavior_id: BEH-049
    title: A root-anchored .gitignore entry excludes only the root directory it names
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestGitignoreMatchingIsNotSubstring.test_a_root_anchored_pattern_does_not_match_at_depth
  - behavior_id: BEH-050
    title: A .gitignore negation re-includes a tracked file, and imports of it still resolve
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestGitignoreMatchingIsNotSubstring.test_a_negation_re_includes_a_tracked_file
---

# Default Graph Scope — What a Build Reads Before Anyone Configures Anything

## What

Every code-graph build decides which paths are graph material before any parser
runs, from three built-in inputs assembled in `_get_exclusion_rules` and applied in
`_should_exclude`:

- **File-kind patterns** (`*.d.ts`, `*.min.js`, `*.bundle.js`, `*.chunk.js`, `*.map`,
  `*.lock`, `*.log`) — applied first and unconditionally.
- **Directory names in two depth tiers.** Artifact trees — dependency, build,
  framework-cache, coverage, editor and CI directories, plus freya's own
  `knowledge-base/` and a backend's `graphify-out/` — match at *every* path
  component. Convention names (`docs`, `examples`, `scripts`, `generated`,
  `.generated`, `autogen`) match only as the *first* component.
- **`.gitignore`**, read as a scope input with git's anchoring rules and
  last-match-wins negation (`gitignore_excludes`).

The same three inputs are also handed to every other backend as the contract's
`Exclusions` object (`project_exclusions`), so a repository has one scope whichever
parser is running rather than one per backend.

Scope has a second half this spec does not own: which *extensions* a backend reads
at all, and the census that names files no backend read. The floor reads six
extensions (`FILE_PATTERNS`); config-as-code is deliberately outside all of it. See
ADR-027 for that boundary and its reasoning.

The built-in lists are **defaults, not law** — a project can overrule any of them.
That mechanism, and how far an override reaches, is SPEC-011.

## Why

A dependency graph earns its value on transitive closure, and closure over a
vendored or generated tree is noise that shows up in every blast radius computed
afterwards. The cost is asymmetric in the other direction too: a build that
excludes real source does not fail, it *succeeds over a smaller codebase* and keeps
answering confidently, so a wrong exclusion is invisible in exactly the way a
missing file is not.

The depth split exists because a single flat name list produced that failure twice
on real trees: matching `scripts` at any depth hid 40 of this repository's Python
files, and `generated` swallowed a git-tracked Next.js route at
`app/api/media/generated/route.ts`. At the repository root those names do mean what
the convention says; below it they promise nothing. Deleting the names instead was
tried and reverted — the fix is depth, not deletion (ADR-022).

`.gitignore` is consulted because it is the one scope statement almost every
project already maintains, and reading it is what lets a build be roughly right in
a repository nobody has configured.

## Certainty

85. The two depth tiers are stated in ADR-022, argued at length in the code's own
comments, and each half has a test named for the defect it closes. The residue is
that the *membership* of the two name lists is a judgement call rather than a
guarantee — which is precisely why SPEC-011 exists — so what is deliberate here is
the rule, not every name in it.

## Behavior

The steps belong to each test; this table only links them.

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-046 An artifact tree is excluded wherever its name appears in the path | proposed | `test_graph_ops.py#TestSourceBearingDirsAreNotExcludedByName.test_build_and_dependency_trees_are_still_excluded` (unittest) |
| BEH-047 A convention name at the repository root is excluded | proposed | `test_graph_ops.py#TestSourceBearingDirsAreNotExcludedByName.test_a_top_level_convention_dir_is_still_excluded` (unittest) |
| BEH-048 The same convention name below the root is graphed | proposed | `test_graph_ops.py#TestSourceBearingDirsAreNotExcludedByName.test_the_same_name_below_the_root_is_kept` (unittest) |
| BEH-049 A root-anchored `.gitignore` entry excludes only the root directory it names | proposed | `test_graph_ops.py#TestGitignoreMatchingIsNotSubstring.test_a_root_anchored_pattern_does_not_match_at_depth` (unittest) |
| BEH-050 A `.gitignore` negation re-includes a tracked file, and imports of it still resolve | proposed | `test_graph_ops.py#TestGitignoreMatchingIsNotSubstring.test_a_negation_re_includes_a_tracked_file` (unittest) |

## Intentional Design Decisions

### The toolkit's own output is excluded from the graph it produces

**Decision**: `knowledge-base/` and `graphify-out/` are in the artifact-tree list, so
freya's specs, ADRs, reference docs, caches and a backend's working notes never
appear as project source — at any depth, in any repository.

**Rationale**: graphing them is self-reference: the artifact would index the notes
written about itself, and a blast radius would route through them. `project_shape`
already skipped `graphify-out/` for the unread-file census while the exclusion rules
did not, and two copies of one idea disagreeing is the recurring failure this
codebase pays for.

**Security Scan Note**: a scanner reporting that the toolkit's own directories are
never analysed is describing an intentional exclusion, not a blind spot in coverage.
It does not mean those files are unscanned by other tools — only that they are not
graph nodes.

### `.gitignore` decides graph scope, not only commit scope

**Decision**: a path excluded by `.gitignore` is excluded from the graph, using git's
own semantics — anchored patterns are root-relative, bare names float to any depth,
and `!` negations re-include with last-match-wins.

**Rationale**: it is the scope statement a project already maintains, so honouring it
is what makes a first build roughly right with no configuration. Honouring it
*partially* was worse than either extreme: dropping `!` lines excluded files git
tracks and then emitted dangling edges to them from files that import them, and an
unanchored substring test let a `.next` entry delete
`app/api/auth/[...nextauth]/route.ts`.

**Security Scan Note**: this is a deliberate coupling of two different questions. A
tool observing that gitignored paths are absent from the graph should not report a
gap — and should note the converse, that a project may explicitly re-admit a
gitignored directory (SPEC-011), so "the graph reads ignored paths" is also a
supported state.

### File-kind patterns are unconditional and are not scope judgements

**Decision**: `*.d.ts`, `*.min.js`, `*.map` and the rest of `always_exclude_files` are
matched before anything else and cannot be argued with, unlike every directory rule
here.

**Rationale**: they answer a different question. A directory list guesses *where this
project keeps its code*; a file-kind pattern states *what this file is*. Re-admitting
a source map because the directory it sits in was declared source helps nobody. See
ADR-022 for the rejected "let everything be overridable" alternative.

**Security Scan Note**: minified and generated files being absent from the graph is by
construction. A scanner should not infer from graph absence that such a file is
unreachable or dead.

### The `.gitignore` matcher is an approximation that errs narrow on purpose

**Decision**: matching uses `fnmatch`, whose `*` crosses `/` where git's does not, so
only an explicit `**/` prefix is allowed to float a slash-bearing pattern.

**Rationale**: the approximation's natural error is to match *deeper* than git would,
which excludes more — and over-excluding is the dangerous direction, because it
produces a smaller graph under a successful build. Keeping the patterns narrow trades
a little fidelity for that safety.

**Security Scan Note**: a reviewer comparing this matcher to git's specification will
find genuine divergences. They are known and bounded to the "keeps a file git would
have ignored" direction; a report should be checked against that direction before it
is treated as a defect.

### Config-as-code is out of scope by construction, and silently so

**Decision**: Dockerfiles, compose files, Kubernetes manifests, Helm charts and YAML
generally are neither graphed nor reported as unread; no backend has a YAML
extractor and none is planned.

**Rationale**: recorded in full in ADR-027 — the relationships do not branch, and
nothing in the toolkit consumes the answer. Not restated here.

**Security Scan Note**: the absence of any deployment or manifest file from the graph
is a scope boundary, not a parsing failure. "I could not read this" and "this is not
in scope" are different sentences, and the census deliberately says only the first.

## Related Specs

- [SPEC-011: A Project Can Overrule Any Exclusion Default](./SPEC-011-two-tier-exclusion-override.md)
- [SPEC-012: Where a Directory Verdict Lives](./SPEC-012-directory-verdicts-and-the-classification-cache.md)
- ADR-022 — every built-in exclusion default is arguable, in two tiers
- ADR-027 — config-as-code and migrations are not graph material

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code during brownfield scan | Candidate behaviors recorded as `proposed` for lazy review (ADR-007) |
