---
id: SPEC-011
title: A Project Can Overrule Any Exclusion Default, in Two Tiers
category: features
tags: [code-graph, scope, exclusions, classification, override, substrate]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-24
related_code:
  - skills/freya-code-graph/scripts/graph_ops.py
  - skills/freya-code-graph/scripts/substrate.py
  - skills/freya-code-graph/scripts/settings.py
  - skills/freya-code-graph/scripts/test_graph_ops.py
intentional_decisions:
  - "A directory verdict can re-admit a directory .gitignore excludes"
  - "Model-authored verdicts may widen graph scope, but never into an artifact tree"
  - "An override widens scope at the directory it names and does not switch off what is excluded beneath it"
  - "File-kind patterns stay excluded under any override"
  - "The contract's Exclusions object carries user and ai overrides in one list — a known, ADR-recorded divergence from the tier table"
behaviors:
  - behavior_id: BEH-051
    title: A person's source verdict admits a directory an artifact-tree name excludes
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_a_user_source_verdict_beats_an_artifact_tree_name
  - behavior_id: BEH-052
    title: A model's source verdict does not admit an artifact tree
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_a_model_source_verdict_does_not_beat_an_artifact_tree_name
  - behavior_id: BEH-053
    title: A model's source verdict does admit a root convention name
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_a_model_source_verdict_does_beat_a_convention_name
  - behavior_id: BEH-054
    title: An override does not admit the vendored tree beneath it, on either filtering layer
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestScaleAndScopeDefects.test_an_override_does_not_admit_the_vendored_tree_beneath_it
  - behavior_id: BEH-055
    title: A deeper stated exclude still carves out a directory inside an override
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-code-graph/scripts/test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_a_deeper_exclude_still_wins_inside_an_override
---

# A Project Can Overrule Any Exclusion Default, in Two Tiers

## What

A project states a verdict — `source` or `exclude` — about one of its directories,
and that verdict outranks the built-in name lists SPEC-010 describes. Two tiers
decide how far it reaches, by *who* stated it:

- A **`user`** verdict — what a committed `knowledge-base/settings.json` entry
  becomes, and what an interactive confirmation records — outranks everything: the
  artifact-tree names matched at any depth, the root convention names, and
  `.gitignore`.
- An **`ai`** verdict — model-authored, from the classification pass — outranks the
  root convention names and `.gitignore`, and never an artifact tree.
- A **`rule`** or **`gitignore`** verdict overrides nothing: those are the name lists'
  own output, so letting one override them would be circular.

Among stated verdicts the deepest ancestor wins, so a carve-out inside an override
still applies; a stated verdict beats a derived one at any depth
(`_stated_verdict`).

An override widens scope **at** the directory it names. It does not switch off what
is excluded beneath it: artifact-tree names are re-matched against the path *below*
the override root, both in the floor's own file filter (`_should_exclude`) and in
the `Exclusions` object the contract hands to every other backend
(`Exclusions._excluded_under_override`). Declaring `packages/` source therefore
admits `packages/app/src/` and still refuses `packages/*/node_modules/**`.

Where these verdicts are stored, and which store survives a clone, is SPEC-012.

## Why

The name lists are written in one file in one toolkit and applied to every
repository it is ever pointed at. Nothing in that file can know that some project
keeps real source in `target/`, or that another's `docs/` is a literate-programming
tree that genuinely is the code. Without an appeal, a wrong default is not a
default at all — it is a hardcoded answer that is unfixable in the project it is
wrong for, and it fails silently, because a narrower graph still reports success.

The tiers are asymmetric because the failure modes are: a person typing
`target: source` has made a claim about a repository they can see, while a model
guessing `node_modules: source` is an ordinary model failure whose blast radius is
an entire vendored tree. ADR-022 records that argument, the measured
npm-workspaces blowup behind the "widens at, not beneath" rule, and every rejected
alternative; none of it is restated here.

## Certainty

80. The tier table is deliberate, ADR-recorded and tested case by case, and the
"widens at, not beneath" rule was written against a measured failure. The score is
not higher because the implementation does not match the stated tiers everywhere:
`project_exclusions` passes `user` and `ai` overrides in a single list while
`_override_root` recognises only `user`, so the two filtering layers reason about
the tiers differently. ADR-022 records that divergence as open and narrow rather
than as a decision, and BEH-054's sibling test asserts only that the two layers
*agree* on the measured cases.

## Behavior

