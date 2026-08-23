---
id: ADR-019
title: the floor always ships, and any other backend runs because a person named it
status: accepted
created: 2026-08-21
updated: 2026-08-21
tags:
  - substrate
  - code-graph
  - zero-install
  - installer
---
# ADR-019: the floor always ships, and any other backend runs because a person named it

## Decision

Two backends satisfy the substrate contract (ADR-018): `homegrown`, the stdlib-only resolver
this toolkit already had, and `graphify`, an external tree-sitter tool installed with `uv` or
pip. `homegrown` is the **floor** (`backends.py:26`). It is registered unconditionally
(`backends.py:63`), and it is what every fallback path lands on. Selection refuses outright if
even the floor reports itself unusable rather than picking something else, because a
stdlib-only backend being unavailable means the installation is broken, not that another
backend should be promoted (`backends.py:127`).

`auto` resolves to the floor and nothing else (`backends.py:166`). It does not rank the
installed backends against the repository, and it does not switch on what it finds there.
Running another backend requires its name in a settings file; naming it *is* the opt-in, and
there is no second permission list. A named backend that is not available degrades to the floor
with a reason rather than failing the build — `not installed` when the name is registered but
absent from the machine, `unknown backend` when the name is not a backend at all
(`backends.py:138`) — and a backend that passes selection and then throws mid-build degrades the
same way (`graph_ops.py:2563`). Every one of those fallbacks records `degraded_from` and its
reason in the graph's own metadata, not only on stderr.

The name is answered **once per machine, at install time**. `freya install` and `freya update`
both call the prompt (`bin/backend_setup.py:104`, from `bin/installer.py:988` and
`bin/updater.py:276`); it asks only at a terminal, only when the machine has never answered, and
only when more than one backend is available. The answer goes to `~/.freya/settings.json`,
relocatable with `FREYA_HOME` (`settings.py:64`, `settings.py:194`) — its own directory rather
than any one agent's, because the suite installs for several hosts and the answer is the same on
all of them. The machine file may carry only `substrate.backend` and `substrate.symbols`
(`settings.py:74`); anything else in it is dropped *and reported* (`settings.py:253`).
`freya code-graph --use <name> [--global]` is the same decision made later,
and it validates the name against the registry at the moment somebody is present to be told they
typed it wrong (`graph_ops.py:2964`). At machine scope, `--use auto` is not an answer — it
clears the default, which is the only way to un-answer the install question
(`settings.py:533`).

Precedence is **project, then machine, then floor** (`settings.py:346`). An explicit name in a
project's `knowledge-base/settings.json` — including `homegrown` — wins, and is how one
repository opts out without touching the others; `auto` in a project file means *defer to the
machine*; a project that has said nothing at all follows the machine, and the floor answers when
the machine has not been asked. "Absent" and "explicitly `auto`" are deliberately different
states (`settings.py:360`, `settings.py:370`). The first `--build` or `--update` in a project
that has not decided copies the machine's answer into that project's own committed
`knowledge-base/settings.json` (`graph_ops.py:3122` → `settings.py:586`), validating it against
the registry on the way so a typo in one person's home directory does not become a repository's
permanent setting. A headless run with nothing configured writes nothing: "not yet asked" is a
state the system keeps rather than resolves. The same precedence and the same seeding apply to
`substrate.symbols`, which changes what is *in* the graph; ADR-024 covers why it is off by
default.

## Rationale

The driving case for the whole polyglot effort is a locked-down work laptop. freya is
stdlib-only; graphify needs `uv` or pip and network access. If enterprise policy blocks
installing a Python package, graphify never runs in the one environment this work exists to
serve. Keeping the homegrown resolver is what makes freya degrade to *something* everywhere
instead of to nothing, and it is why the floor is not legacy baggage waiting to be deleted.
The second reason is the contract itself: an interface with a single
implementation is fiction, and homegrown and graphify differ on every axis that matters — regex
against AST, zero-install against a dependency, four languages against forty, file-level against
symbol-level. Measured on this checkout on 2026-08-21, the floor declares 4 languages and 6
extensions and graphify declares 40 and 93.

