---
id: ADR-031
title: Crossing the project root is a declared act, and it buys resolution only
status: accepted
created: 2026-08-23
updated: 2026-08-23
tags:
  - code-graph
  - substrate
  - settings
  - security
  - trust
---
# ADR-031: Crossing the project root is a declared act, and it buys resolution only

## Decision

> **Correction (2026-08-24, dated append per ADR-016).** *"Nothing outside the root is ever
> discovered"* was true of **imports** and false of **symlinks** when this record was written,
> and the gap was found by auditing this sentence rather than by the scan. A symlink committed
> inside the project whose target resolved outside it was picked up by `_scan_files`, opened,
> parsed, and its declarations published as a node's `exports` — no declaration present,
> nothing on stderr. Filed as SEC-023 and fixed the same day: discovery now asks
> `containment.within` of every candidate, so a link whose realpath leaves the project is
> refused when nothing declares its target and reported as a crossing when something does,
> in both cases without becoming a node. The sentence below now holds for both routes.
>
> Two things worth carrying forward from how it was missed. It is SEC-008's defect on the
> other traversal — that one bounded docs-manager's YAML walk and taught it to refuse
> symlinks, and the code graph's own file discovery was never given the same rule, because
> nobody asked whether the two walks had the same obligation. And a first attempt to reproduce
> it came back clean, because the fixture had no committed `settings.json` and the
> classification path differs without one. A negative result was worth nothing without that
> detail, which is the argument for writing the fixture down and not just the conclusion.

Inside the project root, discovery stays automatic and needs no configuration. Nothing outside
the root is ever discovered — not along an import, and not through a symlink. It is reached
only when the project has declared it, and only along a reference that in-project code wrote.

A project declares an out-of-tree directory in its committed `knowledge-base/settings.json`,
under a new top-level `outside` section mapping an **alias** to a **relative directory**:

```json
{ "outside": { "ui": "../packages/ui" } }
```

`outside` is a top-level section and not a third verdict on `directories`
(`skills/freya-code-graph/scripts/settings.py:122`). The reason is the key space rather than
taste: `directories`' *keys* are project-relative paths and every consumer reads them as the
prefix of one — the scan roots are `project_dir / key.split('/')[0]`, the override lookups
match prefixes, and so does `Exclusions._under`. A path outside the root has no such spelling,
which is why `{"directories": {"../shared": "source"}}` did not extend the mechanism but
corrupted the graph, measured at `abd1de3` and recorded at
`skills/freya-code-graph/scripts/settings.py:183`. `_classify_directories` cannot produce a
verdict for a directory it cannot reach through `project_dir.iterdir()` either, so an
out-of-tree entry could never carry the `ai` tier ADR-022's two-tier design is built around.

**Only relative paths are accepted, and both refusals are portability rather than security.**
`~` is refused by name (`skills/freya-code-graph/scripts/settings.py:413`): this file is
committed and `~` denotes a different directory for every reader, which is the one failure that
is silent on every machine at once. That is a deliberate divergence from `normalise_dir_key`,
which folds `~/shared` into a live key that matches nothing and says so nowhere — right there,
because a `directories` key that matches nothing is a dead entry and refusing every one of them
would start telling projects their settings file is wrong; wrong here, because a declaration is
the one entry in this file a person writes *expecting* the toolkit to look somewhere new, so
silence is the failure rather than the courtesy. An absolute path is refused because a committed
file must name the same directory in every clone. Absoluteness is judged with `containment.escapes`
(`skills/freya-code-graph/scripts/settings.py:421`) and therefore in both path flavours, so
`C:\shared` is a drive on Linux too and `/opt/sdk` is absolute on Windows 3.13 where
`ntpath.isabs` says otherwise — the 3.9/3.13 trap ADR-030 measured, arriving in a new place.

