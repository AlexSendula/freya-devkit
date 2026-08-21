---
id: ADR-027
title: Config-as-code and migrations are not graph material; schemas are, where a backend reads them
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - code-graph
  - substrate
  - scope
---
# ADR-027: Config-as-code and migrations are not graph material; schemas are, where a backend reads them

## Decision

Nothing in this toolkit is built for config-as-code. There is no resource graph over
Dockerfiles, compose files or Kubernetes manifests, no Helm support, no identifier index over
environment variables, image names and service names, and no HCL parser of our own. Database
schemas are treated as code and are graphed wherever the running backend already reads the file
they live in. Migrations get no treatment at all: they are not folded, not chained, and not read
as an ordered log. Where a backend parses one of these files as part of its ordinary work,
whatever it produces is kept as ordinary graph content and nothing is done with it specially.

What that comes to in the shipped code is narrower than the sentence above suggests, and it is
worth stating exactly. The floor reads six extensions — `.ts`, `.tsx`, `.js`, `.jsx`, `.py`,
`.go` (`FILE_PATTERNS`, `graph_ops.py:34`). The graphify backend declares ninety-three, among
them `.sql`, `.tf`, `.tfvars` and `.hcl`, plus `.json` and `.xml` as manifests only
(`backend_graphify.py:202`, `:224`). Neither has a YAML extractor, and neither has a `.prisma`
extractor: verified on 2026-08-21 by reading `graphify.extract._DISPATCH` out of graphifyy
0.9.47's own interpreter, where `.yaml`, `.yml` and `.prisma` all dispatch to nothing. So of the
four schema forms the working record listed, Django models are graphed as ordinary Python by
both backends because they are `.py`; JPA entities are graphed by graphify and not by the floor
because they are `.java`; `*.sql` is declared by graphify behind its optional `sql` extra; and
`schema.prisma` — the most common of the four — is graphed by no backend at all.

A file no backend reads is *declared* unread rather than passed over in silence, and the two
tiers of that census (ADR-029) are where this decision shows up in the artifact. `.prisma`,
`.tf`, `.tfvars` and `.hcl` are tier-1 program source (`substrate.py:841`) and are reported
unconditionally. `.sql` is tier 2 (`substrate.py:848`), reported only when the unread count
beats both the graphed file count and a floor of two (`material_extensions`,
`substrate.py:880`), so a handful of migrations beside an application never fires the caveat and
a repository that genuinely is stored procedures does (`test_substrate.py:457`). YAML and
generic JSON are in neither tier, so an unread `deployment.yaml` produces no report of any kind
(`test_substrate.py:465`) — config is out of scope by construction, and deliberately silently
so. The one config-identifier relation a backend hands us, graphify's `requires_env`, is mapped
to nothing on purpose rather than by omission (`backend_graphify.py:128`).

One clause of the working record is not implemented and must not be read as if it were. It said
that where a project has only migrations and no schema file, the current schema is emitted as
`unresolved`. No code does this, and nothing in today's model could: `unresolved:` is a prefix on
an import *target*, meaning the source named something project-local that resolves to no file
(`substrate.py:65`, `:743`), and a "current schema" is not a file and has no node to hang the
signal on. What actually happens to a migration-only project is the census — its `.sql` files
are graphed as isolated nodes when graphify runs with the extra, and named as unread by the
floor once they dominate. That is the honest answer the clause was reaching for, arrived at by a
different mechanism.

## Rationale

A graph earns its place on transitive closure. Config relationships are one hop and do not
branch: `deployment.yaml → myapp:1.2.3 → Dockerfile → src/` is a chain of three that never
forks, and a chain that never forks is a list. Most projects have a handful of such files. A
traversal engine over them answers questions a `grep` answers, and the artifact, the schema
version, the incremental update path and the staleness rules all have to be paid for anyway.

The stronger reason is that nothing consumes the answer. The graph exists so that docs-manager,
spec-manager and behavior-graph know what to re-check when code changes. Changing `lib/auth.ts`
and learning that it eventually lands in a container image does not change which docs are stale
or which behaviours to re-run — the code graph already answered that question, at the point
where the answer was actionable. Both halves of this record rest on that same test, and neither
had a consumer when it was asked.

