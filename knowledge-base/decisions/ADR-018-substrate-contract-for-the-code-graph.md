---
id: ADR-018
title: the code graph is produced through a contract, not by one resolver
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - substrate
  - code-graph
  - portability
  - contract
---
# ADR-018: the code graph is produced through a contract, not by one resolver

## Decision

`freya-code-graph` defines a substrate contract, in `substrate.py`. Any backend that satisfies
it can produce the code graph; the contract is the deliverable and the backends are
implementations. It is structural rather than inherited — a backend supplies `name`,
`project_dir`, `coverage()`, `available()`, `build()` and `update()`
(`substrate.py:574`) and imports no base class, because the second backend wraps a tool nobody
here controls and a contract only the incumbent can satisfy is not a contract. It is checked at
runtime, not by types: `choose_backend` calls `conformance_errors` on the backend it selected,
and a backend that fails is refused before it runs, replaced by the floor, and recorded in the
graph metadata as a degradation with the reason (`graph_ops.py:3021`). The check binds the call
itself, not just the attribute names — `BUILD_KWARGS` and `UPDATE_KWARGS` (`substrate.py:584`)
are bound against each method's signature, because "callable" is not a contract and a backend
that passes an attribute check can still be uninvokable.

Six obligations, and they are not equally enforced. **Resolve** the languages it claims, given a
project root; the backend hands back a `substrate.Result` and the contract finalises it, which
is ADR-020. **Report what it could not resolve**: an unresolvable reference is emitted as
`unresolved:<raw>`, and `validate_graph` turns that into a rule — an internal-looking edge that
names no file in the graph is an error, because anything unresolvable belongs behind the prefix
where it is visible (`substrate.py:761`). `unresolved:` is a prefix on the edge's *target*, not
a provenance value; `PROVENANCE` has exactly two members, `extracted` and `inferred`
(`substrate.py:59`), and the validator rejects a third (`substrate.py:744`). **Carry per-edge
provenance**, structurally enforced on forward and reverse edges alike; what provenance is
allowed to decide is ADR-021. **Declare coverage** — languages, extensions and relation kinds —
enforced from both ends: `conformance_errors` refuses a backend that declares no languages or
no extensions at all (`substrate.py:648`), and `validate_graph` refuses a graph containing a
file outside the declared extensions (`substrate.py:808`). **Support incremental update, or
decline it.** **Honour the project's exclusions**, which the caller passes in.

The coverage block names relation kinds as well as languages, and the vocabulary is fixed by the
contract rather than by each backend: `RELATION_KINDS` is a five-member tuple
(`substrate.py:47`), `make_edge` raises on anything outside it (`substrate.py:134`), `Coverage`
raises on a declaration outside it (`substrate.py:403`), and `validate_graph` rejects an edge
carrying one. Today homegrown declares four languages, six extensions and two relations;
graphify declares forty languages, ninety-three extensions and all five (measured on this
checkout, 2026-08-21).

Exclusions are a contract type, `substrate.Exclusions` (`substrate.py:458`), assembled by the
project and passed into `build()` and `update()`. A backend never decides for itself what is out
of scope, but it is not required to accept the exclusions natively either: graphify honours
obligation 6 as a post-filter on its own output, because `graphify update` has no exclusion flag
(`backend_graphify.py:615`).

**Obligation 5 was declared and unenforced for the whole of this feature, and was implemented on
the day this record was written.** `Coverage.incremental` is written into every graph's coverage
block (`substrate.py:411`), and until 2026-08-21 the only read in the repository was
`Coverage.from_dict` reconstituting the value it had just written. The clause existed, the branch
did not, and both shipping backends declare `True` — so nothing had ever been in a position to
notice. `run_update` now calls the backend's build path when `coverage().incremental` is false,
and takes the same safe route when a backend cannot describe its coverage at all
(`graph_ops.py:2608`). It is pinned by a test that fails under mutation of that branch.

**`coverage.relations` is still declared and unenforced**, and this record says so rather than
repeating the design's present tense: written on every build, consumed by no caller, so the
"degrade one query rather than distrust the whole graph" it was declared for is available and
unused. The vocabulary half of the same decision *is* load-bearing, because it is what makes an
edge's `kind` checkable at all — see ADR-021.

