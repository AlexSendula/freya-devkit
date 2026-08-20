---
name: freya-code-graph
description: |
  Build and query code dependency graphs for impact analysis and blast radius tracking.
  Use this skill when you need to:
  - Understand code relationships and dependencies
  - Analyze what files are affected when code changes
  - Find all dependents (files that import a file)
  - Find all dependencies (files that a file imports)
  - Get blast radius analysis for change impact

  TRIGGER when: user mentions "dependencies", "impact analysis", "blast radius",
  "what depends on", "what uses this", "affected files", "code relationships",
  or when other skills need dependency information.

  Used by: docs-manager, spec-manager for incremental updates.
---

# Code Graph

A lightweight dependency graph skill that tracks import/export relationships in your codebase. Other skills use this for impact-aware scanning and incremental updates.

## Quick Reference

| Command | Description |
|---------|-------------|
| `build` | Full scan, build dependency graph from codebase |
| `update` | Incremental update via git diff (only changed files) |
| `query <file>` | Show dependencies + usages for a file |
| `impact <file>` | Show blast radius if this file changes |
| `dependents <file>` | Show all files that depend on this one |
| `dependencies <file>` | Show all files this one depends on |
| `clear` | Delete cached graph |
| `--use <backend> [--global]` | Record which substrate backend this project (or this machine) uses |
| `help` | Display help and usage information |

## How It Works

### Graph Storage

The dependency graph and classifications are stored in the project at:
```
knowledge-base/
├── settings.json             # Project settings — committed, see below
└── .graph/                   # Generated cache — self-ignoring
    ├── graph.json            # The active dependency graph
    ├── graph.homegrown.json  # Per-backend copy (one per substrate)
    └── classifications.json  # Directory classifications (source/exclude)
```

`.graph/` writes its own `.gitignore` naming the regenerable files, so the cache is never
committed. It names them individually rather than using `*` because `behavior.json` also lives
there and **is** committed — its coverage comes from running the test suite and cannot be
rebuilt from source (ADR-017).

**Why two copies of the graph.** `graph.json` is the active one, read by docs-manager,
spec-manager and behavior-graph. `graph.<backend>.json` is written alongside it so switching
substrates does not destroy the graph you would want to diff the new one against.

### Project Settings

Optional. Absent, everything below is the default.

```json
{
  "substrate": {
    "backend": "auto",
    "symbols": false
  },
  "directories": {
    "docs": "source"
  }
}
```