Say the limit of that plainly, because it reads like a bound and is not one: refusing absolutes
does **not** constrain where a declaration can reach. `../../../../etc` is expressible and
resolves exactly where it reads. What the relative form buys is that the destination is legible
in review and that the same commit means the same thing everywhere. The bound on what a
declaration *does* is the grant below, not this.

A declared root that resolves inside the project — lexically, or through a symlink — is refused
and sent to `directories` (`skills/freya-code-graph/scripts/settings.py:493`), because one file
must never have two spellings. A root that *contains* the project is refused
(`skills/freya-code-graph/scripts/settings.py:498`): an ancestor is not a scope, and the honest
answer to wanting one is to point freya at that directory instead. A root that names nothing is
refused too (`skills/freya-code-graph/scripts/settings.py:484`), and — the part that matters —
it is **reported**, not silently inert. Every root in force is resolved once, at parse time,
with `realpath`; containment against it is `containment.within`, which resolves both sides.

**A declaration authorises resolution, never traversal.** No declared root is globbed, walked,
or added as a scan root, and no file under one ever becomes a key in `graph['files']` — the key
space stays exactly what ADR-025 says it is. An import in an in-project file that resolves under
a declared root becomes a fourth edge-target signal beside `external:` and `unresolved:`:
`outside:<alias>/<path inside that root>` (`skills/freya-code-graph/scripts/substrate.py:79`).
`is_internal` is false for it (`skills/freya-code-graph/scripts/substrate.py:102`), so
`link_dependents` builds no reverse edge and `validate_graph` demands no node. The whole
filesystem power a declaration grants is therefore what `_resolve_fs` already exercises
in-project: `realpath` on the candidate, one `is_file()`, and one cached `listdir` of that
candidate's own directory — and the `listdir` runs only after `is_file()` has already succeeded,
so it never enumerates a directory the reference did not already land in. **No content outside
the project is ever read.**

The alias, and never the path, is what reaches an answer. It is the same string in every clone,
it carries no absolute path into an artifact, and it is what makes the token splittable on the
first `/`.

**"The same string in every clone" is a promise about the aliases as a set, so two rules make it
true rather than merely intended.** Two roots may not share an alias
(`skills/freya-code-graph/scripts/settings.py:509`): JSON cannot spell a duplicate key, so this
only fires on two spellings `strip()` folds together, which is exactly the typo `_ALIAS_CHARS`
refuses whitespace to keep out of a diff — and left unchecked both entries reached the report and
the crossing was counted once and stamped on both. And where two roots nest — `../packages` and
`../packages/ui`, an ordinary pair to write — the **most specific** one names the file, decided
by resolved path length rather than by the order the file happens to spell them
(`skills/freya-code-graph/scripts/settings.py:286`). Order-of-declaration was not a stable rule
even in principle: `settings.write` re-serialises the section with `sort_keys=True` and
`seed_project_backend` calls it on the first build of any project carrying a machine default, so
freya alphabetised the aliases itself and rewrote every crossing token in the next graph with no
code change at all. The consequence is stated where it is read: an outer root can honestly report
`crossings: 0` while an inner one covers everything it would have.

**Adoption is per consumer, and the default is refusal.** In this branch only code-graph's
containment sites honour a declaration — `CodeGraph._contain`
(`skills/freya-code-graph/scripts/graph_ops.py:724`), reached from `_resolve_fs`
(`skills/freya-code-graph/scripts/graph_ops.py:800`) and `_resolve_python_module`
(`skills/freya-code-graph/scripts/graph_ops.py:1000`), and through them from the alias and
workspace resolvers. Everything else continues to refuse every path outside the project root,
declared or not: `verify_links`, `detect_project`, `audit_engine.resolve_spec_reference`,
docs-manager and behavior-runner. That asymmetry is a decision and not an oversight.