The store behind the project's exclusions is **not** `classifications.json`, which was the
original plan. `classifications.json` stayed a gitignored derived cache (`graph_ops.py:244`);
the committed store is `knowledge-base/settings.json` under a `directories` key
(`settings.py:77`). That correction, and the arguable-defaults problem behind it, are ADR-022.

## Rationale

The homegrown regex resolver covers four languages and cannot be extended to Java without
becoming a parser. But choosing a replacement *tool* means choosing again in a few years, and by
then every consumer has been built on that tool's output shape — spec-manager reads the graph's
substrate block to decide whether a repository is greenfield or merely unreadable, the behavior
graph and behavior runner read the artifact directly, and docs-manager, the security scan and
wrap-up all reach it through the CLI. Moving all of them is the cost that makes the second
choice not get made. A contract makes the parser configuration instead of architecture: the
socket is the thing that is expensive to change, so the socket is the thing that was designed.

Three of the obligations are not generic good practice; each traces to a failure this toolkit
already shipped. Dogfooding finding F7: tsconfig path aliases made every internal import resolve
as `external:`, producing a graph that reported an empty blast radius *as if it were complete*.
F9: relative imports resolved against the process cwd were dropped entirely, not even tagged.
Those are obligations 2 and 4 — never drop, and say what you could not read — and they are
ADR-005's rule applied to a substrate that is no longer ours. Obligation 5 answers the staleness
risk: an incremental pass that cannot remove deleted nodes leaves the graph asserting a
dependency that no longer exists.

Obligation 4 is the one that earns its keep in another skill's code rather than in tests. A Java
repository graphed as empty and reported as success is the headline failure Track B exists to
remove, and the fix is not in the graph builder — it is that spec-manager reads the declared
extensions out of the graph and refuses to call an unreadable repository greenfield
(`project_shape.py:117`). Declaring coverage is what makes "no dependencies" and "this backend
does not read Java" different sentences. ADR-029 generalises the same move from the repository
to the individual answer.

That the contract is real rather than decorative was demonstrated twice while building it, in
both directions. A second backend written strictly to the documented obligations passed every
attribute check, crashed the CLI on an unexpected keyword, and then exited 0 having written
nothing — which is why the contract now binds the call signature and why persistence moved out
of the backends (ADR-020). And on graphify's first real run, `validate_graph` reported files
outside its own declared extensions within seconds, catching a backend under-declaring itself
rather than catching a caller. Both are ADR-016's discipline: the interface was proven against a
real second implementation, not argued.

Exclusions belong to the contract because `vendor/ is not mine` is true whichever parser runs.
Left to each backend, the two disagree about scope on the same repository, which is worse than
either behaviour alone — a user cannot fix it in one place, and blast radius fills with
generated output nobody can switch off. This is also the obligation that proves obligations are
worth writing down separately from the code that honours them: until 2026-08-21 the built-in
name lists lived only inside the floor's own file filter, so `project_exclusions()` handed the
other backend a scope that omitted them, and a project running graphify graphed `vendor/`,
`target/` and the toolkit's own `knowledge-base/` while the floor on the same repository did
not. The obligation had been written down and honoured by one implementation. It now assembles
the built-in lists, the project's directory verdicts and `.gitignore` into the one input every
backend receives (`graph_ops.py:438`).

Relation kinds were settled in the contract's first phase rather than deferred to the phase that
added symbols, because a vocabulary invented under the pressure of a migration is worse than one
agreed before it. Deferring would have meant an edge's `kind` had no fixed set to be validated
against during the exact change that introduced kinds.

## Rejected Alternatives

- **Pick graphify and wire it in directly.** By a distance the fastest thing to ship: no
  interface to design, no floor to maintain, symbol-level relations across thirty-odd languages
  on day one, and none of the declaration machinery above. Rejected because it reopens the whole
  question the first time graphify stalls or is abandoned, and by then every consumer depends on
  its output shape — which is precisely the position the homegrown resolver had already put the
  toolkit in once. It also fails the zero-install property outright; see ADR-019 for why the
  floor is load-bearing rather than legacy.

- **Keep extending the homegrown resolver, one language at a time.** This buys real things: the
  toolkit stays stdlib-only forever, there is one code path, no third party can break a build,
  and every failure is one we can fix. Rejected because Java and anything with a non-trivial
  module system needs a real parser, not another regex family, and the project's own vision had
  already named Java as the point at which hand-rolling stops. Adding an eleventh language to a
  regex scraper is not cheaper than adding a second backend to a socket; it only looks cheaper
  the first time.

