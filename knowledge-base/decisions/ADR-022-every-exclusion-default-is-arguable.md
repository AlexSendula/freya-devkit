---
id: ADR-022
title: every built-in exclusion is a default a project can overrule, in two tiers
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - code-graph
  - substrate
  - scope
  - configuration
---
# ADR-022: every built-in exclusion is a default a project can overrule, in two tiers

## Decision

The directory name lists in `_get_exclusion_rules` (`graph_ops.py:1252`) are defaults, and a
project can overrule any of them. A directory verdict outranks the lists in two tiers
(`graph_ops.py:171`). A `user` verdict — which is what a directory declared in the committed
`knowledge-base/settings.json` becomes (`graph_ops.py:1595`) — beats everything, including the
artifact-tree names matched at any depth (`graph_ops.py:1256`) and `.gitignore`. An `ai` verdict
beats the root convention names (`graph_ops.py:1312`) and `.gitignore`, and never an artifact
tree. A `rule` or `gitignore` verdict overrides nothing: those are the lists' own output, so
letting one override them would be circular. Precedence is stated once and implemented once — a
stated verdict beats a derived one at any depth, and among equals the deepest wins
(`_stated_verdict`, `graph_ops.py:1369`).

Committed verdicts live in `knowledge-base/settings.json` under `directories`, alongside the
backend choice ADR-019 put there:

```json
{ "directories": { "docs": "source", "packages/legacy": "exclude" } }
```

`knowledge-base/.graph/classifications.json` keeps only the derived and model-authored verdicts.
It is gitignored regenerable cache (`CACHE_IGNORED`, `graph_ops.py:245`), and a settings-declared
verdict is deliberately kept *out* of it (`_save_classifications`, `graph_ops.py:1644`). Keys on
both paths are folded to one form, so `docs`, `docs/`, `./docs` and `docs\lit` name what the
person meant (`normalise_dir_key`, `settings.py:169`; `_parse_directories`, `settings.py:781`).

An override widens scope *at* the directory it names; it does not switch off what is excluded
beneath it. The artifact-tree names are re-matched against the path below the override root, in
the floor's file filter (`graph_ops.py:1473`) and in the `Exclusions` object the contract hands
to every backend (`_excluded_under_override`, `substrate.py:537`). So `{"packages": "source"}`
admits `packages/app/src/` and still refuses `packages/app/node_modules/`.

Two things no verdict overrides: file-kind patterns — `*.d.ts`, `*.min.js`, `*.map` — which are
claims about what a *file* is rather than about which directories are in scope, and a more
specific stated verdict beneath the override.

> **Correction, 2026-08-24.** There is a **third**, added 2026-08-23 by SEC-021: a `directories`
> key that does not fold to a path *inside* this project is dropped, whatever verdict it carries.
> `normalise_dir_key` returns `''` for it (`settings.py:169`), judged by `containment.escapes` on
> the folded text (`settings.py:240`) and therefore in both path flavours, so a committed key means
> the same thing on every host. Measured on this tree today: `../shared`, `..`, `.` and `D:/secrets`
> all fold to `''`, while `docs/`, `./docs`, `/docs/`, `docs\lit` and `a/../b` keep folding to the
> keys the paragraph above promises. The cache is folded through the same call, so a key that
> reached `classifications.json` is refused on the same line rather than by a second rule.
>
> This is not an exclusion default being made unarguable; it is the key space being closed. Every
> consumer joins a `directories` key onto the project root or matches it as the prefix of a
> project-relative path, so a key that escapes has no reading at all — and before the refusal the
> build did not fail on one, it succeeded wrongly. The measurement is in `normalise_dir_key`'s own
> docstring, pinned to `abd1de3`: `{"directories": {"../shared": "source"}}` graphed a sibling tree,
> read its file contents, and re-entered through `..` so every in-project file gained a second node,
> with `validate_graph` clean and nothing printed.
>
> **Symlinks are not a fourth tier here, and this record should not be read as if they were.** The
> non-overridable symlink refusal SEC-008 established is `_refuses_descent`
> (`skills/freya-docs-manager/scripts/detect_project.py:352`), in docs-manager's project-stack walk
> — which never reads `directories`, so no verdict in this record reaches it. Separately, a
> declaration under ADR-031 never re-authorises a crossing made through a symlink
> (`settings.py:303`, pinned by `test_graph_ops.py:3397`), and that is `outside`, not `directories`.
> What is true of the graph's own scope is narrower than it first looks, and the narrow version is
> the one worth writing down. `Path.glob` does not follow a directory symlink it meets *during*
> recursion, and the census walk takes `os.walk`'s `followlinks=False` default
> (`graph_ops.py:2840`). But `_scan_files` roots its globs at the classified source directories
> (`graph_ops.py:2007`-`:2010`), and a glob whose **root** is itself a symlink does traverse it —
> measured on Python 3.12.5: a symlinked directory reached mid-recursion yields nothing, the same
> directory used as the glob root yields its files. So a `directories` verdict of `source` naming
> a symlinked top-level directory is followed, and this record's own mechanism is the way in.
>
> That is an observation about current library behaviour, not a guarantee this record makes, and
> it is deliberately stated as the weaker claim: the earlier draft of this paragraph asserted that
> no walk descends a directory symlink at all, which is the false-containment shape ADR-031 and
> SEC-008 were both written against.