**A consumer that has not been taught fails closed, structurally.** A crossing is only ever
spelled `outside:<alias>/<rel>` and never as an ordinary path, so an untaught consumer cannot
open one: the token has no drive, no root and no `..` in either flavour, so joining it onto any
root is safe and names nothing that exists. It refuses — `locator-unresolved`, "not found in
graph", an empty language map — it does not read. That is a property of the token rather than a
rule someone has to remember, and it is the whole reason the token is not the real relative
path.

**A symlink is an implicit crossing, so a declaration never re-authorises one.** Containment
against a declared root resolves both sides, so a symlink planted under one that points
elsewhere — back into the project, or at `/etc` — is not contained and the crossing is refused
(SEC-008).

A declared root that is *itself* a symlink is the other case and gets the other answer: it is
honoured, because nothing was crossed implicitly and refusing it would turn away an ordinary
`../packages -> ...` layout, and it is **named on stderr**
(`skills/freya-code-graph/scripts/settings.py:527`). The reason is the sentence two paragraphs
up: absolutes are refused so the destination stays legible in review, and `../packages/ui` is
only a sentence anyone can check while every component of it is what it looks like. Without the
warning neither the committed file nor `graph.json` ever names where the build actually looked,
because `to_dict` deliberately carries the declared spelling and not the resolved path. The
comparison is against the project's own realpath, so it fires on divergence the declaration
contributed rather than on every macOS checkout under `/tmp`.

**The answer says what it read from outside.** ADR-029 obliges an answer to say what it could
not read; this is the analogue, on the same funnel and with the same discipline. Every build
records at `graph['substrate']['outside_roots']`
(`skills/freya-code-graph/scripts/graph_ops.py:2676`) each declared alias, the path as written,
and how many edges crossed to it, plus every declaration that was refused and why. The key is
**absent** — not empty — when the project declares nothing, so a repository that has never used
this produces byte-identical output. A declared root nothing imported is reported with
`crossings: 0` rather than omitted (`skills/freya-code-graph/scripts/graph_ops.py:3004`): a
declaration that buys nothing is a typo or a leftover, and silent no-effect configuration is the
defect this settings file has already paid for twice. `--query` and `--impact` carry the block
in their payload (`skills/freya-code-graph/scripts/graph_ops.py:2903`); `--dependents` and
`--dependencies` keep their bare arrays and say it on stderr
(`skills/freya-code-graph/scripts/graph_ops.py:3151`), for the reasons ADR-029 measured and
which have not changed. `--format summary` carries the same sentence on all four of its surfaces
(`skills/freya-code-graph/scripts/graph_ops.py:3219`), beside the census line ADR-029 added there
for the analogous case. Without it the split was inverted on exactly the surface a person reads:
`--query --format summary` printed an `outside:` target with no qualification and `--impact
--format summary` printed a blast radius with nothing on either stream, while both carried the
block in `--format json`.

**Two sentences, because there are two facts.** "This graph leaves the project root" is a claim
about the *edges*, and gating it on a declaration merely being in force made it false in the
commonest state of a new one — a root nobody has imported through yet — on `--build` and again
on every `--dependents`. So a total of zero says the roots were **not reached**
(`skills/freya-code-graph/scripts/graph_ops.py:3010`), which is both the true statement and the
one that reads as an invitation to check the declaration.

**"Every build" includes the incremental one, and that costs a rebuild.** A declaration is not a
per-file change, so per-file incrementality cannot see it: `--update` re-resolves only what git
says moved, while the report is recomputed from the settings file as it reads now. Both
directions were reachable by touching one unrelated file and both lied — remove a declaration
and the artifact keeps `outside:` targets with nothing in force, add one and the report says
`crossings: 0` over a file that does cross. A change to the declared roots therefore discards the
cached graph and forces a full build (`skills/freya-code-graph/scripts/graph_ops.py:2254`), on
the same reasoning `RULES_VERSION` already discards cached directory verdicts. The comparison is
over the declarations and not over what they resolve to: a root whose target is replaced on disk
between two runs keeps its signature and does not force a rebuild, because git cannot see outside
the project and nothing here could notice. That bound is stated rather than implied. This matters
more than it looks: `freya-wrap-up` runs `--update`, not `--build`.