**The original justification for dropping the config identifier index was refuted, and must not
be reused.** The index was dropped on the reasoning that graphify "already parses YAML/JSON/HCL
deterministically, so it is probably redundant." The Phase 0 spike ran that premise against a
real fixture and it failed: graphify has no YAML support at all, and — worse than absence —
gives no warning when handed a Kubernetes manifest or a compose file, where the SQL and Terraform
paths both warn clearly if their extra is missing. JSON is manifest-aware only. The same premise
sat in the spec at §7 and §9.4 and is recorded as refuted in that document's own errata table.
The conclusion survives on the two independent reasons above; the argument does not, and anything
else that ever rested on it should be re-derived rather than inherited.

A third reason arrived after the decision and is the most durable of the three: on the formats
graphify *does* parse, the edges do not cross file boundaries, so they cannot become graph
content under the contract. Re-run on 2026-08-21 against the Phase 0 config fixture
(the Phase 0 config fixtures, in git history at `2762d54:docs/polyglot/phases/phase_0/fixtures/config/` — a SQL schema with a foreign key and a view, a
Terraform file with a resolved interpolation, two Kubernetes manifests, a compose file, a
`package.json` and one `.js` file), graphify with its `sql` and `terraform` extras present emits
fifteen nodes and fifteen links. Ten links are `contains`. The other five are real dependency
relations — one foreign-key `references`, two view `reads_from`, one
`aws_cloudfront_distribution.cdn → aws_s3_bucket.assets` interpolation, and one `package.json`
dependency — and all five have the same file at both ends. The contract projects symbol links
onto file pairs and drops anything intra-file (ADR-023, `backend_graphify.py:634`), so the graph
freya writes for that fixture is four file nodes and **zero edges**. "graphify parses it" and "the graph gains something" are different
claims; only the first was ever true here.

Helm is excluded for a reason of its own, which migration-folding then inherits. A chart is a Go
template, not YAML, until it is rendered: `image: {{ .Values.image.tag }}` is not a value until
`helm template` merges `values.yaml`. Support means executing the chart. Folding a migration
directory to derive the current schema is the same shape — you have to run the thing to know the
answer — and writing the reconstruction into the artifact as fact is the confidently-wrong
sibling of the confidently-empty answer ADR-005 exists to prevent. Both get the same reply: emit
what is known and say what is not.

Schemas are the exception because the dependency they carry is a real import chain. A `User`
model becomes a generated client type which `lib/auth.ts` imports, and "I changed the User model,
what touches it?" is exactly the question the graph is for. That chain is answered by graphing
the *importer*, which both backends already do; the schema file's own contribution is the
definition at the far end, which is the least load-bearing link in it. That is why declining to
parse `schema.prisma` costs less than it sounds like — and why it is still worth reporting, since
a schema file is code by this record's own reasoning and a reader should not have to guess that
it was skipped.

## Rejected Alternatives

- **A resource graph over Docker, compose and Kubernetes manifests, with Helm deferred to v2.**
  This was in the design for most of the brainstorm, so it is also the default that applied if
  nobody re-asked: the work was already scoped. It would have made "which image does this code
  ship in" and "which manifest deploys this service" recorded edges rather than a grep, and it is
  the only proposal here that would have put deployment topology in the same artifact as the
  code. It lost on the consumer question, and the spike added a cost nobody had counted: no
  backend has a YAML parser, so building it means writing or vendoring one — per format, in a
  toolkit whose whole substrate contract (ADR-018) exists so that parsing is somebody else's
  problem.

- **Helm chart support.** It would have covered the projects that actually deploy this way, which
  is most of the population a resource graph would serve — a Kubernetes graph that stops at the
  chart boundary is a graph of the generated output, not of what anyone edits. Rejected as the
  highest cost in the feature for the least value: a chart must be rendered before it is data,
  and one hop of non-branching topology is not worth an execution dependency.

