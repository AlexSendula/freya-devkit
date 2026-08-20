# Code Graph JSON Schema

This document describes the structure of the dependency graph stored in `graph.json`.

## File Location

```
knowledge-base/.graph/graph.json
```

The graph is stored inside the project under `knowledge-base/` so it moves with the checkout
and stays in sync with branch changes.

**It is not committed, and that is not a choice you make.** `.graph/` writes its own
`.gitignore` on every build, naming `graph.json`, `graph.*.json`, `classifications.json` and
`docs.json`. The one file in that directory which *is* tracked is `behavior.json`, whose
observed coverage comes from running the test suite and cannot be rebuilt by re-reading
source (ADR-017) — which is why the ignore names files individually instead of using `*`.

## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["version", "timestamp", "project_root", "files"],
  "properties": {
    "version": {
      "type": "integer",
      "description": "Schema version number. 2 since 2026-08-20, when edges became objects; a 1 on disk is read and brought forward",
      "const": 2
    },
    "commit": {
      "type": "string",
      "description": "Git commit hash the graph was built from (if available)"
    },
    "timestamp": {
      "type": "string",
      "format": "date-time",
      "description": "ISO 8601 timestamp when the graph was created/updated"
    },
    "project_root": {
      "type": "string",
      "description": "Absolute path to the project root directory"
    },
    "substrate": {
      "type": "object",
      "description": "Which backend produced this graph and what it can read (Track B Phase 1)",
      "required": ["backend", "coverage"],
      "properties": {
        "backend": { "type": "string", "description": "Backend name, e.g. homegrown" },
        "coverage": {
          "type": "object",
          "properties": {
            "languages":  { "type": "array", "items": { "type": "string" } },
            "extensions": { "type": "array", "items": { "type": "string" } },
            "relations":  { "type": "array", "items": { "type": "string" },
                            "description": "Edge kinds this backend emits" },
            "incremental": { "type": "boolean",
                             "description": "The backend declares whether it can drop deleted nodes. Declared, not currently enforced — see ADR-018" }
          }
        },
        "degraded_from": {
          "type": "string",
          "description": "Present only when the configured backend was unavailable and this is a fallback"
        },
        "exclusions": {
          "type": "object",
          "description": "What the project declared out of scope for this build",
          "properties": {
            "directories": { "type": "array", "items": { "type": "string" } },
            "patterns":    { "type": "array", "items": { "type": "string" } },
            "overrides":   { "type": "array", "items": { "type": "string" },
                             "description": "Present only when the project overrode a default" }
          }
        },
        "unmapped_source": {
          "type": "object",
          "description": "In-scope program source this backend does not read (ADR-029). `files: 0` means the census ran and found none; the key's absence means the graph predates the census; `files: null` with `error` means it could not run",
          "properties": {
            "files":               { "type": ["integer", "null"] },
            "backend":             { "type": ["string", "null"] },
            "extensions":          { "type": "object", "additionalProperties": { "type": "integer" } },
            "directories":         { "type": "object", "additionalProperties": { "type": "integer" } },
            "readable_by":         { "type": "object", "additionalProperties": { "type": "integer" } },
            "advice":              { "type": "string" },
            "extensions_omitted":  { "type": "integer" },
            "directories_omitted": { "type": "integer" },
            "truncated":           { "type": "boolean" },
            "error":               { "type": "string" }
          }
        },
        "validation": {
          "type": "object",
          "description": "Present only when the produced graph broke the contract; the errors are recorded rather than only printed",
          "properties": {
            "error_count": { "type": "integer" },
            "errors":      { "type": "array", "items": { "type": "string" } }
          }
        }
      }
    },
    "files": {
      "type": "object",
      "additionalProperties": {
        "$ref": "#/definitions/FileInfo"
      }
    }
  },
  "definitions": {
    "FileInfo": {
      "type": "object",
      "required": ["imports", "dependents"],
      "properties": {
        "exports": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "List of exported symbols (functions, classes, types, constants)"
        },
        "imports": {
          "type": "array",
          "items": { "$ref": "#/definitions/Edge" },
          "description": "Outgoing edges. Each names a project-relative path, or an external:/unresolved: signal"
        },
        "dependents": {
          "type": "array",
          "items": { "$ref": "#/definitions/ReverseEdge" },
          "description": "Incoming edges — the reverse of every other file's imports"
        },
        "language": {
          "type": "string",
          "description": "Detected language. Deliberately not an enum: the homegrown backend writes one of four values and the graphify backend writes any of forty, so pinning the list here would exclude exactly the polyglot support this field exists to report. May be null for an extensionless file"
        }
      }
    },
    "Edge": {
      "type": "object",
      "required": ["to", "kind", "provenance"],
      "properties": {
        "to": {
          "type": "string",
          "description": "Project-relative path, or external:<pkg> / unresolved:<spec>"
        },
        "kind": {
          "type": "string",
          "enum": ["imports", "re_exports", "calls", "inherits", "references"],
          "description": "The relation. A backend may only emit kinds its coverage claims"
        },
        "provenance": {
          "type": "string",
          "enum": ["extracted", "inferred"],
          "description": "How directly it was read out of the source"
        },
        "from_symbol": {
          "type": "string",
          "description": "Optional. The symbol the edge leaves. Refines the file anchor, never replaces it"
        },
        "to_symbol": {
          "type": "string",
          "description": "Optional. The symbol it arrives at"
        },
        "line": {
          "type": "integer",
          "minimum": 1,
          "description": "Optional. 1-based line of the statement that produced the edge"
        }
      }
    },
    "ReverseEdge": {
      "type": "object",
      "required": ["from", "kind", "provenance"],
      "description": "An Edge keyed by `from` instead of `to`. Every other field is the forward edge's, copied verbatim — including the optional symbols, without which two symbol-refined edges between one file pair collapse into byte-identical duplicates",
      "properties": {
        "from": { "type": "string" },
        "kind": {
          "type": "string",
          "enum": ["imports", "re_exports", "calls", "inherits", "references"]
        },
        "provenance": { "type": "string", "enum": ["extracted", "inferred"] },
        "from_symbol": { "type": "string", "description": "Optional. The symbol the forward edge left" },
        "to_symbol": { "type": "string", "description": "Optional. The symbol it arrived at" },
        "line": { "type": "integer", "minimum": 1, "description": "Optional. 1-based line of the statement that produced the forward edge" }
      }
    }
  }
}
```

### Edges were strings until 2026-08-20

An edge used to be a bare path — `"imports": ["./config"]`. A string can carry exactly one
fact, where the edge points, so `a imports b` and `a re-exports b` were the same value and
`a calls b` could not be written at all. Phase 0 measured the cost: of the 5,027 links
graphify produces for the testbed, this shape could express 2,102.

**Readers must accept both.** `graph.json` is gitignored, so there is no committed copy to
correct in a commit — an older one stays on a given machine until something rebuilds it, and
refusing to read it looks identical to a project with no dependencies. `substrate.edge_other`
is the projection to use; `substrate.upgrade_edges` rewrites a loaded graph in place. An
upgraded edge claims `imports` / `extracted`, which is all the string era ever determined.

## Example

```json
{
  "version": 2,
  "commit": "abc123def456",
  "timestamp": "2024-01-15T10:30:00Z",
  "project_root": "/Users/example/projects/my-app",
  "substrate": {
    "backend": "homegrown",
    "coverage": {
      "languages": ["go", "javascript", "python", "typescript"],
      "extensions": [".go", ".js", ".jsx", ".py", ".ts", ".tsx"],
      "relations": ["imports", "re_exports"],
      "incremental": true
    },
    "schema": 2,
    "exclusions": { "directories": ["vendor"], "patterns": ["dist/"] }
  },
  "files": {
    "src/lib/auth/validateToken.ts": {
      "exports": ["validateToken", "TokenPayload", "TokenConfig"],
      "imports": [
        {"to": "external:jsonwebtoken", "kind": "imports", "provenance": "extracted"},
        {"to": "src/lib/auth/config.ts", "kind": "imports", "provenance": "extracted"},
        {"to": "src/lib/utils/logger.ts", "kind": "imports", "provenance": "extracted"}
      ],
      "dependents": [
        {"from": "src/api/middleware/auth.ts", "kind": "imports", "provenance": "extracted"},
        {"from": "src/lib/auth/index.ts", "kind": "re_exports", "provenance": "extracted"}
      ],
      "language": "typescript"
    },
    "src/lib/auth/config.ts": {
      "exports": ["authConfig", "AuthConfig"],
      "imports": [],
      "dependents": [
        {"from": "src/lib/auth/validateToken.ts", "kind": "imports", "provenance": "extracted"}
      ],
      "language": "typescript"
    },
    "src/lib/auth/index.ts": {
      "exports": [],
      "imports": [
        {"to": "src/lib/auth/validateToken.ts", "kind": "re_exports", "provenance": "extracted"}
      ],
      "dependents": [],
      "language": "typescript"
    },
    "src/api/middleware/auth.ts": {
      "exports": ["authMiddleware", "requireAuth"],
      "imports": [
        {"to": "src/lib/auth/validateToken.ts", "kind": "imports", "provenance": "extracted"},
        {"to": "unresolved:../../../lib/utils/logger", "kind": "imports", "provenance": "extracted"}
      ],
      "dependents": [],
      "language": "typescript"
    }
  }
}
```

`src/lib/auth/index.ts` is the barrel. Under the old shape its edge to `validateToken.ts`
was indistinguishable from `middleware/auth.ts`'s — both were the string
`"src/lib/auth/validateToken.ts"` — even though one file uses the module and the other only
forwards it.

## Field Descriptions

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | integer | Yes | Schema version (currently **2**). 1 means the bare-string edges this format used until 2026-08-20; readers accept both and `substrate.upgrade_edges` brings one forward |
| `commit` | string | No | Git commit hash (null if not in git repo) |
| `timestamp` | string | Yes | ISO 8601 timestamp of graph creation |
| `project_root` | string | Yes | Absolute path to project directory |
| `substrate` | object | Yes | Which backend built this and what it can read |
| `files` | object | Yes | Map of file paths to FileInfo objects |

### The `substrate` block

Added in Track B Phase 1. It is what lets a caller distinguish **"this repo has no
dependencies"** from **"this backend cannot read Java"** — the confusion that made a Java repo
classify as greenfield.

| Field | Description |
|---|---|
| `backend` | Name of the backend that produced the graph, e.g. `homegrown` |
| `coverage.languages` / `.extensions` | What it parsed. Anything on disk outside this is a blind spot, not an absence |
| `coverage.relations` | Edge kinds it emits. `homegrown` claims `imports` and `re_exports`; it has no notion of a symbol, so it must not claim `calls`, `inherits` or `references` |
| `coverage.incremental` | `false` means the backend cannot reliably drop deleted nodes, and the contract rebuilds from scratch instead |
| `degraded_from` | Present **only** on a fallback: the backend that was configured but unavailable |
| `exclusions` | What the project declared out of scope for this build |
| `unmapped_source` | In-scope program-source files on disk this backend does not read: `{files, extensions, directories, backend[, readable_by, advice, directories_omitted, truncated, error]}`. `files: 0` means the census ran and found none; the key's **absence** means the graph predates it. `files: null` with `error` means the census could not run. Never a refusal — see CD-27 |

### FileInfo Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `exports` | string[] | No | List of exported symbol names |
| `imports` | Edge[] | Yes | Outgoing edges. `to` is project-relative, or an `external:`/`unresolved:` signal |
| `dependents` | ReverseEdge[] | Yes | Incoming edges. `from` is always a project file |
| `language` | string | No | Detected language |

### Edge Fields

| Field | Type | Description |
|-------|------|-------------|
| `to` / `from` | string | The far end. `to` on an import, `from` on a dependent |
| `kind` | string | One of `imports`, `re_exports`, `calls`, `inherits`, `references` |
| `provenance` | string | `extracted` (stated in the source) or `inferred` (derived by resolution) |
| `from_symbol` / `to_symbol` | string | Optional. Which symbol each end is, when the backend can see that far |
| `line` | integer | Optional. 1-based line of the statement that produced the edge |

The last three are **refinement, never replacement** (spec §5, CD-6). Every edge keeps its
file anchor, so a consumer that ignores them behaves exactly as it did before they existed —
which is what lets symbol support be a per-backend capability rather than a schema change.
They appear only when `substrate.symbols` is enabled *and* the backend provides them; the
homegrown resolver never does, because it has no notion of a symbol.

`provenance` is **not** the deterministic-vs-model axis. Phase 0 measured graphify emitting
`INFERRED` edges from a pure AST pass with no model involved; it records how directly the edge
was read out of the source text, and nothing about who read it.

It has exactly **two** values. `unresolved` is not a third one — it is a prefix on the far
end of an edge, because "could not be resolved" is a fact about the *target*, not about how
the edge was read. An edge to `unresolved:./missing` still has a provenance of `extracted`:
the import statement was right there in the source.

**Nothing filters on `provenance` today.** The design says `inferred` edges are advisory and
only `extracted` ones may gate `wrap-up`; no code implements that, so an inferred edge reaches
blast radius indistinguishable from an extracted one. The field is recorded faithfully and is
correct — it is the *enforcement* that does not exist yet. Written down here rather than left
as a promise the schema appears to make.

### What a backend may legitimately not fill in

| Field | Under `homegrown` | Under `graphify` |
|---|---|---|
| `exports` | populated | **always empty** — the extractor has no notion of a module's public surface, so a backend swap empties this field |
| `external:` edges | populated | **not emitted** for TS/JS/Python: graphify records no node for a third-party import, so there is nothing to project. Package dependencies are still read from manifests |
| `from_symbol` / `to_symbol` / `line` | never | only with `substrate.symbols` enabled |

Neither gap is a defect in the projection — the upstream extractor does not produce the
material — but both are real differences a reader has to know about, and the coverage block
has no vocabulary for "does not emit exports". If something starts depending on `exports`,
that is the moment to add one.

A reverse edge carries the forward edge's `kind` — an `inherits` edge read backwards is still
`inherits`, and a blast radius has to be able to ask which kind reached it.

### `category` — removed 2026-08-19

Every file entry used to carry a `category` (`auth`, `api`, `ui`, …) guessed from its path.
Nothing ever read it: the two live things in this toolkit also called "category" are security
findings and spec contexts, and neither comes from here.

Caches written before the removal still contain the key. Readers ignore it, and it disappears
on the next build. See CD-12 in the Track B decision register.

## Path Resolution

### Relative Imports

Relative imports are resolved to project-relative paths:

```typescript
// In src/lib/auth/validateToken.ts
import { config } from './config';
// Resolved to: src/lib/auth/config.ts
```

### External Imports

External package imports are stored with a `external:` prefix:

```typescript
import jwt from 'jsonwebtoken';
// Stored as: "external:jsonwebtoken"
```

### Absolute Imports

Project-absolute imports (with path alias) are resolved when possible:

```typescript
// With tsconfig paths: { "@/*": ["./src/*"] }
import { auth } from '@/lib/auth';
// Resolved to: src/lib/auth.ts
```

### Workspace Imports

In an npm/yarn/pnpm monorepo, a sibling package is resolved to the file it actually names,
not treated as a third-party dependency:

```typescript
// In apps/mobile/src/App.tsx, with workspaces ["packages/*", "apps/*"]
import { extract } from '@acme/domain';
// Resolved to: packages/domain/src/index.ts   (via that package's `main`)
```

Membership is read from `package.json#workspaces` (list or `{ "packages": [...] }`) and from
a top-level `packages:` block in `pnpm-workspace.yaml`. A bare package name honours `main` then
falls back to index resolution; a subpath resolves inside the package.