**Trust.** The declaration comes from the scanned repository's own committed settings file, so
the repository is granting itself the power to make the toolkit look outside itself. ADR-019
already accepts a structurally similar grant for backends and that decision stands and is not
reopened — but its reasoning does not transfer by analogy, and this record does not claim it
does. Naming a backend selects among programs the *operator* installed; the repository cannot
introduce one. Naming a directory is different in kind: the repository supplies the target and
there is no operator-side allowlist. This is accepted anyway, for a reason ADR-019 does not
supply, set out in the Rationale.

## Rationale

**The user asked for the feature and named the shape of it.** "Any kubernetes manifest or
architecture or separate code should be explicitly linked and made clear on where it is, and
what its directory scope is." Two halves: a thing outside the repository should be *linkable*,
and where it is should be *stated*. The alias-to-relative-path map is the first half and
`substrate.outside_roots` plus the `outside:` token are the second. Nothing here is discovered;
everything here was written down by a person and is reported back.

**Zero-config on a fresh repository is the property that makes the toolkit usable, and it is
not traded away.** Everything above the "declared" line is opt-in and absent by default: no
section, an empty section, and no settings file at all are the same answer, and none of them
produces a byte of new output. The feature costs a repository that does not use it exactly
nothing, which is the same bar ADR-029 set for the census.

**What a hostile declaration actually buys, measured rather than asserted.** "The grant is
small" is doing all the work in the trust argument, so it has to be stated concretely. Under the
resolution-only design an attacker who controls a scanned repository can cause, for a path they
also name from an in-project import: one `realpath`, one `is_file()`, and — only if that
`is_file()` succeeded — one `listdir` of the directory it succeeded in. So the power is an
existence oracle over paths ending in the resolver's candidate suffixes, plus the filenames in a
directory where the attacker had already guessed a file correctly. It is not a read, not a walk,
and not an enumeration of a directory they guessed wrong about.

**And no mechanical consumer carries the oracle's answers anywhere the attacker can read
them.** This is the part that finishes the argument and it is not in ADR-019, because ADR-019
did not need it. The victim is whoever runs freya over someone else's repository, and the
answers land in that person's `graph.json` — gitignored by the `.graph/.gitignore` code-graph
writes itself (ADR-017) — and on that person's stderr. The one artifact in this tree that is
both committed and derived from graph answers is `behavior.json`, and it is built from
`--dependents`/`--dependencies`, which filter every `outside:` target out through
`substrate.internal_ends`; `project_shape` counts crossings and quotes none of them. Each of
those is checked rather than assumed, and each is named here so the claim can be rechecked when
one of them changes.

State the limit in the same breath, because the unqualified version — "there is no path by
which the attacker reads them" — is what this paragraph said first and it was stronger than the
design. This wave newly puts the crossing into `--query --format json` and `--impact --format
json`, and docs-manager and spec-manager are *agent-driven* readers of exactly those answers
that write committed markdown, which wrap-up then commits. So the honest claim is that the
delivery channel is agent-mediated rather than absent: no code in this tree copies a crossing
into a shared file, and an agent quoting one into prose is a filename in a sentence, not a
read. That is a much smaller thing than an exfiltration primitive, and it is why this is
acceptable at a size where "the repository names an arbitrary path" would otherwise not be —
but it is a bound on the consumers, so it is only as durable as they are, and both revisit
conditions below are written to catch a consumer that moves it.

**Both of those sentences stop being true the moment a content-reading consumer honours
declarations**, which is why that is a revisit condition below and not a licence. docs-manager,
the security scan and spec bodies all write into files that *are* committed and *are* shared. A
declaration that reached them would turn an existence oracle into an exfiltration primitive with
a delivery channel, and it would need a fresh decision rather than an extension of this one.

