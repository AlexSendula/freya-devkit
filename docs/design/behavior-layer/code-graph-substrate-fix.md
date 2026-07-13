# Code-Graph Substrate Fix — Plan

**Status:** Ready to implement
**Date:** 2026-06-29
**Driver:** Dogfooding findings F6–F9 (`dogfooding-notes.md`). The code-graph blast radius is empty/silent on real path-alias projects, which **blocks Phase 2** (impact indexing rides on it). This is vision §10's "capability contract," now forced.
**Route:** A — patch the homegrown resolver (stdlib-only, no new dependency). Graphify (§10) stays the fallback if the regex parser keeps accruing edge cases.
**Discipline:** TDD. `skills/code-graph/scripts/test_graph_ops.py` is new; write failing cases first, implement until green.

---

## Defects to fix

| # | Finding | Defect | Fix |
|---|---------|--------|-----|
| 1 | F7 | No `tsconfig`/`jsconfig` `paths`/`baseUrl` awareness → `@/…` aliases dropped as `external` | Load + apply path mappings before the external fallback |
| 2 | F9 | Relative resolution uses process **cwd** (`Path(from_file).resolve()`) → drops relatives when run with `--dir` from elsewhere | Anchor resolution to `project_dir`, not cwd |
| 3 | F6 | `--build` blocks on interactive stdin dir-classification; can't run in wrap-up | `--non-interactive` (auto when stdin not a TTY) with a deterministic default |
| 4 | §6 | Unresolvable relative/alias imports are silently dropped (look like "no deps") | Record them as `unresolved:<imp>` (distinct from `external:`) |
| 5 | F8 | Generated `knowledge-base/.graph/` not git-ignored | code-graph writes a self-ignoring `.graph/.gitignore` (`*`) on build |

## Capability-contract targets (vision §10) this satisfies

Resolve imports incl. TS path aliases ✓ · stable file identity (already project-relative) ✓ · per-edge classification `internal` / `external` / **`unresolved`** ✓ · explicit "coverage unknown" signal ✓. *Not* in scope: per-edge confidence scoring, multi-language alias systems beyond TS/JS, full TS module-resolution (barrel re-exports, conditional exports), or graphify adoption.

## Design

### Fix 1 — tsconfig/jsconfig paths
- On build, look for `tsconfig.json` then `jsconfig.json` at `project_dir`. Tolerant parse (strip `//` and `/* */` comments + trailing commas → `json.loads`; tsconfig is JSONC).
- Read `compilerOptions.baseUrl` (default `.`) and `compilerOptions.paths`. Follow one level of `extends` best-effort (merge parent `paths`/`baseUrl`).
- Build an alias table: pattern `@/*` → targets `["./*"]`. Resolution: longest-prefix match on the literal part before `*`; substitute the captured tail into each target (relative to `baseUrl`); return the first target that resolves to a real file (reusing the existing suffix/index candidate list).
- A bare specifier that matches **no** alias and isn't relative stays `external`.

### Fix 2 — cwd independence
- In `_resolve_import_path`, compute `from_dir = (self.project_dir / from_file).parent` (absolute, anchored to the project) instead of `Path(from_file).parent`. All candidate resolution and `relative_to(project_dir)` then work regardless of cwd. Verify `from_file` is passed project-relative at every call site.

### Fix 3 — non-interactive classification
- Add `--non-interactive`; also treat `not sys.stdin.isatty()` as non-interactive. In that mode, uncertain directories take a deterministic default of **include as source** (err toward completeness, never silently drop real source), and the set of auto-classified dirs is reported in the build summary. Always auto-exclude known generated/vendor dirs (`node_modules`, `.next`, `.git`, `knowledge-base`, `.graph`, …) without prompting.

### Fix 4 — unresolved signal
- Split the current "return None → maybe `external:`" path: a **relative** import or an **alias-matched** import that fails to resolve to a file is recorded as `unresolved:<imp>` (kept in the file's import list, distinct prefix). A genuine bare package remains `external:<imp>`. `--impact`/`--dependencies` count `unresolved:` toward a `coverage_unknown` indicator in their output so callers can tell "no deps" from "couldn't resolve."

### Fix 5 — self-ignoring graph cache
- When `_ensure_graph_dir`/build writes `knowledge-base/.graph/`, also write `knowledge-base/.graph/.gitignore` containing `*` (and `!.gitignore` is unnecessary — the whole cache is regenerable). Self-contained; no edit to the project root `.gitignore`.

## Test plan (write first, TDD)

`skills/code-graph/scripts/test_graph_ops.py` (stdlib `unittest`, throwaway temp-dir fixtures):
1. **alias_resolves_internal** — tsconfig `@/*`→`./*`; `c.ts` importing `@/src/b` ⇒ dependency `src/b.ts` (internal), not `external:`.
2. **relative_resolves_regardless_of_cwd** — build with cwd ≠ project_dir; `a.ts`'s `./b` ⇒ `src/b.ts`. (Reproduces F9.)
3. **unresolved_relative_marked** — `./missing` ⇒ recorded `unresolved:./missing`, not dropped; surfaced in dependencies/impact as coverage-unknown.
4. **external_package_still_external** — `react` ⇒ `external:react`.
5. **jsconfig_paths** — same as (1) but `jsconfig.json`, JSONC with a comment + trailing comma (exercises the tolerant parser).
6. **non_interactive_build_completes** — build with closed/non-TTY stdin on a project with ambiguous dirs returns without reading stdin.
7. **graph_dir_self_ignored** — after build, `knowledge-base/.graph/.gitignore` exists and contains `*`.

## Steps

1. **S1** — add `test_graph_ops.py` with cases 1–7 (failing). Establish the baseline (some already fail, e.g. 1/2/3).
2. **S2** — Fix 2 (cwd) — smallest, unblocks case 2 and de-risks the rest.
3. **S3** — Fix 1 (tsconfig/jsconfig paths) + Fix 4 (unresolved signal) — the core; cases 1, 3, 4, 5.
4. **S4** — Fix 3 (non-interactive) — case 6; wire `--non-interactive` and TTY detection.
5. **S5** — Fix 5 (self-ignoring cache) — case 7.
6. **S6** — re-run on the testbed: rebuild and confirm the authenticate route now shows internal deps (`@/lib/webauthn` etc.) and the all-external count collapses. Update `dogfooding-notes.md` (close F6–F9).

## Verification
`python skills/code-graph/scripts/test_graph_ops.py` green; then on the testbed `--build --non-interactive` + `--dependencies app/api/auth/passkey/authenticate/route.ts` returns the three `@/lib/*` modules as internal. SKILL.md updated if flags/CLI change.

## Out of scope
Graphify adoption (§10 fallback); barrel/re-export edge resolution; per-edge confidence; the behavior graph (`behavior.json`) itself (Phase 2 proper).