`directories` is how a project argues with the built-in exclusions — see
[Overriding the built-in exclusions](#overriding-the-built-in-exclusions) below.

`symbols` asks a backend to record *which symbol* each edge leaves and arrives at, where it
knows. Off by default: measured on this repository it turns **120 file-level edges into
698**, over the same 77 file pairs, because a test module calling one helper sixty times is
sixty symbol pairs and one dependency. A backend that cannot see symbols is unaffected —
this asks for refinement, it does not require it, and the node queries answer identically
either way.

`backend` resolves in three layers: **this project's file, then the machine default, then the
built-in floor.**

| Value in the project file | Means |
|---|---|
| a backend name (incl. `homegrown`) | this project decided for itself |
| `auto` | defer to the machine default, then the floor |
| absent | not yet decided — the first build records the machine default here, if there is one |

The machine default is answered once, when `freya install` runs, and lives in
`~/.freya/settings.json`. To change it, or to set one project apart:

```bash
freya code-graph --use graphify            # this project
freya code-graph --use graphify --global   # and every future one
freya code-graph --use homegrown           # opt this project out
```

Naming a backend that is not installed does not fail the build; it falls back, and says so on
stderr:

```
code-graph: 'graphify' unavailable (not installed) — using 'homegrown' instead, with reduced coverage
```

The file is committed, so a clone gets the same backend. It sits in `knowledge-base/` rather
than the project root, and outside `.graph/` because that is regenerable cache and `--clear`
would take a real decision with it.

**That is why the first build writes the machine default in rather than just using it.** Left
implicit, the same commit would graph differently on a machine that has a default and one that
does not — and integration behaviours' static fingerprints come from the graph closure into
`behavior.json`, which *is* committed, so the divergence would surface as a diff that reads
like behaviour drift. A run with nothing configured writes nothing: "not yet decided" is an
honest state, and recording the floor as though somebody chose it is not.

| Machine-level (`~/.freya/settings.json`) | Project-level |
|---|---|
| `substrate.backend`, `substrate.symbols` | those, plus `directories` |

Scope is never a machine-level setting — a global `docs: source` would apply to repositories
nobody has looked at. Anything else in that file is ignored and reported.

### Backends

The graph is produced by a **substrate backend** behind a fixed contract
(`scripts/substrate.py`). Two ship today:

| Backend | Languages | Requires |
|---|---|---|
| `homegrown` | 4 — TypeScript, JavaScript, Python, Go (6 extensions) | nothing — stdlib only |
| `graphify` | 40 across 93 extensions, incl. Java, Rust, C#, Kotlin, Swift, Scala, Ruby, PHP, SQL, Terraform, Fortran, Elixir | the `graphify` binary on PATH |

`graphify` also emits `calls`, `inherits` and `references` — relations the homegrown resolver
has no notion of, because it resolves module references between files and has no idea what a
symbol is.

**It is opt-in, deliberately.** With no machine default set, `auto` stays on the floor even
when another backend would read more of your repository — and tells you what it is leaving
out:

```
code-graph: 'graphify' is installed and declares it reads 2 file(s) here that 'homegrown'
cannot (.ps1, .sh).
  → freya code-graph --use graphify            (this project)
  → freya code-graph --use graphify --global   (and every future one)
```

The count excludes extensions the other backend declares but selects by *name* —
`package.json` produces nodes and an arbitrary `x.json` does not — because almost every
repository has a manifest and the hint would otherwise fire everywhere on the strength of a
file the backend may well ignore.

Scoring silently would mean that installing a binary anywhere on PATH changed the substrate —
and therefore every blast radius — for every project on the machine at once, with no diff.
A substrate change is a measured migration (CD-13): `graph.<backend>.json` is written beside
`graph.json` precisely so you can diff the new one against the old before trusting it.

Every graph records which backend built it and what that backend can read:

```json
"substrate": {
  "backend": "homegrown",
  "coverage": {
    "languages": ["go", "javascript", "python", "typescript"],
    "extensions": [".go", ".js", ".jsx", ".py", ".ts", ".tsx"],
    "relations": ["imports", "re_exports"],
    "incremental": true
  }
}
```

That block is what lets a caller tell **"this repo has no dependencies"** from **"this backend
cannot read Java"** — the distinction that made a Java repo read as greenfield.

### Classifications File Structure

```json
{
  "version": 1,
  "classified_at": "2024-01-15T10:30:00Z",
  "project_context": {
    "framework": "Next.js",
    "language": "typescript",
    "package_manager": "npm/yarn/pnpm"
  },
  "directories": {
    "src": { "type": "source", "confidence": 1.0, "source": "rule" },
    "lib": { "type": "source", "confidence": 1.0, "source": "rule" },
    "custom-codegen": { "type": "source", "confidence": 0.85, "source": "ai" },
    "experimental": { "type": "exclude", "confidence": 1.0, "source": "user" },
    ".next": { "type": "exclude", "confidence": 1.0, "source": "rule" }
  }
}
```

#### Overriding the built-in exclusions

Some directory names are excluded by default — artifact trees like `node_modules/` and
`dist/` at any depth, and convention names like `docs/`, `examples/`, `scripts/` and
`generated/` at the repo root only.

Those are **defaults, not verdicts.** Nothing in this skill can know that your repository
keeps real source in a directory called `target`, or that your `docs/` is a literate
programming tree. Say so in `knowledge-base/settings.json` and it is believed:

```json
{
  "directories": {
    "docs": "source",
    "packages/legacy": "exclude"
  }
}
```

`settings.json` and not `classifications.json`: the latter is gitignored regenerable cache,
so a verdict written there works for whoever typed it and vanishes on clone — CI and every
colleague would silently graph a smaller codebase and be told the build succeeded. Keys are
folded, so `docs`, `docs/`, `./docs` and `docs\lit` all name what you meant.

| Verdict source | Overrides |
|---|---|
| `settings.json`, or a `user` classification | Everything, including artifact-tree names and `.gitignore` |
| An `ai` classification | Root convention names and `.gitignore`, but not artifact trees |
| `rule` / `gitignore` classifications | Nothing — these *are* the defaults' own output, so letting them override would be circular |

Two things a verdict does not override: file-kind patterns (`*.d.ts`, `*.min.js` — claims
about what a file is, not which directories are in scope), and a more specific verdict
beneath it (`packages/` can be source while `packages/legacy/` is excluded).

`classifications.json` still holds the *derived* verdicts, and the model's. Those are cache:
`rule` and `gitignore` entries are discarded and re-derived whenever the rules change, which
is how a fix to the defaults reaches a project that was already graphed.

Until 2026-08-20 a `source` verdict was accepted, written to disk, and then silently
overruled — `_should_exclude` never consulted classifications at all. A default that cannot
be argued with is not a default, and the one certain thing about a hardcoded answer is that
it is wrong for somebody.

### Graph Structure

```json
{
  "version": 2,
  "commit": "abc123",
  "timestamp": "2024-01-15T10:30:00Z",
  "project_root": "/path/to/project",
  "substrate": {
    "backend": "homegrown",
    "coverage": { "languages": ["typescript"], "extensions": [".ts", ".tsx"],
                  "relations": ["imports", "re_exports"], "incremental": true },
    "schema": 2
  },
  "files": {
    "src/lib/auth/validateToken.ts": {
      "exports": ["validateToken", "TokenPayload"],
      "imports": [
        {"to": "external:jsonwebtoken", "kind": "imports", "provenance": "extracted"},
        {"to": "src/lib/auth/config.ts", "kind": "imports", "provenance": "extracted"}
      ],
      "dependents": [
        {"from": "src/api/middleware/auth.ts", "kind": "imports", "provenance": "extracted"},
        {"from": "src/lib/auth/index.ts", "kind": "re_exports", "provenance": "extracted"}
      ],
      "language": "typescript"
    }
  }
}
```

With `symbols` on, an edge also carries `from_symbol`, `to_symbol` and `line`. Those refine
the file anchor and never replace it, so anything that ignores them behaves exactly as it did
before they existed.

An edge names its far end in `to` (or `from`, going backwards), and that end is one of three
things: a project-relative path (a real edge), `external:<pkg>` (third-party), or
`unresolved:<raw>` (meant something in this project and could not be found). The third is
never dropped — a silently-empty answer is worse than an honest gap.

**Edges were bare strings until 2026-08-20** (schema 1). A string can carry exactly one fact,
so `imports` and `re_exports` were indistinguishable and symbol-level relations could not be
written at all. Readers accept both shapes; `substrate.edge_other` is the projection, and
`load()` brings an older graph forward. See [references/graph-schema.md](references/graph-schema.md).

### What each command returns

The distinction is deliberate, not incidental — three other skills feed the node queries
straight into set arithmetic, where an edge object would raise `unhashable type: 'dict'`.

| Command | Returns |
|---|---|
| `--query <file>` | **Edge objects.** "Tell me about this file", so kind and provenance are the point |
| `--impact` / `--dependents` / `--dependencies` | **Path strings.** "Which files are affected" — a set of nodes, not edges |

`--build`, `--update`, `--query` and `--impact` may also carry an **`unmapped_source`** key
naming the in-scope source files the backend could not read, with the directories to search
instead. It is absent whenever there is nothing to say, so its presence means the answer above
it is computed over an incomplete graph. `--dependents`/`--dependencies` keep their bare arrays
and say the same thing on stderr.

### Import Parsing

The script parses imports for multiple languages:

| Language | Import Patterns |
|----------|----------------|
| TypeScript/JS | `import { x } from './y'`, `import x from './y'`, `import type { X } from './y'`, `require('./y')`, `export * from './y'` |
| Python | `from x import y`, `import x`, `from .pkg import y` |
| Go | `import "module/path"`, `import alias "module/path"` |

Not `from . import x` — the bare-package form has no module name to resolve and is tracked in
the backlog alongside `import a, b` and indented imports.

### Impact Analysis Algorithm

```
impact(file) = file + direct_dependents(file) + transitive_dependents(file)
```

Traverses the dependency graph to find all files that would be affected by changes to the input file(s).

---

## Commands

### `freya-code-graph build`

Build the dependency graph from scratch by scanning all source files.

**Process:**
1. **Classify directories** (hybrid: rules → AI → user confirmation)
2. Detect project root (look for .git, package.json, pyproject.toml, etc.)
3. Scan source directories using classifications
4. Parse imports/exports from each file
5. Build reverse mapping (dependents) from imports
6. Store graph in `knowledge-base/.graph/`

**Directory Classification System:**

The build process uses a hybrid approach to determine which directories contain source code:

1. **Rules first** - Known patterns are instantly classified:
   - Source: `src/`, `lib/`, `app/`, `components/`, `pages/`, `cmd/`, `pkg/`, etc.
   - Exclude: artifact trees and framework caches — see *Overriding the built-in exclusions*
     for the tiers and how to overrule any of them

2. **AI classification** - For unknown directories, AI classifies with confidence

3. **User confirmation** - Low confidence (<80%) requires user input:
   ```
   Uncertain classification for 'custom-codegen/'
     AI suggests: source (65% confidence)
     Reasoning: Contains generated code but may be tracked

     [1] Source - include in dependency graph
     [2] Exclude - skip this directory

   Your choice (1 or 2):
   ```

   **Non-interactive mode** (`--non-interactive`, and auto-enabled when stdin is not a
   TTY — e.g. when invoked by wrap-up): never prompts; uncertain directories default to
   **source** so real code is never silently dropped. Use it for any automated run.

4. **Cached** - Classifications saved to `knowledge-base/.graph/classifications.json`

**Import resolution:**

- **Relative imports** (`./x`, `../y`) resolve against the project directory (independent of the current working directory).
- **Path aliases** (`@/lib/x` and similar) resolve via `tsconfig.json` / `jsconfig.json` `compilerOptions.paths` + `baseUrl`. Without this, alias-heavy projects (e.g. Next.js) would show an empty internal graph.
- Each import edge is tagged: an internal project-relative path, `external:<pkg>` (a third-party package), or `unresolved:<import>` (a relative/alias import that could not be resolved — surfaced rather than silently dropped, so "no dependencies" is distinguishable from "could not resolve").

**File patterns scanned:**
- `**/*.ts`, `**/*.tsx`, `**/*.js`, `**/*.jsx`
- `**/*.py`
- `**/*.go`

**Excluded directories:** artifact trees (`node_modules`, `vendor`, `dist`, `build`, `target`,
`__pycache__`, framework caches, …) at any depth; convention names (`docs`, `examples`,
`scripts`, `generated`) at the repo root only; anything in your `.gitignore`; and anything
classified `exclude`. The authoritative list is `_get_exclusion_rules()` in `graph_ops.py` —
this file deliberately does not keep a second copy, because the two copies it used to keep had
already drifted apart. Every one of them is a default you can overrule: see
[Overriding the built-in exclusions](#overriding-the-built-in-exclusions).

**Output:**
```
Scanning /path/to/project...
Classifying directories...
Classified: 5 source dirs, 3 excluded dirs
Found 147 source files
Built dependency graph:
  - 147 files scanned
  - 312 import relationships
  - 89 export declarations
  - Stored to knowledge-base/.graph/graph.json
```

### `freya-code-graph update`

Incrementally update the graph by only processing changed files.

**Process:**
1. Check if graph exists in cache
2. Get last commit hash from stored graph
3. Run `git diff <last-commit>..HEAD --name-only`
4. Re-parse only changed files
5. Update dependents for affected files
6. Store updated graph

**Output:**
```
Updated dependency graph:
  - 5 files changed since commit abc123
  - 3 new import relationships
  - 1 removed import relationship
  - Graph updated at 2024-01-15T11:00:00Z
```

### `freya-code-graph query <file>`

Show complete dependency information for a file.

**Output includes:**
- What the file exports (empty under `graphify`, which does not extract them)
- What the file imports (dependencies), as edge objects
- What files depend on this one (dependents)
- The detected language

**Example:**
```
File: src/lib/auth/validateToken.ts

Exports:
  - validateToken
  - TokenPayload

Dependencies (imports from):
  - external:jsonwebtoken
  - → src/lib/auth/config.ts

Dependents (imported by):
  - src/api/middleware/auth.ts
  - src/lib/auth/index.ts  [re_exports]

Language: typescript
```

With `substrate.symbols` on, each edge also names the symbols it joins —
`[calls: verifyChallenge → query:88]` — so two edges between the same pair of files are
distinguishable rather than printing as identical lines.

### `freya-code-graph impact <file>`

Show blast radius analysis - all files that would be affected if this file changes.

**Process:**
1. Start with the input file
2. Find all direct dependents
3. Recursively find dependents of dependents (transitive)
4. Present the full impact set

**Example:**
```
Impact analysis for: src/lib/auth/validateToken.ts

Direct impact (3 files):
  - src/api/middleware/auth.ts
  - src/api/routes/users.ts
  - src/lib/auth/index.ts

Transitive impact (5 files):
  - src/api/routes/admin.ts (via middleware)
  - src/api/routes/dashboard.ts (via middleware)
  - src/pages/api/user.ts (via routes/users)
  - src/pages/api/settings.ts (via routes/users)
  - src/lib/auth/session.ts (via auth/index)

Total blast radius: 8 files affected
```

### `freya-code-graph impact <file1> <file2> ...`

Analyze combined impact for multiple files.

**Example:**
```
freya-code-graph impact src/lib/auth/validateToken.ts src/lib/db/connection.ts
```

Returns combined blast radius for all specified files.

### `freya-code-graph dependents <file>`

Show all files that depend on this file (direct and transitive).

**Example:**
```
Dependents of src/lib/utils/format.ts:

Direct (12 files):
  - src/components/ui/Table.tsx
  - src/components/ui/Card.tsx
  - src/lib/api/response.ts
  ...

Transitive (8 files):
  - src/pages/index.tsx (via components)
  ...
```

### `freya-code-graph dependencies <file>`

Show all files that this file depends on (direct and transitive).

**Example:**
```
Dependencies of src/api/routes/users.ts:

Direct:
  - src/lib/auth/validateToken.ts
  - src/lib/db/connection.ts
  - src/lib/utils/format.ts

Transitive:
  - src/lib/auth/config.ts (via auth)
  - src/lib/db/schema.ts (via db)
```

### `freya-code-graph clear`

Delete the cached graph for this project.

**Use when:**
- Graph seems corrupted or out of sync
- Significant restructuring of the codebase
- Switching branches with different file structures

**Output:**
```
Cleared dependency graph cache for this project.
Run freya-code-graph build to create a fresh graph.
```

### `freya-code-graph help`

Display help information about the code-graph skill.

**Example usage:**
```
freya-code-graph help
freya-code-graph --help
freya-code-graph -h
```

---

## Using with Other Skills

### With docs-manager

When running `freya-docs-manager update`:
1. docs-manager checks if code-graph skill exists
2. If available, calls `freya-code-graph impact <changed-files>`
3. Uses impact results to determine which docs need updating
4. Falls back to simple git diff if code-graph unavailable

### With spec-manager

When running `freya-spec-manager update`:
1. spec-manager checks if code-graph skill exists
2. If available, calls `freya-code-graph impact <changed-files>`
3. Includes dependent files in affected code analysis
4. Falls back to simple git diff if code-graph unavailable

---

## Command Usage

The `freya code-graph` command wraps the underlying `graph_ops.py` script:

```bash
# Build graph
freya code-graph --build --dir /path/to/project

# Update graph
freya code-graph --update --dir /path/to/project

# Query file
freya code-graph --query src/lib/auth.ts

# Impact analysis
freya code-graph --impact src/lib/auth.ts

# Dependents
freya code-graph --dependents src/lib/auth.ts

# Dependencies
freya code-graph --dependencies src/lib/auth.ts

# Clear cache
freya code-graph --clear --dir /path/to/project

# Output formats
freya code-graph --query src/lib/auth.ts --format json
freya code-graph --query src/lib/auth.ts --format summary
```

**Output formats:**
- `--format json` (default): Machine-readable JSON
- `--format summary`: Human-readable summary

---

## Limitations

Everything here describes the **`homegrown`** backend unless it says otherwise, because that
is what runs unless a project opts into another one.

- **Language support**: TypeScript/JS, Python, Go. Anything else is a *declared* blind spot —
  the `substrate.coverage` block names what was read, so a caller can tell "no dependencies"
  from "this backend cannot read Java". `graphify` covers 40 languages; it is opt-in.
- **Dynamic imports**: may not catch `import()` or `require(variable)`.
- **String literals**: the regexes read import statements inside string bodies, which is a
  known false-positive source — a real parser correctly ignores them.
- **Still unparsed in Python**: `from . import x`, `import a, b`, and indented imports.
- **External packages**: tracked as `external:<name>` signals, not resolved into the graph.
  `graphify` emits no `external:` edges at all for TS/JS/Python — it records package
  dependencies from manifests instead.
- **`exports`**: not extracted by `graphify`, so the field is empty under that backend.
- **Provenance does not gate anything yet.** Every edge records whether it was `extracted` or
  `inferred`, and nothing filters on it — the two-tier design is recorded and not enforced.
- **Monorepos**: cross-package imports resolve via `package.json#workspaces` and
  `pnpm-workspace.yaml`, so one graph covers the whole workspace. Unrelated subprojects that
  are not workspace members still need their own.

---

## References

- `references/graph-schema.md` - Full JSON schema for the graph structure
