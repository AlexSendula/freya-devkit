# Research Brief — Skill: `code-graph`

> Sourced backing layer for the freya-devkit plugin explainer.
> Topic: the foundation skill — dependency graph, impact analysis, blast radius, `graph.json`, subcommands, languages/resolution, degradation.

## Sources read

- `skills/code-graph/SKILL.md` — skill definition, subcommand catalog, integration notes, limitations.
- `skills/code-graph/references/graph-schema.md` — full JSON schema for `graph.json`, field descriptions, path-resolution rules, reference impl of impact/dependency traversal.
- `skills/code-graph/scripts/graph_ops.py` — the actual implementation (single-file Python, stdlib only).
- `skills/code-graph/scripts/test_graph_ops.py` — unit tests confirming alias resolution, cwd-independence, unresolved-marking, non-interactive defaulting, self-ignoring cache.

---

## 1. What it is

`code-graph` is the **foundation skill** of freya-devkit: a lightweight code dependency graph that tracks import/export relationships across a codebase and answers "what depends on this?" (blast radius) and "what does this depend on?". It is deliberately small — one stdlib-only Python script (`graph_ops.py`) plus a thin SKILL.md wrapper — with no third-party parser or LSP dependency.

From SKILL.md:
> "A lightweight dependency graph skill that tracks import/export relationships in your codebase. Other skills use this for impact-aware scanning and incremental updates."

It is invoked namespaced as `/freya-devkit:code-graph <subcommand>`.

## 2. Why it exists

Its purpose is to be the shared **impact-analysis substrate** for the higher-tier skills. `docs-manager` and `spec-manager` call it to decide *which* docs/specs a code change actually affects (not just the literally-changed files, but their dependents). SKILL.md frontmatter states plainly:
> "Used by: docs-manager, spec-manager for incremental updates."