**The resolution-only grant is also what keeps the key-space rule unconditional.** Because a
file under a declared root never becomes a key, `validate_graph`'s check that every `files` key
is project-relative (`skills/freya-code-graph/scripts/substrate.py:736`) needs no exception for
declarations — it can refuse absolutely, for every backend present and future. That check was
written in the same branch with a comment saying so, before this feature existed. A design that
made declared files into nodes would have forced a conditional there, and a conditional in the
one rule that binds a backend nobody has written yet is worth more than the nodes.

**`_contain` was already a method, and this is the change it was written for.** ADR-030 recorded
`containment.rel_within`'s intended first caller as the graph-key path, and the migration left
`CodeGraph._contain` as a one-line wrapper with a docstring saying a declared out-of-tree root
was on the roadmap and would become a second branch in it. It did, and the two call sites did
not have to be rewritten. The two questions inside it are deliberately different predicates:
in-project containment is lexical (`rel_within`, which does not resolve, so a legitimately
symlinked in-project file keeps the key the other two artifacts carry), and out-of-tree
containment resolves both sides (`within`, because that answer decides whether a path outside
the project is touched at all).

**One prefix list, because there were three.** `substrate.IMPORT_SIGNALS` carried a comment
saying it was kept in one place because three skills filter on it and a fourth prefix added
without updating all of them would be counted as an internal edge. By the time the fourth prefix
arrived there were three copies of the tuple: `substrate.py`, `graph_ops.py`, and a literal
`("external:", "unresolved:")` in `skills/freya-spec-manager/scripts/project_shape.py`, at `:60`
as of `52f4a11` — pinned to a commit for the reason `normalise_dir_key` pins its own
measurement, because the line is about to move and a reader following it would otherwise land on
the fix and be unable to see the claim. It had been justified in a docstring on the same
reasoning that a *projection* is cheaper to
duplicate than to import. That reasoning holds for the two-line edge-shape tolerance beside it
and does not hold for a vocabulary that grows. Both copies now read the one definition — the
spec-manager one through the sibling import pattern ADR-030 blesses. Left alone, `project_shape`
would have counted every crossing as this project's own wiring and reported a bare scaffold that
imports a shared design system as brownfield.

**The report distinguishes declared-and-unused from refused, and carries both.** A root with
`crossings: 0` is in force and reached nothing; a refused root is not in force at all. Both
produce a warning on stderr and ADR-029 measured that stderr is dead skill-to-skill — all three
programmatic callers capture it and read only stdout — so both are in the payload as well. A
declaration thrown away in a run nobody watched is exactly the thing a later reader of the
artifact needs told.

## Rejected Alternatives

- **A third verdict on `directories`, e.g. `{"../packages/ui": "source"}`.** The smallest
  possible surface: one existing map, one new value, no new section and no new parser. Rejected
  on the key space, which is not a style argument — that map's keys are consumed as
  project-relative prefixes by four different call sites, and a path outside the root has no
  such spelling. It is not a hypothesis: measured at `abd1de3`, a committed `../shared` key
  graphed the sibling tree, read the contents of files under it, and — because the scan root is
  the key's first component — walked back in through `..` and gave every in-project file a
  second node, silently and with `validate_graph` returning clean. The verdict map also cannot
  carry the `ai` tier for a directory `iterdir()` cannot reach, so an entry there would sit in a
  dict whose tier machinery can neither produce nor invalidate it.

- **Make files under a declared root real `graph['files']` nodes**, so that a change in
  `../packages/ui` shows up in `apps/web`'s blast radius. This is the version a user would
  probably ask for next, and it is a materially different feature rather than a bigger version
  of this one. It breaks ADR-025's single key space; it requires reading content outside the
  project, which is the whole grant this record is built on refusing; it churns `behavior.json`
  and the BACKLOG through `behavior_graph`'s file census; and a node with no edges of its own is
  ADR-005's confidently-empty answer wearing a new hat. The honest answer to wanting it is
  "point freya at the monorepo root instead", and that answer is one sentence rather than a
  design.