## Rationale

The lists had just been re-scoped by depth: artifact trees match at every path component, and
convention names like `docs`, `examples`, `scripts` and `generated` only at the repository root.
The objection that produced this record was that no list written in this file can know what some
other repository keeps in a folder called `docs/`. Checking whether such a project could simply
say so found the real defect. `set_classification('docs', 'source')` was accepted, written to
disk, and then silently overruled, because `_should_exclude` never consulted classifications at
all — it read them only for `exclude`, so a verdict could narrow scope and never widen it. The
lists were therefore not defaults. They were hardcoded answers with no appeal, and a wrong one
was unfixable in the project it was wrong for.

The tiers are asymmetric because the failure modes are. A person who types `target: source` has
made a claim about a repository they can see. A model asked to classify an unfamiliar directory
guessing `node_modules: source` is an ordinary failure, and its blast radius is the whole
vendored tree. That is not hypothetical in the shape, only in the source: an override with no
floor beneath it was shipped and measured on a two-package npm-workspaces fixture, where
`{"directories": {"packages": "source"}}` pulled every `packages/*/node_modules/**` into the
graph. Nothing could switch it back off, either, because the classifier does not descend into a
directory whose ancestor already carries a stated verdict (`_inherits_a_stated_verdict`,
`graph_ops.py:1395`), so no nested `exclude` is ever derived to catch it. The two filters now
agree on that case by test rather than by inspection
(`test_graph_ops.py:2158`).

The location is the other half of this decision, and it was settled before the override existed
and then not applied to it. Three properties were needed at once: the verdict has to survive a
clone, survive a cache clear, and not add a file to the project root. `knowledge-base/` gives all
three — it exists wherever freya runs, its name is hardcoded rather than configurable, and only
`.graph/` inside it is gitignored. The override was nonetheless put in `classifications.json`
first, where it worked for whoever typed it and vanished on clone: CI and every colleague
silently graphed a smaller codebase and were told the build succeeded. The same distinction
ADR-017 draws inside `.graph/` applies here — a decision and a parse cache are not the same kind
of file, and this one is a decision.

Keeping the two stores separate needs enforcement in both directions. `_load_classifications`
folds the committed verdicts over the cached ones so a build sees both (`graph_ops.py:1600`), and
persisting that result baked them into the cache as ordinary `user` entries, where they outlived
the file that declared them: deleting `"docs": "source"` from `settings.json` changed nothing,
because the cached copy still outranked every rule, survived the `RULES_VERSION` discard and
survived `--clear`, which deliberately keeps `classifications.json` (`graph_ops.py:2545`). The
cache now never holds a settings-declared verdict.

`RULES_VERSION` (`graph_ops.py:152`, currently `'2026-08-20b'`) is what lets the defaults change
at all. The classifier skips any directory already present in the cache, so without a version
stamp a corrected rule reached only fresh clones. On a mismatch the cached `rule` and `gitignore`
verdicts are discarded and re-derived; `user` and `ai` ones are judgements about the project that
no rule change invalidates, and they stay.

**What the code does not do.** The `ai` tier is enforced in the floor's file filter and not in
the `Exclusions` object the contract passes to other backends: `project_exclusions`
(`graph_ops.py:465`) puts `user` and `ai` source verdicts into `overrides` alike, while
`_override_root` (`graph_ops.py:1354`) recognises only `user`. Verified on 2026-08-21 with a
cached `{"target": {"type": "source", "source": "ai"}}`: `_should_exclude('target/a.ts')` returns
`True` and `Exclusions.excludes('target/a.ts')` returns `False`, so the same repository is scoped
one way on the floor and another under graphify, which post-filters its output through that
object. The path there is narrow — `_classify_with_rules` answers artifact names before the model
is ever asked, so an `ai` verdict on one can only arrive from a hand-edit or from a cache written
before that name joined the list — but it is open, and the tier boundary is the entire safety
argument for admitting model verdicts at all.