The steps belong to each test; this table only links them.

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-051 A person's `source` verdict admits a directory an artifact-tree name excludes | proposed | `test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_a_user_source_verdict_beats_an_artifact_tree_name` (unittest) |
| BEH-052 A model's `source` verdict does not admit an artifact tree | proposed | `test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_a_model_source_verdict_does_not_beat_an_artifact_tree_name` (unittest) |
| BEH-053 A model's `source` verdict does admit a root convention name | proposed | `test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_a_model_source_verdict_does_beat_a_convention_name` (unittest) |
| BEH-054 An override does not admit the vendored tree beneath it, on either filtering layer | proposed | `test_graph_ops.py#TestScaleAndScopeDefects.test_an_override_does_not_admit_the_vendored_tree_beneath_it` (unittest) |
| BEH-055 A deeper stated `exclude` still carves out a directory inside an override | proposed | `test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_a_deeper_exclude_still_wins_inside_an_override` (unittest) |

## Intentional Design Decisions

### A directory verdict re-admits a directory `.gitignore` excludes

**Decision**: a `user` or `ai` `source` verdict overrules `.gitignore`, so the graph
will read — and record edges into — files git has been told not to commit. Both
filtering layers honour this, so the file survives being passed back through the
contract's `Exclusions` as well.

**Rationale**: what to commit and what to graph are different questions. A project
that gitignores its build output and then vendors real source underneath it has
said so explicitly, and the explicit statement is the better evidence. Verified by
`test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_an_override_beats_gitignore`.

**Security Scan Note**: a finding of the form "the tool indexes paths excluded from
version control" is expected behaviour whenever a `source` verdict names such a
directory — check `knowledge-base/settings.json` and
`knowledge-base/.graph/classifications.json` before treating it as a leak. What the
graph records is file paths, import specifiers and exported symbol names; it does not
copy file contents into the artifact.

### Model-authored verdicts are allowed to widen scope at all

**Decision**: an `ai` verdict from the classification pass can pull a directory back
into scope over a convention name or a `.gitignore` entry, without a human
confirming it.

**Rationale**: unattended onboarding has no human to write a settings file, and the
alternative — a model that can only ever narrow scope — reintroduces the unfixable
default this whole mechanism exists to remove. The tier boundary is the safety
argument: the failure a model actually makes is claiming a vendored tree is source,
and that one is refused (BEH-052).

**Security Scan Note**: an `ai` `source` entry in the gitignored classification cache
is not a privilege escalation into the artifact trees; the ceiling is enforced in
`_should_exclude`. It *is* a hand-editable file, so a `user`-labelled entry there
carries the strong tier — see SPEC-012 for why the committed store is the one that
should be trusted.

### An override does not switch off exclusions beneath it

**Decision**: `{"packages": "source"}` admits `packages/app/src/` and still refuses
`packages/app/node_modules/**`; the artifact-tree names are re-matched against the
path relative to the override root.

**Rationale**: an override says a directory is in scope, not that nothing inside it
can ever be out of scope. The first implementation read it the other way and was
measured pulling every `packages/*/node_modules/**` into the graph on a two-package
workspace — and it could not be switched back off, because the classifier does not
descend into a directory whose ancestor already carries a stated verdict, so no
nested `exclude` is ever derived to catch it. ADR-022 owns the reasoning.

**Security Scan Note**: this is the reason a `source` override is a bounded action
rather than an unbounded one. A review of the override mechanism should check both
implementations of the rule, not one — they are separate code paths, and the fix was
once applied to only one of them.

### File-kind patterns stay excluded under any override

**Decision**: `*.d.ts`, `*.min.js`, `*.map` and their siblings are filtered before
verdicts are consulted, so no `source` verdict re-admits them.

**Rationale**: they are claims about what a file *is*, not about which directories a
project keeps code in — the same boundary SPEC-010 draws, and the "let everything be
overridable" alternative ADR-022 rejects. Verified by
`test_graph_ops.py#TestAProjectCanOverrideTheDefaults.test_file_kind_patterns_are_not_overridable`.

**Security Scan Note**: a declaration that a directory is source will not cause
minified or generated files inside it to enter the graph. Absence of a `.min.js` from
a graph built over an overridden directory is expected.

### A `directories` key that leaves the project is refused, not folded

**Decision**: `normalise_dir_key` returns `''` — no key, no verdict — for any name that does
not resolve to a directory *inside* this project. `containment.escapes` is the predicate,
judged in **both** path flavours, and applied to the **folded** text rather than to the text as
written.