`auto` does not go shopping because the alternative is a substrate that changes without anyone
deciding. Backend availability is a property of `PATH`, so a ranking rule means that installing
a binary — for any reason, in any project — silently swaps the parser under every repository on
the machine at once. That changes every blast radius, and it reaches further than the graph:
integration behaviours' static fingerprints come from the code-graph closure and land in
`behavior.json`, which is committed (ADR-017). A ranking rule would deliver that as an unexplained
diff. The design document's own risk table already said graphify is opt-in, and a substrate swap
is supposed to be a measured migration — diffed against the previous backend before it is
trusted, which is what ADR-028 keeps both graphs current for. Re-derived on this repository on
2026-08-21 at `2762d54`, a widest-coverage rule would not have been hypothetical: graphify
declares it reads 68 of the 90 in-scope files to the floor's 62, so it would have won here, on a
repository the floor covers well.

**The design said something stronger than what ships, and this record corrects it rather than
repeating it.** The spec and the original decision entry both say the floor "remains the default
where it already covers the project's languages" — that is, that `auto` would hand a Java
repository to graphify. It does not. `auto` is the floor unconditionally, even where the floor
reads nothing at all: re-derived 2026-08-21 on the Maven fixture the toolkit is tested against,
the floor reads 0 of its 8 in-scope files, graphify reads 7, and `auto` still selects the floor.
What stops that from being silent is not selection. It is the discovery hint described next, and
the blind-spot reporting of ADR-029, which is what makes an almost-empty graph say on its face
that it could not read the repository.

Opt-in must not mean undiscoverable, so `auto` still runs the extension census — purely to say
what it is leaving out. When another backend is installed and declares extensions present here
that the floor does not read, the run prints which extensions and how many files, followed by
the two commands that switch (`backends.py:176`). Verified live on this repository on
2026-08-21: `code-graph: 'graphify' is installed and declares it reads 2 file(s) here that
'homegrown' cannot (.ps1, .sh)`, with the `--use graphify` and `--use graphify --global` lines
under it. The hint has a hole: the census is skipped when only one backend is available
(`graph_ops.py:3014`), so it can only ever tell you about a tool you already own. Two other
places close that gap — the install prompt's single-backend branch says what is missing and how
to get it (`bin/backend_setup.py:39`), and the blind-spot report derives its remedy from a
backend's *declared* coverage, deliberately without checking whether it is installed
(`backends.py:207`).

Install is where the question goes because install is where the keyboard is. `code-graph`
auto-enables non-interactive mode whenever stdin is not a TTY (`graph_ops.py:3105`), which is
every agent-driven run and every `wrap-up` run — a mid-workflow prompt fires almost exclusively
for someone typing the command by hand. `freya install` and `freya update` are the two commands
a person runs deliberately, and asking on update is the migration path for anyone installed
before the question existed: no version check, because "has this machine answered?" is the only
state that matters. Everything in that path is best-effort — a preference that cannot be saved
must never turn a completed install into a failure.

The machine answer being *recorded* in each project, rather than merely applying to it, is the
load-bearing half. A default that stayed implicit would mean the same commit graphs differently
on a machine that has one and a machine that does not, and — again through the committed
`behavior.json` — that divergence arrives as a diff that reads like behaviour drift. Writing it
down makes the repository self-describing: a clone and CI resolve the same backend without
sharing anyone's laptop configuration. That is the property the settings file exists for, and it
is why the file lives in `knowledge-base/`, whose name every skill already hardcodes, which
survives a cache clear, and where only the generated files under `.graph/` are gitignored —
`specs/`, `decisions/` and `principles.md` are tracked, so a settings file beside them is
committed by default (`graph_ops.py:244`, ADR-017). The seeding is a seed and not a live link:
once a project has an answer of its own, the project file wins, and changing the machine default
later does not reach back into it — which the `--use --global` output says out loud rather than
promising more than it does (`graph_ops.py:2990`).

