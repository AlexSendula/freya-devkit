---
name: code-graph
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
| `help` | Display help and usage information |

## How It Works

### Graph Storage

The dependency graph and classifications are stored in the project at:
```
knowledge-base/.graph/
├── graph.json           # Dependency graph
└── classifications.json # Directory classifications (source/exclude)
```

This keeps the graph version-controlled alongside the code and in sync with branch changes.

**Note:** Add `knowledge-base/.graph/` to `.gitignore` if you don't want to commit the generated graph.

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

### Graph Structure

```json
{
  "version": 1,
  "commit": "abc123",
  "timestamp": "2024-01-15T10:30:00Z",
  "project_root": "/path/to/project",
  "files": {
    "src/lib/auth/validateToken.ts": {
      "exports": ["validateToken", "TokenPayload"],
      "imports": ["jsonwebtoken", "./config"],
      "dependents": [
        "src/api/middleware/auth.ts",
        "src/api/routes/users.ts"
      ],
      "category": "auth"
    }
  }
}
```

### Import Parsing

The script parses imports for multiple languages:

| Language | Import Patterns |
|----------|----------------|
| TypeScript/JS | `import { x } from './y'`, `import x from './y'`, `require('./y')`, `export * from './y'` |
| Python | `from x import y`, `import x`, `from . import x` |
| Go | `import "module/path"`, `import alias "module/path"` |

### Impact Analysis Algorithm

```
impact(file) = file + direct_dependents(file) + transitive_dependents(file)
```

Traverses the dependency graph to find all files that would be affected by changes to the input file(s).

---

## Commands

### `/freya-devkit:code-graph build`

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
   - Exclude: `.next/`, `node_modules/`, `dist/`, `build/`, `.git/`, etc.

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

**Excluded directories:**
- `node_modules`, `__pycache__`, `.git`
- `dist`, `build`, `venv`
- `.next`, `.nuxt`, `.output`, `out` (framework build outputs)
- `coverage`, `.cache`
- Plus any patterns from your `.gitignore` file
- Plus any directories classified as "exclude" by AI/user

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

### `/freya-devkit:code-graph update`

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

### `/freya-devkit:code-graph query <file>`

Show complete dependency information for a file.

**Output includes:**
- What the file exports
- What the file imports (dependencies)
- What files depend on this one (dependents)
- Category (if detectable)

**Example:**
```
File: src/lib/auth/validateToken.ts

Exports:
  - validateToken (function)
  - TokenPayload (type)

Dependencies (imports from):
  - jsonwebtoken (external)
  - ./config → src/lib/auth/config.ts

Dependents (imported by):
  - src/api/middleware/auth.ts
  - src/api/routes/users.ts
  - src/lib/auth/index.ts

Category: auth
```

### `/freya-devkit:code-graph impact <file>`

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

### `/freya-devkit:code-graph impact <file1> <file2> ...`

Analyze combined impact for multiple files.

**Example:**
```
/freya-devkit:code-graph impact src/lib/auth/validateToken.ts src/lib/db/connection.ts
```

Returns combined blast radius for all specified files.

### `/freya-devkit:code-graph dependents <file>`

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

### `/freya-devkit:code-graph dependencies <file>`

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

### `/freya-devkit:code-graph clear`

Delete the cached graph for this project.

**Use when:**
- Graph seems corrupted or out of sync
- Significant restructuring of the codebase
- Switching branches with different file structures

**Output:**
```
Cleared dependency graph cache for this project.
Run /freya-devkit:code-graph build to create a fresh graph.
```

### `/freya-devkit:code-graph help`

Display help information about the code-graph skill.

**Example usage:**
```
/freya-devkit:code-graph help
/freya-devkit:code-graph --help
/freya-devkit:code-graph -h
```

---

## Using with Other Skills

### With docs-manager

When running `/freya-devkit:docs-manager update`:
1. docs-manager checks if code-graph skill exists
2. If available, calls `/freya-devkit:code-graph impact <changed-files>`
3. Uses impact results to determine which docs need updating
4. Falls back to simple git diff if code-graph unavailable

### With spec-manager

When running `/freya-devkit:spec-manager update`:
1. spec-manager checks if code-graph skill exists
2. If available, calls `/freya-devkit:code-graph impact <changed-files>`
3. Includes dependent files in affected code analysis
4. Falls back to simple git diff if code-graph unavailable

---

## Script Usage

The underlying `graph_ops.py` script can be called directly:

```bash
# Build graph
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --build --dir /path/to/project

# Update graph
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --update --dir /path/to/project

# Query file
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --query src/lib/auth.ts

# Impact analysis
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --impact src/lib/auth.ts

# Dependents
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --dependents src/lib/auth.ts

# Dependencies
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --dependencies src/lib/auth.ts

# Clear cache
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --clear --dir /path/to/project

# Output formats
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --query src/lib/auth.ts --format json
python "${CLAUDE_PLUGIN_ROOT}/skills/code-graph/scripts/graph_ops.py" --query src/lib/auth.ts --format summary
```

**Output formats:**
- `--format json` (default): Machine-readable JSON
- `--format summary`: Human-readable summary

---

## Limitations

- **Dynamic imports**: May not catch dynamic `import()` or `require(variable)`
- **External packages**: Only tracks local file relationships, not npm/pip packages
- **Language support**: Currently TypeScript/JS, Python, Go
- **Monorepos**: Each subproject should have its own graph

---

## References

- `references/graph-schema.md` - Full JSON schema for the graph structure
