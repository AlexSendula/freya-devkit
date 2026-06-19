# Code Graph JSON Schema

This document describes the structure of the dependency graph stored in `graph.json`.

## File Location

```
docs/.code-graph/graph.json
```

The graph is stored inside the project under `docs/` so it stays version-controlled and in sync with branch changes.

**Gitignore:** Add `docs/.code-graph/` to `.gitignore` if you prefer not to commit the generated graph.

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
          "items": {
            "type": "string"
          },
          "description": "List of import paths (relative or absolute within project)"
        },
        "dependents": {
          "type": "array",
          "items": {
            "type": "string"
          },
          "description": "List of files that import this file (reverse mapping of imports)"
        },
        "category": {
          "type": "string",
          "enum": ["auth", "api", "data", "ui", "infra", "util", "config", "test", "unknown"],
          "description": "Inferred category based on file path and content"
        },
        "language": {
          "type": "string",
          "enum": ["typescript", "javascript", "python", "go"],
          "description": "Detected programming language"
        }
      }
    }
  }
}
```

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
        "jsonwebtoken",
        "./config",
        "../utils/logger"
      ],
      "dependents": [
        "src/api/middleware/auth.ts",
        "src/api/routes/users.ts",
        "src/lib/auth/index.ts"
      ],
      "category": "auth",
      "language": "typescript"
    },
    "src/lib/auth/config.ts": {
      "exports": ["authConfig", "AuthConfig"],
      "imports": [],
      "dependents": [
        "src/lib/auth/validateToken.ts",
        "src/lib/auth/session.ts"
      ],
      "category": "config",
      "language": "typescript"
    },
    "src/api/middleware/auth.ts": {
      "exports": ["authMiddleware", "requireAuth"],
      "imports": [
        "../../../lib/auth/validateToken",
        "../../../lib/utils/logger"
      ],
      "dependents": [
        "src/api/routes/users.ts",
        "src/api/routes/admin.ts"
      ],
      "category": "api",
      "language": "typescript"
    },
    "src/api/routes/users.ts": {
      "exports": ["usersRouter"],
      "imports": [
        "../middleware/auth",
        "../../../lib/db/connection",
        "../../../lib/utils/format"
      ],
      "dependents": [
        "src/app.ts"
      ],
      "category": "api",
      "language": "typescript"
    }
  }
}
```

## Field Descriptions

### Top-Level Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `version` | integer | Yes | Schema version (currently 1) |
| `commit` | string | No | Git commit hash (null if not in git repo) |
| `timestamp` | string | Yes | ISO 8601 timestamp of graph creation |
| `project_root` | string | Yes | Absolute path to project directory |
| `files` | object | Yes | Map of file paths to FileInfo objects |

### FileInfo Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `exports` | string[] | No | List of exported symbol names |
| `imports` | string[] | Yes | List of imported module paths (resolved to project-relative) |
| `dependents` | string[] | Yes | Files that import this file |
| `category` | string | No | Inferred category |
| `language` | string | No | Detected language |

### Categories

| Category | Description | Path Patterns |
|----------|-------------|---------------|
| `auth` | Authentication/authorization | `**/auth/**`, `**/middleware/auth*` |
| `api` | API routes/handlers | `**/api/**`, `**/routes/**` |
| `data` | Data models/schemas | `**/models/**`, `**/schema/**`, `**/db/**` |
| `ui` | UI components | `**/components/**`, `**/pages/**` |
| `infra` | Infrastructure/config | `**/infra/**`, `**/deploy/**` |
| `util` | Utility functions | `**/utils/**`, `**/lib/**` |
| `config` | Configuration files | `**/*.config.*`, `**/config/**` |
| `test` | Test files | `**/*.test.*`, `**/*.spec.*`, `**/__tests__/**` |
| `unknown` | Uncategorized | (default) |

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