**Rationale**: added 2026-08-24 (SEC-022, medium). Every consumer joins this key onto the
project root or matches it as the prefix of a project-relative path — the scan roots are
`project_dir / key.split('/')[0]`, and the override lookups and `Exclusions._under` compare
prefixes — so a key that escapes has no valid reading, and the build does not fail on it: it
succeeds, wrongly. Measured 2026-08-23 at `abd1de3`, a committed
`{"directories": {"../shared": "source"}}` graphed the sibling tree (`../shared/secret.ts` a
node, its exports read out of the file) and, because the scan root is the key's first
component, `..` walked back into the project and gave every in-project file a second node under
`../<checkout-name>/`. Nothing was printed and `validate_graph` returned clean. `D:/secrets` is
the same hole on Windows: the drive survives the fold, and `PureWindowsPath('C:/proj') / 'D:'`
is `D:` with the project root discarded — which is why the check does not defer to the host it
happens to be running on. A directory key is a value *declared* in checked-in data, so the
platform reading the file does not get to decide what a committed key means.

**Nor does the interpreter, and that took a second fix.** `escapes` asked
`PureWindowsPath(rel).drive`, and `pathlib` restricted a drive letter to ASCII up to Python
3.11 before delegating to `ntpath.splitdrive` from 3.12, which accepts any character. `1:x`
therefore carried no drive on 3.9 and a drive on 3.12, while the consumers here join with
`ntpath` on every version — and `ntpath.join('C:\\work\\proj', '1:x')` is `'1:x'`, the root
discarded. This refusal was therefore absent on three supported interpreters (SEC-026, found
by CI), which is why the predicate now asks `ntpath.splitdrive`: the same body the consumers
join with, so predicate and join cannot disagree.

**Folded text, not written text**, and that is the one way this differs from checking a
locator: `a/../b` and `b` have to be one key (ADR-025), so the question is whether the key the
consumers will actually join escapes — not whether a `..` appeared on the way to it.

**Refusing is all it does.** Naming a directory outside the root stays impossible rather than
becoming a third verdict here. Declaring an out-of-project root is a separate, explicit act
under `outside` (ADR-031), which grants *resolution* and never a verdict.

**Security Scan Note**: `substrate.validate_graph` now also rejects a non-project-relative key
under `files`, so backing this refusal out today produces three errors rather than silence.
That is **not a substitute** and does not make this redundant — its own message says "writing
it anyway", and by the time it runs the file has been opened and its contents are already in
the artifact being audited. That check reads the graph; this one refuses the read. A leading
`/` and a UNC-looking name still fold rather than being refused; only what escapes after
folding is dropped.

### The contract layer collapses the two tiers

**Decision**: `project_exclusions` puts `user` and `ai` `source` verdicts into the
same `overrides` list, while `_override_root` — the floor's own copy of the rule —
recognises only `user`. The tier distinction is therefore enforced on one layer and
not the other.

**Rationale**: this is a known divergence rather than a chosen design. ADR-022 records
it explicitly, along with the reason it has no measured effect today (artifact names
travel to the contract as patterns, and `_excluded_under_override` re-matches them
below the override root) and the reason the path is narrow (`_classify_with_rules`
answers artifact names before a model is asked, so an `ai` verdict on one can only
arrive from a hand-edit or a stale cache).

**Security Scan Note**: a reviewer who notices that the contract's `Exclusions` does
not distinguish the tiers has found something real and already recorded — see
ADR-022, "What the code does not do". Do not report it as unknown, and do not assume
it is harmless in a future backend: the tier boundary is the entire safety argument
for admitting model verdicts, and the property under test today is that the two
layers *agree*, not that the contract enforces the tier.

## Related Specs

- [SPEC-010: Default Graph Scope](./SPEC-010-default-graph-scope.md)
- [SPEC-012: Where a Directory Verdict Lives](./SPEC-012-directory-verdicts-and-the-classification-cache.md)
- ADR-022 — every built-in exclusion default is arguable, in two tiers
- ADR-018 — the substrate contract for the code graph (obligation 6: exclusions are an input)

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-24 | Recorded that the escape refusal was absent on Python 3.9-3.11 until the predicate stopped asking `pathlib` for the drive | SEC-026, found by CI. `pathlib` and `ntpath` disagree about what a drive letter is, and the consumers join with `ntpath` |
| 2026-08-24 | Added "A `directories` key that leaves the project is refused, not folded" | SEC-022 (medium). A committed `../shared` key graphed a sibling tree and re-entered the project through `..`, with nothing printed and `validate_graph` clean |
| 2026-08-21 | Initial spec, inferred from code during brownfield scan | Candidate behaviors recorded as `proposed` for lazy review (ADR-007) |