A specifier that names a workspace package but does not resolve is `unresolved:`, not
`external:` — it could only ever have meant something in this repo.

### Python Imports

Python module syntax is not a filesystem path, so it is resolved with Python's own rules:

```python
import behavior_graph          # a sibling module -> skills/x/scripts/behavior_graph.py
from .adapters import parse    # explicit relative, anchored to the containing package
from myapp.core import db      # src-layout, when a packaging manifest declares one
```

A file inside a package (its directory has `__init__.py`) does **not** search its own
directory: Python 3 removed implicit relative imports, so `import logging` there is absolute
and must not bind a sibling `logging.py`.

Still missed, and tracked in the backlog: `from . import x`, `import a, b`, and indented
imports.

### Unresolved Imports

A relative/aliased import that the resolver could not map to a real file has an edge whose
far end carries an `unresolved:` prefix (rather than being silently dropped), e.g.
`{"to": "unresolved:./missing", ...}`. So an edge in `imports` is **internal** (real project
wiring) only when its far end carries neither the `external:` nor the `unresolved:` prefix —
this is the predicate consumers use to count internal edges (e.g. `spec-manager bootstrap`'s
shape detector), and `substrate.is_internal` is the one implementation of it.

## Graph Operations

**Read edges through `substrate`, never by indexing them directly.** An edge is an object
since schema 2, and a graph already on disk may still hold bare strings — so a reader that
treats either shape as the only one is wrong half the time. `substrate.edge_other(edge)`
gives the far end whichever it is; `edge_ends` and `internal_ends` give the list a
string-era caller used to get.

The recipes below were left in the string era when the schema moved and crashed on every
graph the toolkit writes today. They are correct now, and they are the shape to copy.

### Impact Analysis

```python
import substrate

def get_impact(graph, file_path):
    """Every file affected by a change to file_path."""
    visited = set()

    def traverse(path):
        if path in visited:
            return
        visited.add(path)
        info = graph['files'].get(path, {})
        for dependent in substrate.edge_ends(info.get('dependents')):
            traverse(dependent)

    traverse(file_path)
    return visited
```

### Dependency Traversal

```python
import substrate

def get_dependencies(graph, file_path):
    """Every file that file_path depends on."""
    visited = set()

    def traverse(path):
        if path in visited:
            return
        visited.add(path)
        info = graph['files'].get(path, {})
        # internal_ends drops the external:/unresolved: signals as well as
        # projecting the edge, so there is nothing left to prefix-check by hand.
        for target in substrate.internal_ends(info.get('imports')):
            traverse(target)

    traverse(file_path)
    return visited
```
