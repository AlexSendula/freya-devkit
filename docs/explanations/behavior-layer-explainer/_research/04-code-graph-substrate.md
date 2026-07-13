# 04 — The code-graph substrate & its capability contract

**Slice:** the foundation layer the whole Behavior Layer stands on.
**One-line:** Before governance can *block a commit* based on "this change affects behavior X", the thing that answers "what does this change affect?" — the code-graph — has to actually be trustworthy. This slice is the story of the capability contract that trust requires, the bugs that proved the old substrate failed it, and the specific fix that shipped.

Primary sources (all read in full):
- `docs/design/behavior-layer/code-graph-substrate-fix.md` (the fix plan)
- `skills/code-graph/scripts/graph_ops.py` (the engine)
- `skills/code-graph/SKILL.md` (the interface/contract doc)
- Supporting: `docs/design/behavior-layer/00-vision.md` §10 & §6; `docs/design/behavior-layer/dogfooding-notes.md` F6–F9; `skills/behavior-graph/scripts/behavior_graph.py`; `skills/spec-manager/scripts/drift.py`.

---

## 1. Why a newcomer should care

The Behavior Layer's promise is: when you change code, the tools tell you which *behaviors* (BEHAVIOR → TEST → CODE) your change might have broken, and — at wrap-up — can hold the commit until you deal with it. That entire promise is a **projection over a code dependency graph**. If the graph is wrong, every governance decision built on it is wrong in the most dangerous way: it can report a *small, confident, empty* blast radius that looks complete but isn't.

The vision states this as a hard precondition (00-vision.md §6):

> "Governance leans on this graph, so it must *report when it cannot resolve* an edge (e.g. a path-aliased or dynamic import it can't follow) rather than return a small blast radius that looks complete. A **capability contract** for the substrate (§10) is a precondition for trusting any block decision built on it."

So the substrate is not a "nice to have." It is the thing that had to be fixed *first*, before Phase 2 (the behavior graph) could be trusted.

---

## 2. The capability contract (vision §10)

The contract is stated in `00-vision.md` §10 ("Deferred / open decisions → Code substrate & its capability contract"). The framing is deliberately **implementation-independent**: it does not matter whether the substrate stays homegrown or gets replaced — *any* substrate must satisfy this before governance depends on it. Verbatim, the substrate must:

> "resolve imports (incl. TypeScript path aliases — the current regex resolver treats non-relative imports as external and silently drops them), stable file identity, language coverage, per-edge confidence, freshness, changed-file impact, and an explicit **"coverage unknown"** signal instead of a falsely-small blast radius."

Breaking that into the contract items:

| Contract requirement | What it means | Status after the fix |
|---|---|---|
| **Resolve imports incl. TS path aliases** | `@/lib/x`-style aliases (from `tsconfig`/`jsconfig` `paths`+`baseUrl`) must resolve to real internal files, not be dumped as external. | ✓ met for TS/JS |
| **Stable file identity** | Files identified by a stable key (project-relative path) regardless of where the tool is run from. | ✓ (already project-relative; F9 fixed cwd leakage) |
| **Per-edge confidence** | A confidence score per dependency edge. | ✗ **NOT shipped** — explicitly out of scope (graphify fallback if needed) |
| **Freshness** | Graph knows the commit it was built at; can update incrementally. | ✓ (git commit stored, `update` via `git diff`) |
| **Changed-file impact** | Given changed files, produce the blast radius (dependents). | ✓ (`--impact`) |
| **Explicit "coverage unknown" signal** | When it *can't* resolve an edge, say so — never silently drop it and imply "no deps". | ✓ met via the `unresolved:` tag |

The fix plan (`code-graph-substrate-fix.md`) restates exactly what it does and does **not** claim:

> "Resolve imports incl. TS path aliases ✓ · stable file identity (already project-relative) ✓ · per-edge classification `internal` / `external` / **`unresolved`** ✓ · explicit "coverage unknown" signal ✓. *Not* in scope: per-edge confidence scoring, multi-language alias systems beyond TS/JS, full TS module-resolution (barrel re-exports, conditional exports), or graphify adoption."

**Takeaway for the newcomer:** the contract is a checklist. The fix satisfied the *governance-blocking* subset (alias resolution + coverage-unknown signal) enough to unblock Phase 2 for TypeScript/JavaScript. Per-edge confidence remains a deliberate gap.

---

## 3. How the old substrate failed — the four dogfooding findings (F6–F9)