Degradation is not cosmetic, and the proof is that another skill acts on it. `degraded_from` in
the artifact means the project asked for a backend and did not get one, so the graph is thinner
than the project declared; the behavior runner refuses to compute a static closure from it and
returns `unknown` with the reason instead of a narrower answer that looks authoritative
(`skills/freya-behavior-runner/scripts/run_behaviors.py:323`). One honest gap remains and this
record states it rather than implying enforcement: nothing verifies that a seeded
`settings.json` is actually committed. The build prints one line asking for it
(`graph_ops.py:2939`) and that is the entire mechanism. A project that ignores the line keeps
the divergence the seeding was designed to remove.

## Rejected Alternatives

- **Score the installed backends and let `auto` pick the widest.** The helpful-sounding option,
  and the one most tools ship: every repository silently gets the best parser present, a Java
  repo on a machine with graphify simply works, and nobody has to be taught a setting exists. It
  was rejected because "which parser produced this graph" would then be a property of `PATH`
  rather than a decision, changing every blast radius on the machine at once with no diff and no
  record — and because the same closure is committed into `behavior.json`, the change would
  surface as behaviour drift rather than as a parser change. The scorer it would have used is
  deleted rather than left dormant, and its place carries a comment saying why
  (`backends.py:106`), because the reasoning that argued `auto` should "see the most of this
  repo" reads as obviously correct until the consequence is spelled out.

- **Replace the homegrown resolver once graphify proved itself.** Genuinely attractive: one code
  path instead of two, forty languages instead of four, symbol-level relations everywhere, and
  no floor to keep working. Rejected on the locked-down laptop, which is the case the initiative
  exists for — where `uv`, pip and the network are all unavailable, this leaves freya with no
  substrate at all rather than a narrow one. It would also make the zero-install property that
  ADR-005 already paid to keep depend on a third-party package's continued existence.

- **Keep homegrown only as a comparison target for the spike, then delete it.** A real position,
  not a straw man: the contract needs a second implementation to be proven, and the migration
  needs a baseline to diff against, but both of those uses expire once the measurement is
  published. Rejected because its value as a *floor* does not expire. It is the landing point
  for a name that is not installed, a name that is not a backend, a backend that fails the
  contract check, a backend that throws mid-build, and selection itself failing — five paths
  that all currently end in "run the stdlib one and say so".

- **A separate `substrate.allow` list, so permitting a backend and choosing it are different
  acts.** It would buy a real separation — an operator could sanction graphify for a repository
  without switching to it yet, and a policy could be expressed independently of a preference.
  Rejected as machinery for an answer already given: a project that has written a backend's name
  into a committed file has decided, and a second list would only create a state where the name
  is present and ignored.

- **Ask which backend to use in the middle of the workflow.** The question would arrive when it
  is relevant, in the project it is about, with the repository right there to justify the answer.
  Rejected because that prompt almost never fires: non-interactive mode auto-enables whenever
  stdin is not a TTY, which is every agent-driven run and every `wrap-up` run. Designing for the
  hand-typed run means designing for the path that rarely executes.

- **Ask through the agent, using the deferred-prompt protocol.** This works headless, which the
  terminal prompt does not: the script emits "I need a decision", the agent asks in chat, the
  answer comes back on the next call. The machinery is even half-built —
  `needs_classification()`, `get_classification_prompt()` and `classify_with_ai_response()` exist
  (`graph_ops.py:1823`) and, verified at `2762d54`, have no caller and no CLI flag anywhere in
  the repository. Rejected on standing cost: the instruction telling the agent what to do would
  live in the skill layer, which is read on *every* invocation to say nothing on almost all of
  them, and this question is asked once per machine. The instruction rides in the output of the
  one run that needs it instead. The protocol is still the right answer for directory
  classification, which is genuinely per project.

- **Let the machine default apply to projects without recording it in them.** Cheaper and less
  intrusive — no writes into somebody's repository as a side effect of a build, and no committed
  file appearing unbidden. Rejected because it reintroduces exactly the divergence the machine
  default creates: two engineers, the same commit, different graphs, and a `behavior.json` diff
  nobody can explain. The objection that a build should not write configuration was answered by
  the file being committed in the first place: recording the answer where it travels is the
  point, not a side effect.