- **A config identifier index.** A flat "this name is defined here, used there" table over
  environment variables, image names and service names, answering "I renamed this, what else must
  change?" by lookup rather than traversal. It is the cheapest thing in this record — no
  closure, no schema, no incremental story — and it is the only one attached to a question a
  person genuinely asks. It was invented as the replacement for the resource graph and then
  dropped on the YAML premise above, which was false. It stays dropped on the surviving grounds:
  the question has no *programmatic* caller, so nothing in the toolkit would read the table, and
  we already discard the single identifier relation a backend offers us (`requires_env`,
  `backend_graphify.py:128`) rather than lacking one. This is the alternative in this record
  whose case was never argued at full strength. If it returns it should return on its own merits.

- **Parsing Terraform HCL ourselves.** Terraform is the one genuine branching DAG in the config
  world — unlike the rest of config, a blast radius over it would actually compose — so it is the
  proposal that most nearly beat the transitive-closure test. Rejected because `terraform graph`
  already emits that DAG: consume it if it is ever wanted, never hand-roll HCL. Note that this
  rejects *our* parser and not the data. `.tf` and `.hcl` are tier-1 census material
  (`substrate.py:841`) and graphify parses them behind its `terraform` extra; a future consumer
  should arrive that way.

- **Graph migrations as a chain.** Cheap to the point of free — the order is in the filenames and
  nothing needs parsing — and it would have answered "which migration added this column" from the
  artifact instead of from `git blame`. Rejected on two counts: no consumer asked for it, and it
  would teach every reader that migration order is a dependency relation. Blast radius traverses
  edges, so the first migration in a project would return every migration written since, forever.

- **Fold the migrations to reconstruct the current schema.** The only proposal that would make
  migration-only projects first-class, and it would close the one real gap this record leaves —
  such a project gets no schema node at all today. Rejected because folding means executing, and a
  reconstructed schema recorded as fact is worse than no schema: a wrong answer nobody can tell
  from a right one. The shipped substitute is the census, which says the files exist and were not
  read.

- **Report unread YAML and config JSON the way `.prisma` and `.tf` are reported.** One rule
  instead of a boundary: anything the backend did not read gets named, and "we do not graph your
  Kubernetes manifests" becomes explicit rather than implicit. Rejected because the census is
  only worth having if it is believed, and a field that fires on every repository with a compose
  file is one an agent learns to skip inside a single context window (`substrate.py:814`). "I
  could not read this" and "this is not in scope" are different sentences, and config is the
  second. ADR-029 owns the general form of that rule; the extension lists are where the two
  decisions meet.

## Revisit Conditions

- **A concrete question arrives with a named caller.** "Which chart deploys the service this code
  is in" qualifies the moment it comes with a consumer — docs-manager, spec-manager,
  behavior-graph or the security scan — whose output would change because of the answer. Absent a
  caller, no. This is the trigger both halves of the record turn on, and it is deliberately
  harder to satisfy than "someone would find it interesting".

- **Any backend gains a YAML extractor.** That is the first time "config comes free" becomes
  testable rather than assumed. Re-run the fixture at
  the Phase 0 config fixtures (git history: `2762d54:docs/polyglot/phases/phase_0/fixtures/config/`)
  and look at whether the edges cross file
  boundaries. If they do, the projection keeps them and this record has to say what happens to
  them; if they are intra-file like SQL's and HCL's, nothing changes and the answer is now
  measured rather than argued.

- **Intra-file links become representable.** File-level self-edges are dropped today for want of
  a node type below the file (`backend_graphify.py:641`, ADR-023). If a symbol-level graph lands,
  the SQL foreign keys, view reads and Terraform interpolations graphify already extracts stop
  being discarded, and config starts contributing content without anyone deciding it should.
  Re-derive the zero measured above rather than assuming it still holds.

- **Migration-only projects turn out to be common among adopters.** Then the census is the whole
  answer such a project ever gets, which may be too weak to be useful, and running the migrations
  in a scratch database becomes worth costing against the execution dependency it brings. Count
  them before assuming.

- **A `.prisma` parser appears in any backend.** This is the sharpest place the record is
  currently uncomfortable: `schema.prisma` is code by this document's own reasoning, it is the
  most common schema file in the ecosystem the toolkit came from, and every Prisma project's
  build reports it as a blind spot. A backend that reads it closes that with no decision to
  re-litigate.