The contract stopped being theoretical when the team dogfooded Phase 1 against a real Next.js testbed. Four findings (dogfooding-notes.md) turned §10 from "deferred/open" into **"BLOCKING for Phase 2"**.

Key context: these were **not new bugs introduced by the Behavior Layer work.** A verified git check (`git diff ba8470b..HEAD -- skills/code-graph/scripts/graph_ops.py` = 2 lines, both a path rename) proved the engine is **ORIGINAL** — the impact feature "has been broken for path-alias projects since v0.1.0; dogfooding merely exposed it on the first real alias-using project."

### F6 — `--build` was interactive; could not run unattended
`graph_ops.py --build` prompted on stdin to classify ambiguous directories (`"Uncertain classification for 'app/[lang]/' … Your choice (1 or 2):"`). On a real Next.js `app/` tree this fires for many subdirs and **hangs**, so wrap-up's Phase 1 (`code-graph update`) could not complete as a pipeline subprocess. It even prompted to classify its own generated `knowledge-base/.graph/` output dir.

### F7 — **(critical)** path aliases ⇒ 100% external, internally-empty graph, reported silently
After building the testbed graph, it had **229 files, 1052 import edges — and 0 internal edges; all 1052 tagged `external:`.** Cause: every internal import uses the `@/` alias (Next.js standard; `tsconfig` `paths: {"@/*": ["./*"]}`), and the resolver treated non-relative imports as external and dropped them. Concretely: `--dependencies app/api/auth/passkey/authenticate/route.ts` → `[]` despite three `@/lib/*` imports. The notes call this **"worse than incomplete"**: it returns an empty blast radius *as if complete*, violating "coverage-unknown, never silent" (§6). No "unknown" signal was emitted.

### F8 — generated `knowledge-base/.graph/` was not git-ignored
The renamed cache `knowledge-base/.graph/` (was `.code-graph/`, which *was* ignored) had no gitignore coverage in adopting projects, so it would be committed as an artifact — a regenerable (and currently broken) cache.

### F9 — relative-import resolution was cwd-sensitive (silently drops)
`_resolve_import_path` resolved relative imports via `(from_dir / import_path).resolve()` relative to the **process cwd**, then `relative_to(project_dir)`. When invoked with `--dir X` from a different cwd — exactly how wrap-up and the testbed build run it — every relative import failed `relative_to` and was **dropped entirely** (not even tagged external). Proven with a 3-file fixture: from a foreign cwd, `a.ts`'s `./b` → `[]`; rebuilt with `cwd==projectdir` → `['src/b.ts']`. This *compounded* F7 — the testbed's 0/1052 internal was **both** bugs at once.

**Why these mattered together:** "for any alias-using TS project (the majority), code-graph impact analysis is uniformly empty → spec/docs impact updates and **all of Phase 2's blast radius ride on nothing**."

---

## 4. The fix that shipped

**Route chosen (a real decision, see §6 below):** Route A — patch the homegrown resolver, stdlib-only, no new dependency. TDD discipline: `skills/code-graph/scripts/test_graph_ops.py` written first (failing), implement until green. The fix plan lists **8** test cases (cases 1–7 in the plan; dogfooding-notes records "8 cases, written first" as the final count).