- **Write the floor into `settings.json` when nobody answers.** It would make every project
  self-describing after one build and remove the "not yet asked" state entirely. Rejected
  firmly: a committed file recording a decision no person made is a decision attributed to
  someone who never made it, and this substrate exists to refuse confidently-wrong answers. A
  headless run with nothing configured writes nothing, and the floor works with no configuration
  at all.

- **Put the setting somewhere other than `knowledge-base/settings.json`.** Three candidates, each
  buying something. *`freya.json` at the repository root* is the conventional, discoverable place
  and needs no other directory to exist — rejected because it puts a file in the root of every
  adopting project for a tool that already owns a directory. *Extending
  `knowledge-base/.graph/classifications.json`* adds no new file at all, and that file is where
  the first version of the directory overrides actually went — rejected because it is named in
  the cache's own `.gitignore` (`graph_ops.py:244`), so a setting recorded there works for
  whoever typed it and reaches neither a fresh clone nor CI, leaving every checkout to re-decide.
  *A `"freya"` key in `package.json`* is the Node ecosystem's own convention and costs nothing in
  a Node repo — worth
  supporting later as an optional override, rejected as the home because Java, Python and Go
  repositories have no `package.json`, and keying the polyglot toolkit's configuration to a Node
  manifest is precisely the framework assumption this work exists to remove.

- **Allow `directories` in the machine-level file too, so scope rules could be set once.** It
  would spare anyone who works in similar repositories from repeating the same overrides. Rejected
  because a global "docs is source" would apply to repositories nobody has looked at, and a
  global `node_modules: source` is a 50,000-file graph on every project on the machine. Scope is
  a fact about one project; a parser preference is a fact about the person. The key is dropped
  *and reported* rather than silently ignored, because someone who writes it has a reasonable
  expectation that it does something.

## Revisit Conditions

- **Supporting a second workspace format turns into per-tool special-casing.** The floor reads
  `package.json#workspaces` and resolves cross-package imports itself, because in a monorepo the
  cross-package edge is *the* architectural edge and a floor that collapses on the layout the
  immediate real target uses is not a floor. pnpm and yarn declare membership differently
  (`pnpm-workspace.yaml`, `package.json#workspaces.packages`). One more format is fine; a third
  branch of tool-specific parsing is the signal to stop and let the substrate contract own
  package resolution instead — at which point this belongs to whichever backend can actually
  parse the manifest, not to the floor. (Carried forward from the working record, where it was
  the revisit condition on a decision too small to become a record of its own.)

- **graphify, or a successor, ships as a single self-contained binary with no install step.**
  Then the floor's load-bearing argument collapses to "one less thing to maintain" and replacing
  the homegrown resolver becomes arguable again. Check the install story specifically — the
  language count is not the trigger and never was.

- **A third backend arrives, or one needs to ship out of tree.** `_registry()` is a hardcoded
  dict of two factories (`backends.py:63`) and `FLOOR` is a module constant. Entry-point
  discovery would replace it, and the precedence rules above were written with exactly two names
  in mind — re-read them before assuming they generalise.

- **The opt-in hint starts recommending a switch that buys nothing.** Its evidence is a backend's
  *declaration*, filtered only by the extensions a backend admits are name-based rather than
  language-based (`backends.py:186`). graphify already declares `.sql` and `.tf` but parses them
  only when optional grammar extras are installed. If that class of over-claim grows beyond the
  two extensions the current filter covers, a static tuple stops being enough and the contract
  needs a backend to say what it can parse *here*, not what it supports in principle.

- **People keep discovering the floor's blind spots downstream instead of from the report.**
  `auto` deliberately produces a near-empty graph on a repository the floor cannot read, and
  relies entirely on ADR-029's reporting to keep that honest. If the gap keeps being found
  through a wrong blast radius rather than through the report, the trade is wrong and `auto`
  should refuse rather than produce.

- **`knowledge-base/` has to move.** The project-level setting cannot live inside the thing whose
  location it would configure; if that directory ever becomes relocatable, the setting moves with
  it and the machine-level file has to answer where it went.