The tier diagram (from the repo's CLAUDE.md ecosystem description) puts it at the bottom: `code-graph` → `docs-manager`/`spec-manager` → `codebase-security-scan` → `wrap-up`. It also underpins the newer behavior layer (`behavior-graph` is described as a "Pure graph layer over code-graph + behavior-runner").

The core value proposition: when a file changes, a naive git diff only knows the changed file. Impact analysis walks the reverse-dependency edges so consumers can update everything transitively affected.

## 3. Storage / artifacts

The graph and directory classifications live **inside the target project** (not in the plugin), under:

```
knowledge-base/.graph/
├── graph.json            # Dependency graph
├── classifications.json  # Directory classifications (source/exclude)
└── .gitignore            # auto-written, contents: "*"  (self-ignoring cache)
```

- Constructed in code as `self.graph_dir = self.project_dir / 'knowledge-base' / '.graph'` (`graph_ops.py`).
- `_ensure_graph_dir()` writes a self-ignoring `.gitignore` containing `# Generated code-graph cache — do not commit\n*\n` if one doesn't already exist. Docstring: *"The cache is fully regenerable, so it ignores its own contents — adopting projects never need to touch their root `.gitignore`."* Confirmed by test `test_graph_dir_self_ignored`.

> IMPORTANT DISCREPANCY (flag in explainer): SKILL.md and `graph-schema.md` both say the graph is stored in `knowledge-base/` "so it stays version-controlled and in sync with branch changes," and only *optionally* gitignored. But the implementation **auto-writes a `.gitignore` that ignores everything (`*`)** in the cache dir, so by default the graph is **not** committed. The prose (version-controlled by default) and the code (ignored by default) disagree. Treat the code as ground truth: cache is regenerable and git-ignored.

### `graph.json` shape

```json
{
  "version": 1,
  "commit": "abc123def456",
  "timestamp": "2024-01-15T10:30:00Z",
  "project_root": "/absolute/path/to/project",
  "files": {
    "src/lib/auth/validateToken.ts": {
      "exports": ["validateToken", "TokenPayload"],
      "imports": ["external:jsonwebtoken", "src/lib/auth/config.ts"],
      "dependents": ["src/api/middleware/auth.ts", "src/api/routes/users.ts"],
      "category": "auth",
      "language": "typescript"
    }
  }
}
```

- Top-level required fields: `version` (const `1`), `timestamp`, `project_root`, `files`. `commit` is optional (12-char short hash from `git rev-parse HEAD`, or `null` outside a git repo).
- `FileInfo` required fields: `imports`, `dependents`. Optional: `exports`, `category`, `language`.
- `category` enum: `auth`, `api`, `data`, `ui`, `infra`, `util`, `config`, `test`, `unknown` — inferred purely from path globs (`CATEGORY_PATTERNS`).
- `language` enum: `typescript`, `javascript`, `python`, `go` — from file extension.

### `classifications.json` shape

Records how each top-level directory was classified as `source` vs `exclude`, with `confidence` (0.0–1.0) and `source` provenance (`rule` | `ai` | `user` | `gitignore` | `default` | `no_ai` | `auto-source-default` | `error`). Also stores detected `project_context` (framework/language/package_manager/config_files).

## 4. How it works — the build pipeline

`build()` in `graph_ops.py`, per SKILL.md "Process":

1. **Classify directories** (hybrid: rules → AI → user confirmation). See §5.
2. Scan the classified `source` directories (top-level only for scanning, `'/' not in d`) plus root-level source files.
3. Detect language by extension; parse imports + exports via regex (`IMPORT_PATTERNS`, `EXPORT_PATTERNS`).
4. Resolve + tag each import (internal path / `external:` / `unresolved:`). See §6.
5. **Build reverse mapping** (`dependents`): for every internal import edge `A → B`, append `A` to `B.dependents`.
6. Write `graph.json` (and `classifications.json`) into `knowledge-base/.graph/`.

`update()` — incremental:
1. Load cached graph; if none or no stored `commit`, fall back to a full `build()`.
2. `git diff <last-commit>..HEAD --name-only` to get changed files.
3. If no changes → `{status: 'up_to_date', files_changed: 0}`.
4. Re-parse changed source files; delete entries for files that no longer exist.
5. **Rebuild all `dependents` from scratch** (clears every file's `dependents`, then re-derives — not a surgical patch).
6. Update `commit` + `timestamp`, save.

### File patterns scanned
`**/*.ts`, `**/*.tsx`, `**/*.js`, `**/*.jsx`, `**/*.py`, `**/*.go` (`FILE_PATTERNS`).

### Always-excluded (build artifacts / vendored / non-source)
Directories (matched anywhere in path): `node_modules`, `vendor`, `__pycache__`, `venv`, `.venv`, `env`, `.git`, `.svn`, `.hg`, `dist`, `build`, `out`, `.output`, `target`, `.next`, `.nuxt`, `.astro`, `.svelte-kit`, `.remix`, `.vuepress`, `.docusaurus`, `.cache`, `.parcel-cache`, `.vite`, `.turbo`, `coverage`, `.nyc_output`, `htmlcov`, `.idea`, `.vscode`, `.sublime-project`, `__MACOSX`, `generated`, `.generated`, `autogen`, `_site`, and notably `.github`, `.gitlab`, `scripts`, `docs`, `knowledge-base`, `examples`.
File patterns: `*.d.ts`, `*.min.js`, `*.min.css`, `*.bundle.js`, `*.chunk.js`, `*.map`, `*.lock`, `*.log`.
Plus every non-negated, non-comment pattern parsed from the project's `.gitignore`.

## 5. Directory classification (hybrid: rules → AI → user)

Because "which directories are source?" varies per project, build classifies each top-level dir:

1. **Rules first.** Known source names (`src`, `lib`, `app`, `apps`, `packages`, `components`, `pages`, `hooks`, `utils`, `services`, `cmd`, `pkg`, `internal`, `server`, `client`, `config`, etc.) → `source` at confidence 1.0. Known excludes → `exclude` at 1.0. Gitignore-matched → `exclude` at 0.9.
2. **AI classification** for anything still unknown. The Python `_classify_with_ai()` is a **stub in CLI mode** — it returns `{type: 'exclude', confidence: 0.5, source: 'no_ai'}` for every unknown dir. Real AI classification happens only when the *skill* (which has model access) pre-fetches a response and passes it in via `classify_with_ai_response()` / the `ai_response` param. The public methods `needs_classification()`, `get_unclassified_directories()`, `get_classification_prompt()`, `classify_with_ai_response()`, `set_classification()` exist specifically for the skill to drive this loop.
3. **User confirmation** for confidence `< 0.8`, via an interactive `[1] Source / [2] Exclude` prompt.

**Non-interactive mode** (`--non-interactive`, *auto-enabled when stdin is not a TTY*, e.g. under `wrap-up`): never prompts; uncertain dirs default to **source**. Rationale in code: *"err toward completeness — never silently drop real source"* (labeled F6). Recorded with `source: 'auto-source-default'` so the choice is auditable. Confirmed by test `test_ambiguous_dir_included_without_stdin`.

> Note the asymmetry: in **interactive** CLI mode with the stub AI, unknown dirs come back at 0.5 confidence and the user is prompted; on `EOFError` the prompt handler defaults to **exclude**. In **non-interactive** mode the same 0.5-confidence dirs default to **source**. So the "never drop source" guarantee holds for automated/wrap-up runs specifically.

## 6. Import resolution & language support

Resolution is regex + filesystem probing, not a real parser.

- **Relative/absolute imports** (`./x`, `../y`, `/z`): anchored to `project_dir`, **independent of current working directory** (labeled F9; test `test_relative_import_resolves_from_foreign_cwd`). Resolved by `_resolve_fs()`, which probes suffixes `.ts/.tsx/.js/.jsx/.py` and index files `index.ts/tsx/js/jsx`, `__init__.py`.
- **Path aliases** (`@/lib/x` etc.): resolved via `tsconfig.json` / `jsconfig.json` `compilerOptions.paths` + `baseUrl` (labeled F7). Includes a **string-aware JSONC stripper** (`_strip_jsonc`) so comments/trailing commas in tsconfig don't break parsing, while `@/*` aliases and `**/*.ts` globs inside strings are preserved. Only **one** config is read; `extends` is intentionally **not** followed. Tests: `test_tsconfig_alias_resolves_internal`, `test_alias_resolves_with_glob_include`, `test_jsconfig_jsonc_alias_resolves_internal`.
- **Edge tagging** — every import becomes one of three kinds:
  - internal → a project-relative path (real wiring),
  - `external:<pkg>` → third-party package,
  - `unresolved:<import>` → a relative/alias import that *looked* internal but couldn't be mapped to a real file (surfaced, not silently dropped).

From `graph-schema.md`:
> "an entry in `imports` is **internal** (real project wiring) only when it carries neither the `external:` nor the `unresolved:` prefix — this is the predicate consumers use to count internal edges (e.g. `spec-manager bootstrap`'s shape detector)."

Tests `test_unresolved_relative_is_marked_not_dropped` and `test_external_package_still_external` lock this in.

### Language patterns (regex, `IMPORT_PATTERNS` / `EXPORT_PATTERNS`)
- **TypeScript/JS**: `import { x } from './y'`, `import x from './y'`, `import * as x from './y'`, `export * from './y'`, `require('./y')`, and dynamic `import('./y')`. Exports: `export function/const/class/interface/type/enum`, `export { ... }`, plus JS `module.exports = {...}` / `exports.x =`.
- **Python**: `from x import y`, `^import x`, `from . import x`. Exports tracked only via `__all__`.
- **Go**: `import "module/path"`, `import alias "module/path"`, and a catch-all quoted-string pattern for multi-line `import ( ... )` blocks. Exports = capitalized `func`/`type`/`var`/`const`.

> Cross-language resolution caveat (see gotchas): only imports starting with `.` / `/`, or matching a tsconfig alias, get filesystem-resolved. **Go module paths and absolute Python package imports don't start with `.` and match no alias → they fall through to `external:`.** So the internal-edge graph is realistically strong for TS/JS relative + aliased imports; Go/Python intra-project resolution is weak.

## 7. Impact analysis / traversal algorithms

Blast radius = the input file plus all transitive **dependents**:
```
impact(file) = file + direct_dependents(file) + transitive_dependents(file)
```
`get_impact()` returns a dict with `input_files`, `direct_dependents` (immediate), `transitive_dependents` (all-affected minus inputs minus direct), and `all_affected`. Accepts multiple files (combined blast radius).

`get_dependents()` / `get_dependencies()` do DFS with a visited-set (cycle-safe). Dependencies traversal skips edges prefixed `external:` **and** `unresolved:` (so only real internal files are followed).

## 8. Subcommands & exact CLI

Skill-level commands (SKILL.md "Quick Reference"):

| Command | Description |
|---------|-------------|
| `build` | Full scan, build dependency graph from codebase |
| `update` | Incremental update via git diff (only changed files) |
| `query <file>` | Show dependencies + usages for a file |
| `impact <file>` | Show blast radius if this file changes |
| `dependents <file>` | All files that depend on this one |
| `dependencies <file>` | All files this one depends on |
| `clear` | Delete cached graph |
| `help` | Display help/usage |

`impact` accepts multiple files: `/freya-devkit:code-graph impact <file1> <file2> ...`.
`help` also responds to `--help` / `-h`.

### Underlying script invocation (verbatim from SKILL.md)
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --build --dir /path/to/project
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --update --dir /path/to/project
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --query src/lib/auth.ts
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --impact src/lib/auth.ts
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --dependents src/lib/auth.ts
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --dependencies src/lib/auth.ts
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --clear --dir /path/to/project
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --query src/lib/auth.ts --format json
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --query src/lib/auth.ts --format summary
```

### Flags (verbatim from `argparse` in `graph_ops.py`)
Mutually-exclusive, one required: `--build`, `--update`, `--query FILE`, `--impact FILE [FILE ...]` (`nargs='+'`), `--dependents FILE`, `--dependencies FILE`, `--clear`.
Additional: `--dir PATH` (project directory; defaults to `os.getcwd()`), `--format {json,summary}` (default `json`), `--non-interactive` (never prompt; default uncertain dirs to source — also auto-enabled when stdin is not a TTY).

Note the CLI uses `--query`/`--impact`/etc. (double-dash flags); the skill-facing form is bare subcommands (`query`, `impact`). Docstring examples also show `--commit HEAD~1` but **there is no `--commit` argparse argument** — that appears to be stale/aspirational (see gotchas).

## 9. Composition with other skills

- **docs-manager `update`**: checks if code-graph exists → if so calls `impact <changed-files>` to decide which docs need refreshing → falls back to plain git diff if unavailable.
- **spec-manager `update`**: same pattern — uses `impact` to pull dependent files into the affected-code set, not just directly-changed files; falls back to git diff otherwise.
- **spec-manager bootstrap** consumes the internal-edge predicate (imports without `external:`/`unresolved:` prefixes) as a project "shape detector."
- **wrap-up** runs `code-graph update` as its first step, in non-interactive mode (no TTY).
- **behavior-graph / behavior layer** builds on code-graph as the pure graph layer beneath behavior→test→code projection.

The consistent contract: consumers **degrade gracefully** if code-graph is absent, falling back to a simple git diff.

## 10. Degradation behavior

- **No graph cached** on `query`/`impact`/`dependents`/`dependencies` → prints "No cached graph found…" and returns empty/None (no crash).
- **`update` with no cache or no stored commit** → auto-falls-back to a full `build()`.
- **Not a git repo** → `commit` is `null`; `update` can't diff so it full-builds.
- **File read errors** → `_build_file_info` returns `{imports: [], dependents: [], exports: []}` (uses `errors='ignore'` on read).
- **AI unavailable (raw CLI)** → classification stub returns defaults; non-interactive runs err toward `source` so real code isn't dropped.
- **Malformed tsconfig** → JSONC strip + `try/except` around `json.loads`; on failure aliases are simply empty (imports become external/unresolved rather than crashing).
- **Consumer skills** fall back to git diff when code-graph isn't installed.

## 11. Honest limits

From SKILL.md "Limitations" plus code reading:
- **Dynamic imports**: may not catch `import(variable)` or `require(variable)` — only string-literal specifiers are matched. (Static `import('./y')` *is* matched.)
- **External packages**: only local file relationships are tracked as edges; npm/pip/go packages are recorded as `external:` leaves, not traversed.
- **Language support**: TypeScript/JS, Python, Go only. No Rust/Java/Ruby/etc. (Rust is *detected* for project context but has no file/import patterns.)
- **Monorepos**: "Each subproject should have its own graph" — scanning is top-level-dir oriented and one config file only.
- **Regex, not AST**: comments, strings, and unusual formatting can produce false import/export matches; Python/Go intra-project resolution is weak (see §6).
- **`extends` in tsconfig/jsconfig is not followed** (single config only).
- **Directory scan for classification is shallow** (`_get_all_directories(max_depth=2)`), and only **top-level** source dirs are actually scanned for files.

## 12. Verbatim quotable lines

- (SKILL.md) "A lightweight dependency graph skill that tracks import/export relationships in your codebase. Other skills use this for impact-aware scanning and incremental updates."
- (SKILL.md) "Used by: docs-manager, spec-manager for incremental updates."
- (SKILL.md) "impact(file) = file + direct_dependents(file) + transitive_dependents(file)"
- (SKILL.md) "never prompts; uncertain directories default to **source** so real code is never silently dropped."
- (graph-schema.md) "A relative/aliased import that the resolver could not map to a real file is stored with an `unresolved:` prefix (rather than silently dropped)."
- (graph_ops.py) "# Generated code-graph cache — do not commit\n*\n" — the auto-written cache `.gitignore`.
- (graph_ops.py) "err toward completeness — never silently drop real source" (F6, non-interactive default-to-source rationale).

---

### Cross-file discrepancies to surface in the explainer
1. **Version control of the graph**: prose says version-controlled/optional-ignore; code auto-ignores the whole cache dir. Code wins → cache is regenerable and git-ignored by default.
2. **`--commit` flag**: shown in the script docstring but not implemented in argparse.
3. **AI classification**: SKILL.md presents rules→AI→user as one flow; in reality the AI step only works when the *skill* injects a model response — raw CLI degrades to defaults.