The five defects and their fixes (from the plan's "Defects to fix" table):

1. **F7 — tsconfig/jsconfig `paths`/`baseUrl` awareness.** Load + apply path mappings *before* the external fallback.
2. **F9 — cwd independence.** Anchor resolution to `project_dir`, not cwd.
3. **F6 — non-interactive build.** `--non-interactive` (auto when stdin is not a TTY) with a deterministic default.
4. **§6 — the unresolved signal.** Record unresolvable relative/alias imports as `unresolved:<imp>` (distinct from `external:`), instead of silently dropping.
5. **F8 — self-ignoring cache.** code-graph writes `knowledge-base/.graph/.gitignore` containing `*` on build.

### 4a. Alias resolution (F7) — the JSONC gotcha
On build, code-graph looks for `tsconfig.json` then `jsconfig.json` at `project_dir`, reads `compilerOptions.baseUrl` (default `.`) and `compilerOptions.paths`, and builds an alias table. Resolution is longest-prefix match on the literal part before `*`, substituting the captured tail into each target (relative to `baseUrl`), returning the first target that resolves to a real file.

The subtle part: tsconfig is **JSONC** (comments + trailing commas allowed), so it must be pre-processed to valid JSON. A **naive regex stripper is a trap** — it mis-reads the `/*` inside the `@/*` alias and the `*/` inside a `**/*.ts` glob as comment markers. The shipped `_strip_jsonc` is deliberately **string-aware**: comment markers inside string literals are preserved. From the code's own docstring:

> "String-aware: comment markers inside string literals are preserved, so values like the `@/*` alias or a `**/*.ts` glob (which contain `/*` and `*/`) are not mistaken for comments."

A TDD regression test caught this before shipping.

`extends` chains are **not** followed (out of scope — one config only).

### 4b. cwd independence (F9)
In `_resolve_import_path`, relative/absolute imports now compute `from_dir = (self.project_dir / from_file).parent` (absolute, anchored to the project) instead of `Path(from_file).parent`. All candidate resolution + `relative_to(project_dir)` then works regardless of cwd.

### 4c. non-interactive classification (F6)
`--non-interactive` added; also `not sys.stdin.isatty()` is treated as non-interactive (so wrap-up's subprocess invocation auto-triggers it). In that mode, uncertain directories take a deterministic default of **include as source** — "err toward completeness, never silently drop real source." The choice is recorded (`source: "auto-source-default"`) so it's auditable. Known generated/vendor dirs (`node_modules`, `.next`, `.git`, `knowledge-base`, `.graph`, …) are always auto-excluded without prompting.

### 4d. The unresolved signal (§6) — the heart of the contract
This is the item that makes the substrate *honest*. `_classify_import` tags each edge one of three ways:
- an **internal** project-relative path (resolved),
- `external:<pkg>` — a genuine third-party bare package,
- `unresolved:<imp>` — a **relative or alias-matched** import that *should* have resolved but didn't.

From the code docstring: `unresolved:` "makes a failed relative/alias resolution visible instead of silently dropping it (vision §6, 'coverage-unknown, never silent')." This is what lets a caller distinguish **"no dependencies"** from **"couldn't resolve some dependencies."**

### 4e. Self-ignoring cache (F8)
`_ensure_graph_dir` writes `knowledge-base/.graph/.gitignore` with contents `# Generated code-graph cache — do not commit\n*\n`. Self-contained — adopting projects never touch their root `.gitignore`.

### The measured result
On the testbed, the rebuild went from **0 internal / 1052 external** to **607 internal / 488 external / 0 unresolved**. The authenticate route now resolves its real deps: `lib/webauthn.ts`, `lib/rate-limit.ts`, `lib/audit.ts`, `lib/prisma.ts`. Verdict recorded: "**§10 capability-contract (alias resolution + coverage-unknown signal) now met for TS/JS — Phase 2 unblocked.**"

---

## 5. The interface governance depends on: `--impact ... --format json`

Everything above exists to serve one query: *given a set of changed files, what is the blast radius?* That is the `--impact` command.

**CLI (from `graph_ops.py` argparse and SKILL.md):**
```bash
python graph_ops.py --impact <file...> --dir <project> --format json
```
- `--impact` takes `nargs='+'` (one or more files).
- `--dir` sets the project directory (independent of cwd — this is what F9 made safe).
- `--format json` (the default) emits machine-readable JSON; `--format summary` is the human view.

**`get_impact(file_paths)` output shape** (the JSON keys downstream consumers read):
```
{
  "input_files":           [...],   # the files you passed in
  "direct_dependents":     [...],   # files that import an input file directly
  "transitive_dependents": [...],   # dependents-of-dependents (all_affected minus inputs minus direct)
  "all_affected":          [...]    # the full blast radius: inputs + direct + transitive dependents
}
```
`all_affected` is the load-bearing key: it is **inputs ∪ transitive-dependents-closure**. The algorithm (SKILL.md): `impact(file) = file + direct_dependents(file) + transitive_dependents(file)`, traversing the reverse (`dependents`) mapping recursively.

Note on freshness/identity supporting this: the graph stores `commit`, `timestamp`, `project_root`, and a `files` map keyed by project-relative path, each entry carrying `exports`, `imports` (the tagged edges), `dependents`, `category`, `language`. `dependents` is the reverse of `imports`, and edges tagged `external:`/`unresolved:` are excluded from the reverse mapping and from transitive dependency traversal.

---

## 6. Two consumers that reuse this exact blast radius

The substrate fix pays off because **two different governance features call the same `--impact ... --format json` and read `all_affected`.** Neither reimplements graph traversal.

### 6a. The behavior graph (Direction A) — `behavior_graph.py`
The behavior-graph skill is a "pure graph layer" over code-graph + behavior-runner; code-graph stays unaware of behaviors (vision §5b). Its `_code_graph_impact(changed_files, project_dir)` shells out:
```python
[sys.executable, str(_CODE_GRAPH), "--impact", *changed_files,
 "--dir", project_dir, "--format", "json"]
```
then unions `data.get(key, [])` over `("input_files", "direct_dependents", "transitive_dependents")`. **Direction A** ("code change → affected behaviors") is then just a set intersection: `direction_a` calls `_affected_from_impact`, which returns the BEH ids whose *exercised* code paths (`entry["exercises"][*]["path"]`) intersect that impact set. So the honesty of the blast radius directly determines which behaviors get flagged.

### 6b. The declarative-drift check (governance P4b) — `drift.py`
Declarative intent (e.g. an ADR or a spec's `intentional_decisions`) has **no test to fail**, so it is guarded at wrap-up by a Tier-2 check that runs "**only for the declarative specs whose `related_code` intersects the change's blast radius**" (vision §7). Crucially, per the vision, "This relies on the *existing* code-level blast radius from code-graph, not the behavior graph." Its `compute_impact(project, base)` runs the same command:
```python
[sys.executable, _GRAPH_OPS, "--impact", *changed,
 "--dir", project, "--format", "json"]
```
and here the coverage-unknown discipline is explicit in the return value:
> "`code-graph` means the graph actually ran (the `all_affected` key is present, even if it lists no dependents). A missing graph — where graph_ops emits `{}` with no `all_affected` key — degrades to `changed-only` so the operator sees the blast radius is narrower (direct files only), not falsely complete."

So `compute_impact` returns `(set(data["all_affected"]) | set(changed), "code-graph")` when the graph ran, and `(set(changed), "changed-only")` when it couldn't — **never a silent empty set.** That "source" label (`code-graph` vs `changed-only` vs `empty`) is the operator-facing honesty signal, and it exists *because* the substrate contract demanded "coverage unknown, never falsely-small." Then `_spec_targets`/`_adr_targets` keep only items whose `related_code` has a path `in impact`.

**The through-line:** one fix to `all_affected` + the `unresolved`/`changed-only` honesty signals makes *both* the behavior-drift guard and the declarative-drift guard trustworthy. That is the payoff of fixing the substrate before building governance on it.

---

## 7. The deferred graphify-vs-homegrown decision

§10 leaves **open** whether to keep the homegrown regex-based code-graph or adopt [graphify](https://github.com/safishamsi/graphify), described in the vision as "symbol-level, multi-language, tree-sitter, confidence-scored — philosophically aligned," or to borrow its ideas.

The substrate fix did **not** resolve that decision — it deliberately took **"Route A — patch the homegrown resolver (stdlib-only, no new dependency). Graphify (§10) stays the fallback if the regex parser keeps accruing edge cases."** The fix plan explicitly lists graphify adoption as *out of scope*.

Why this ordering is smart for a newcomer to understand: the behavior graph is kept in a **sibling** file `behavior.json`, *not* a schema bump to `graph.json` — "deliberate: it lets the code-substrate decision (§10) stay decoupled." So a future swap to graphify does not touch the behavior-layer schema. The homegrown resolver was patched *just enough* to meet the governance-blocking subset of the contract; graphify remains the escape hatch specifically for the capabilities left unshipped (per-edge confidence, multi-language aliases, full TS module resolution like barrel/re-export edges).

---

## 8. Honest limits (still true after the fix)

- **Per-edge confidence: not implemented.** A contract item that remains a gap.
- **Alias systems: TS/JS only.** No multi-language alias resolution.
- **`extends` chains in tsconfig: not followed.** One config only.
- **Barrel re-exports / conditional exports: not resolved.** Full TS module resolution is out of scope.
- **Dynamic imports** (`import(variable)`, `require(variable)`) may not be caught (SKILL.md limitations).
- **Monorepos:** each subproject should have its own graph.

---

## 9. Glossary for explainer copy

- **Substrate** — the code-graph layer everything else projects onto.
- **Blast radius / impact** — the set of files affected by a change: `all_affected` = inputs + direct + transitive dependents.
- **Capability contract** — the §10 checklist a substrate must satisfy before governance trusts it.
- **`unresolved:` / coverage-unknown** — an edge the graph knows it *should* resolve but couldn't; surfaced, never dropped. Distinguishes "no deps" from "couldn't resolve."
- **`external:`** — a genuine third-party package edge (intentionally not internal).
- **Direction A** — behavior-graph query: code change → affected behaviors (a set intersection over the blast radius).
- **Declarative-drift check (P4b)** — wrap-up guard for untestable intent, scoped to `related_code ∩ blast-radius`.