- **Choose a substrate per feature: homegrown by default, a real parser opt-in wherever a
  feature wanted one.** Attractive because it needs no contract at all and lets adoption happen
  incrementally, feature by feature, with no migration. Rejected because it answers the question
  once per feature forever, and produces exactly the divergence obligation 6 exists to prevent —
  two graphs of the same repository with different scope, and no single place to say what the
  project's scope actually is. The contract supersedes the question rather than answering it
  repeatedly.

- **Write the interface down and trust backends to follow it.** The cheapest form of a
  contract, and the one most codebases ship. It would have bought everything above with none of
  `conformance_errors`, `validate_graph` or the signature binding. Rejected on evidence rather
  than principle: this is what the first phase actually had, and a backend that satisfied every
  documented obligation still crashed the caller and wrote nothing, while another under-declared
  its own coverage. A `typing.Protocol` was the near variant and is no better — Python 3.9 is
  the floor here, and a runtime-checkable protocol only asserts that the names exist, which is
  the half of the problem that was never failing.

- **Let each backend apply its own exclusion defaults.** Zero work, and each backend gets to use
  the ignore machinery it already has, which is usually better tuned to the languages it parses.
  Rejected because the two would then disagree about scope on the same repository, with no one
  place to correct it — and because that is not hypothetical: it is what shipped for a day when
  the built-in lists were left inside one backend, and it graphed `vendor/` and `target/` for
  the other.

- **Take scope from the polyglot backend and let the floor follow it.** A tempting
  simplification: graphify already decides which files to index, so the contract could read its
  selection instead of owning one. Rejected because it strands the floor, which needs the same
  information and must work on a machine where graphify was never installed — and because it
  inverts the ownership the whole decision rests on, making project scope a property of whichever
  parser happens to be running.

- **Have a backend declare languages only.** The smallest possible obligation 4, and the first
  recommendation. Rejected on two counts. The file scanner matches on *extensions*, so every
  caller would have had to keep its own language→extension mapping, and those mappings drift
  independently — the census and the validator would eventually disagree about whether a `.mts`
  file was in scope. And omitting relation kinds defers the edge vocabulary to the migration that
  introduces symbols, where it becomes a schema change instead of a definition. The relation-kind
  declaration is currently unread, so this alternative would have cost nothing *today* — it is
  kept because the fixed vocabulary it forced into existence is what every edge is now validated
  against.

## Revisit Conditions

- **The first backend that declares `incremental=False`.** The forced rebuild now exists, and
  no shipping backend exercises it — both declare `True`, so the branch is proven only by a
  fixture. When a real backend declines, check that a full rebuild is actually what it wants:
  a backend that can drop *some* deleted nodes but not all is a third case the current boolean
  cannot express, and the honest answer might be a finer declaration rather than an all-or-
  nothing one.

- **`coverage.relations` acquires a reader, or does not.** It is declared on every build and
  consumed by nothing. If a query ever degrades on it, this is load-bearing and should be
  tested as such; if nothing has read it a year from now, strike it rather than leave a
  promise standing on an unexercised field. The same reasoning that closed obligation 5
  applies — a declaration nobody reads is indistinguishable from a false one.

- **A query surface that needs symbol-level relations.** `coverage.relations` is recorded on
  every graph and consumed by nothing. If a caller ships that needs `calls` or `inherits` and
  still does not consult the declaration before asking, the field is decoration and should be
  dropped from the block; if it does consult it, this becomes an enforced obligation and the
  record should be corrected to say so.

- **Adding a third backend requires editing `substrate.py`.** The contract is only real if a new
  backend is a new module. If `RELATION_KINDS`, `BUILD_KWARGS` or `Coverage` has to change to
  admit one, the contract leaked assumptions from its first two implementations and needs
  tightening rather than widening.

- **A backend needs a relation kind outside the fixed vocabulary, and the proposed answer is to
  let backends extend it.** Treat that as a design failure, not a feature: a vocabulary each
  backend defines for itself is a contract describing implementations, and a caller could no
  longer ask "does this backend give me calls?" in a portable way. Collapse it back to a fixed
  set and add the kind to it.