- **Glob the declared root as a scan root.** The obvious way to make the above work, and the one
  that reintroduces an unbounded walk of an attacker-named path. That is SEC-008's defect with a
  declaration written on it, and the declaration does not make the walk any more bounded.

- **Allow absolute paths, so `/opt/sdk` can be declared.** A genuine limitation and not a
  theoretical one: a shared SDK at a fixed absolute location cannot be declared anywhere today,
  because it is a fact about a machine and the machine-level file deliberately cannot carry
  project scope (ADR-019, ADR-022). Rejected on the committed-file argument — the same commit
  must mean the same directory in every clone — and on the Windows absoluteness instability.
  Recorded as a revisit condition rather than a closed question.

- **Allow `outside` in `~/.freya/settings.json`.** Already rejected in principle by ADR-019 and
  ADR-022 (scope is a fact about one project) and already enforced: `load_global` filters to
  `GLOBAL_KEYS` and reports anything else as "not a machine-level setting". No code was needed
  and none was written.

- **Gate declarations on the enclosing VCS root: a root inside the project's own git root is
  honoured silently, one outside it is refused unless the operator permits it at machine
  level.** This is the only option that makes the trust argument transfer *by construction*
  rather than by the grant being small, it is about twenty-five lines of stdlib, and it covers
  the entire monorepo motivating case at zero configuration. Rejected for now because with the
  grant reduced to stat-only it defends a threat this design has already removed, and it buys
  that defence with a new machine-level key, a second tier of declaration, and an install-time
  question nobody has asked for. It is the first thing to reach for if the grant ever widens.

- **A separate absoluteness gate using `containment.is_anchored` before the relative-path
  check.** Written into an earlier draft of `_outside_target` and deleted after measurement: it
  was redundant. Stripping leading `../` from an absolute value strips nothing, so an absolute
  path arrives at the `containment.escapes` line as its own tail and is refused there with the
  same sentence. Recorded because the two predicates look like they ask different questions here
  and do not, and because a dead branch in a security-adjacent parser is how the next person
  concludes the live one is optional.

- **Emit the real relative path, `../packages/ui/src/Button.tsx`, as the edge target.** No new
  vocabulary, no `IMPORT_SIGNALS` change, no ADR-021 amendment. Rejected because it is the exact
  inverse of the fail-closed property: every untaught consumer in the tree joins a target onto
  the project root and opens it, so this hands all of them a working path out of the repository
  — and `_scan_files`, which has no containment check at all, would consume it. It is also what
  the accidental `../shared` key already did, so its consequences are measured rather than
  predicted.

- **Report the crossing only on stderr, and change no payload.** One channel, no schema
  question, no tokens spent in any answer. Rejected on ADR-029's own measurement, which has not
  changed: all three skill-to-skill callers capture stderr and read only stdout on success, so
  the caveat would be discarded in exactly the runs that matter.

- **Refuse the second of two nested roots, instead of resolving to the most specific.** Symmetric
  with the in-project refusal, one more `containment.within` call, and the honest advice would be
  "declare only the outer one". Rejected because it is not honest advice: `../packages` and
  `../packages/ui` mean different things in a report, and a project that wants both a coarse
  bucket and a named package is asking for something reasonable. Longest-resolved-path-wins costs
  one `sorted` in the constructor, makes the token a function of the declarations rather than of
  their order, and the only thing it owes the reader is the `crossings: 0` caveat recorded above.
  A duplicate *alias* is refused, because that one really is a typo with no legitimate reading.

- **On `--update`, keep the incremental pass and refuse to write a report known to be
  inconsistent** — say so when a surviving edge names an alias nothing declares. Cheaper than a
  rebuild and it closes the loudest half. Rejected because it only closes that half: the mirror
  case, adding a declaration, leaves every unchanged file carrying `unresolved:` with nothing
  anomalous for such a check to see, and the report reads `crossings: 0` over a file that
  crosses. A detector that catches one direction of a two-directional defect is worse than the
  rebuild it saves, because it reads as coverage.