Two more things are true and worth saying plainly: nothing writes `directories` for you. `freya
code-graph --use` writes `substrate.backend` only (`bin/backend_setup.py:153`, merging rather
than replacing so it never discards a verdict), and `set_classification` has no CLI surface and
writes to the cache, not to the committed file. The machine-level `~/.freya/settings.json`
deliberately cannot carry `directories` at all, and says so on stderr when someone tries
(`GLOBAL_KEYS`, `settings.py:102`).

## Rejected Alternatives

- **Scope the change to this repository.** The original proposal, and the safest-sounding one:
  it would have guaranteed that no repository nobody has looked at changes behaviour. It needs a
  name or a path hardcoded into a general-purpose toolkit, and it leaves every other project with
  exactly the defect being fixed — defaults it cannot argue with. The change as made is strictly
  more inclusive than what it replaced, so its worst case is noise, never a missing edge.

- **One tier: any verdict overrides anything.** Much simpler to implement, to document and to
  reason about, and it would make a model's judgement as load-bearing as a person's, so an
  automated onboarding could fix a wrong default without a human. Rejected on the asymmetry
  above: the two sources fail differently and the cheaper failure is unbounded.

- **Read an override as switching everything off beneath it.** This is what shipped first and it
  is the natural reading of "this directory is in scope, whatever the convention decided". It
  buys a one-line rule with no depth arithmetic and no second implementation to keep in step.
  Rejected on the measured workspaces blowup: an override says a directory is in scope, not that
  nothing inside it can ever be out of scope.

- **Keep the store in `classifications.json` and commit that file.** One store instead of two,
  no key folding across two parsers, and the override would have travelled. Rejected because the
  file is rewritten on every build from re-derivable input, so committing it buys the
  per-build churn ADR-017 rejected for `graph.json` — and it would put a decision back inside the
  thing that gets discarded when the rules change.

- **A `freya.json` at the repo root, or a `"freya"` key in `package.json`.** Both are the
  conventional homes and either would have been found without documentation. The root file
  pollutes the root of every adopting project for a tool that already owns a directory;
  `package.json` is fine for Node and absent from Java, Python and Go repositories, so keying the
  polyglot toolkit's own configuration to a Node manifest is the framework assumption Track B
  exists to remove. Worth revisiting as an *optional* override for Node projects, never as the
  home.

- **Remove the arguable names from the lists instead of making them overridable.** No override
  machinery at all: a default that is not there cannot be wrong. This was tried and reverted.
  Removing `docs` outright indexed the published site's bundled JavaScript and the spike's own
  fixtures; dropping `scripts` un-excluded a root `scripts/` in every project the toolkit had
  ever run on, in order to fix one repository's nested `skills/*/scripts/`. The names are right
  at the root and wrong below it, which is a depth problem and not a naming one — so `scripts`
  stayed, root-only.

- **Let file-kind patterns be overridden too.** Consistency: one rule, everything arguable, no
  exception to explain. Rejected because `*.d.ts` and `*.min.js` answer a different question.
  Re-admitting a source map because the directory it sits in was declared source helps nobody,
  and no plausible project needs it.

- **Allow `directories` in the machine-level settings file.** Somebody who always keeps source in
  `target/` could say so once instead of per repository. Rejected and made audible rather than
  silently dropped: a global `docs: source` applies to repositories nobody has looked at, and a
  global `node_modules: source` is a vendored tree in every graph on the machine. Scope is a fact
  about one project; a parser preference is a fact about the person.

## Revisit Conditions

- **A backend arrives that selects its own files and cannot be post-filtered.** Exclusions reach
  a backend as a contract input (ADR-018) and graphify is filtered on its output because
  `graphify update` takes no exclusion flag. A backend that walks the tree itself and cannot be
  told what to skip breaks "one scope, whichever parser runs", and the tier table would need
  enforcing somewhere that backend cannot ignore.
- **Overrides stop being rare.** Today there is no command that writes `directories` and the key
  folding exists to forgive hand-editing. If adopters routinely edit the file, the folding stops
  being a courtesy and the case for `freya code-graph --scope <dir> <verdict>`, with validation
  against the tier table, becomes real.
- **The same name is overridden by many projects.** If `target`, `build` or `out` turns out to be
  real source in a large share of repositories, the answer is not that every one of them writes a
  settings file — it is that the name was misclassified as an artifact tree and belongs in the
  root-only set, or gated on a marker file. Count the overrides before assuming the list is
  right.
- **Model-authored verdicts become the normal way scope is decided** — an unattended bootstrap
  with no human to write `settings.json`. Then the two tiers are answering a policy question
  rather than a safety one, and the better fix is probably to have the bootstrap write
  `settings.json` for review than to promote `ai` to the top tier.
