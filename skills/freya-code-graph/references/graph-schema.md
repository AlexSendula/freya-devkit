# Code Graph JSON Schema

This document describes the structure of the dependency graph stored in `graph.json`.

## File Location

```
knowledge-base/.graph/graph.json
```

The graph is stored inside the project under `knowledge-base/` so it stays version-controlled and in sync with branch changes.

**Gitignore:** Add `knowledge-base/.graph/` to `.gitignore` if you prefer not to commit the generated graph.

## Schema

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "required": ["version", "timestamp", "project_root", "files"],
  "properties": {
    "version": {
      "type": "integer",
      "description": "Schema version number",
      "const": 1
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
                             "description": "False means the contract forces a full rebuild" }
          }
        },
        "degraded_from": {
          "type": "string",
          "description": "Present only when the configured backend was unavailable and this is a fallback"
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
          "enum": ["typescript", "javascript", "python", "go"],
          "description": "Detected programming language"
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
        }
      }
    },
    "ReverseEdge": {
      "type": "object",
      "required": ["from", "kind", "provenance"],
      "description": "An Edge keyed by `from` instead of `to`; kind and provenance are the forward edge's",
      "properties": {
        "from": { "type": "string" },
        "kind": {
          "type": "string",
          "enum": ["imports", "re_exports", "calls", "inherits", "references"]
        },
        "provenance": { "type": "string", "enum": ["extracted", "inferred"] }
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
  "version": 1,
  "commit": "abc123def456",
  "timestamp": "2024-01-15T10:30:00Z",
  "project_root": "/Users/example/projects/my-app",
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
| `version` | integer | Yes | Schema version (currently 1) |
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

`provenance` is **not** the deterministic-vs-model axis. Phase 0 measured graphify emitting
`INFERRED` edges from a pure AST pass with no model involved; it records how directly the edge
was read out of the source text, and nothing about who read it.

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

A relative/aliased import that the resolver could not map to a real file is
stored with an `unresolved:` prefix (rather than silently dropped), e.g.
`unresolved:./missing`. So an entry in `imports` is **internal** (real
project wiring) only when it carries neither the `external:` nor the
`unresolved:` prefix — this is the predicate consumers use to count internal
edges (e.g. `spec-manager bootstrap`'s shape detector).

## Graph Operations

### Impact Analysis

```python
def get_impact(graph, file_path):
    """Get all files affected by changes to file_path."""
    visited = set()

    def traverse(path):
        if path in visited:
            return
        visited.add(path)
        file_info = graph['files'].get(path, {})
        for dependent in file_info.get('dependents', []):
            traverse(dependent)

    traverse(file_path)
    return visited
```

### Dependency Traversal

```python
def get_dependencies(graph, file_path):
    """Get all files that file_path depends on."""
    visited = set()

    def traverse(path):
        if path in visited:
            return
        visited.add(path)
        file_info = graph['files'].get(path, {})
        for imp in file_info.get('imports', []):
            if not imp.startswith('external:'):
                traverse(imp)

    traverse(file_path)
    return visited
```