- **Delete `parse_outside`'s `None` and non-dict guards as dead code.** They are unreachable
  through `load()` — `DEFAULTS` carries `'outside': {}`, so the section is type-checked there and
  the default substituted with a different sentence. Rejected, but only just, and the reason is
  the same one that deleted `is_anchored` above: a branch no test can reach is how the next
  reader concludes the live ones are optional. Kept because this is a module-level parser with a
  public name, and closed by giving them a caller — a test that invokes `parse_outside` directly
  and asserts *its* sentence rather than the substring it shares with `load()`'s.

## Revisit Conditions

- **A content-reading consumer wants to honour declarations.** docs-manager reading a declared
  root's markdown, the security scan scanning it, behavior-runner executing a test located under
  one. Any of these changes the grant from an existence oracle to a read, and puts the result
  into artifacts that are committed and shared — which removes both halves of the trust argument
  in the Rationale at once. That is a new decision, not an extension of this one, and the
  VCS-root tier above becomes the obvious answer rather than an over-engineered one.

- **Any consumer starts copying a crossing into a committed file**, whether or not it reads
  content under a declared root. This is the weaker sibling of the bullet above and it is
  separate because the strong one does not cover it: a skill that merely quotes a `--query`
  answer into markdown that wrap-up commits has read nothing outside the project and has still
  moved the oracle's answers somewhere the attacker can read them. The delivery channel the
  Rationale relies on is agent-mediated, and the four mechanical consumers it names —
  `graph.json`, `behavior.json`, `project_shape`, stderr — are what make that true today. When a
  fifth appears, recheck them by name rather than re-reading the paragraph.

- **An adopter needs an absolute root.** The `/opt/sdk` case. It has no home today because it is
  a machine fact and the machine-level file cannot carry project scope. If it arrives, the
  question to answer first is *whose* fact it is — that decides whether it belongs in a new
  machine-level section keyed by project, or nowhere.

- **A backend needs the declared roots as a contract input.** They are not in
  `substrate.Exclusions` today, and a backend that resolves imports itself (graphify does) will
  eventually want to know about them. At that point `outside` stops being a code-graph
  configuration and becomes part of the substrate contract, which is an ADR-018 change.

- **A second backend starts emitting `outside:` tokens.** Nothing validates the alias in a token
  against the declared roots — `validate_graph` treats any `outside:` target as a signal and asks
  nothing further of it. That is correct while the only producer is the resolver that also reads
  the declarations. A second producer makes an unvalidated alias possible, and the check to add
  then is that every alias in a token was declared.

- **A project on graphify reads `crossings: 0` and believes it.** The report is written by
  `_finalise`, which every backend passes through, but only the floor resolver honours
  declarations. So a project that declares a root and switches backend gets a block saying the
  root is in force and nothing crossed it, when the truth is that this backend never looked.
  Accepted for now because the alternative is a contract flag for a capability one backend has,
  and the honest fix arrives with the bullet above rather than before it. If an adopter is
  misled by it, the answer is a `honours_declarations` bit on `Coverage` and a report that says
  "not consulted" instead of a zero.

- **The `outside:` vocabulary needs to be in ADR-021.** That record presents the edge-target
  classification as three-way and is now one short; it cites `substrate.py` for the tuple, which
  is now four-way. It is deliberately not edited here, because this record's grant over
  `knowledge-base/` is itself and nothing else. This bullet is the whole of the deferral: there
  is no backlog file to appeal to that a reader of this repository could check — `BACKLOG.md`
  is generated and says so in its own banner — so the omission is dated and named here instead
  of being assumed to be recorded somewhere else. An ADR-021 that still reads three-way is a
  known gap as of `52f4a11`, not an oversight.
