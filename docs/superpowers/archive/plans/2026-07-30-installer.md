# Installer Implementation Plan (Phase 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One command installs the whole freya-devkit suite onto Claude Code and GitHub Copilot from a checkout, with the `freya` launcher on `PATH`, and removes it again cleanly.

**Architecture:** The checkout *is* the canonical store. Installation is symlinking — no file rewriting — which is only possible because this phase first renames the skill directories to their installed names (`freya-*`). All install logic lives in one stdlib-Python module, `bin/installer.py`; `install.sh`, `install.ps1`, and `freya install` are thin bootstraps over it, so there is one implementation and it is unit-testable.

**Tech Stack:** Python 3 stdlib only (`argparse`, `pathlib`, `shutil`, `os`, `unittest`). POSIX `sh` and PowerShell bootstraps of ~20 lines each.

## Context

This is **Phase 3 of 6** ([`docs/design/portability/01-design.md`](../../../design/portability/01-design.md) §4, §11). Branch `feat/polyglot-portability` stays open through all six phases. Phase 1 shipped the launcher; Phase 2 made the skill layer agent-neutral and left every cross-reference reading `freya-<skill>`.

### Two findings that reshaped this phase (verified 2026-07-30)

**1. The Agent Skills spec requires `name` to match the parent directory.** From <https://agentskills.io/specification>: the `name` field *"Must match the parent directory name."* Claude Code's docs say the same from the other side: *"The directory name becomes the command you type."*

Design Decision 3 said the installer would apply the `freya-` prefix to both the directory and the `name:` field at install time. With symlinks that is impossible — `~/.claude/skills/freya-code-graph` → `<store>/skills/code-graph` yields a `SKILL.md` saying `name: code-graph` under a `freya-code-graph` parent, which violates the spec and fails `skills-ref validate`.

**Resolved (project owner, 2026-07-30): rename in the repo.** `skills/code-graph/` → `skills/freya-code-graph/`, with `name: freya-code-graph`. The installer then never rewrites anything. Phase 2 already made all 173 cross-references say `freya-<skill>`, so this makes the repo self-consistent rather than less so.

**2. `compatibility:` is a standard field, and the checker wrongly rejects it.** The spec lists `compatibility` (max 500 chars), `license`, `metadata`, and `allowed-tools` as optional standard fields. `01-design.md` §1 called `compatibility` "non-standard" and Phase 2 propagated that into `ALLOWED_FRONTMATTER = {"name", "description"}`. R5 therefore rejects four legitimate fields. Task 1 fixes it. (Deleting the two `compatibility:` lines in Phase 2 remains correct on its own merits — they listed Claude tool names — but the stated reason was wrong.)

### Where each agent reads skills (verified 2026-07-30)

| Agent | Personal-scope paths | What we do |
|---|---|---|
| Claude Code | `~/.claude/skills/` **only** — no cross-agent path appears in its docs | link here |
| GitHub Copilot | `~/.copilot/skills/` **and** `~/.agents/skills/` | link into `~/.agents/skills/` only — writing both risks double registration |

`~/.agents/skills/` is the cross-agent location the ecosystem converged on; this machine already uses the pattern (`~/.claude/skills/cmux-browser -> ../../.agents/skills/cmux-browser`).

**Dual-install hazard to surface, not solve:** Claude namespaces plugin skills `plugin-name:skill-name`, so a user with *both* the marketplace plugin and this personal install gets `/freya-devkit:freya-code-graph` **and** `/freya-code-graph` — two copies of all ten skills. `freya doctor` must warn (Task 6). The plugin name stays `freya-devkit` (owner's decision, 2026-07-30).

## Global Constraints

- **Python 3 stdlib only.** No third-party imports anywhere.
- **Shebang `#!/usr/bin/env python3`** on executable scripts. **Never invoke bare `python`** — in code, in docs, or in commands you run.
- **Tests colocated, `unittest`**, run as `python3 -m unittest`. Match `bin/test_freya_cli.py`.
- **One implementation.** Install logic lives only in `bin/installer.py`. `install.sh`, `install.ps1`, and `freya install` must not reimplement any of it — they locate a Python 3 and delegate.
- **Never destroy user data.** The installer may remove only symlinks that point into the store. A real directory, or a symlink pointing anywhere else, is an error the user must resolve — `--force` may replace a *foreign symlink*, never a real directory.
- **Idempotent.** Running the installer twice must be a no-op the second time and must exit 0.
- **Two names, one character apart:** `freya <command>` (space) is the CLI; `freya-<skill>` (hyphen) is a skill name. After Task 2 the *command* names in `bin/commands.json` are unchanged (`freya code-graph` still works) — only the *paths* they map to gain the prefix.
- **`skills/*/scripts/` may be modified in this phase** (Task 2's sibling paths, Task 6's `drift.py`) — unlike Phase 2, which was markdown-only.
- **Do not touch** `workflows/codebase-security-audit.js`, the four "Workflow tool" references, or the two `${CLAUDE_PLUGIN_ROOT}` audit lines — Phase 4b owns them.
- **`.claude-plugin/` stays as-is.** Plugin name remains `freya-devkit`.
- **Commit locally after each task. Do NOT push.** The user requires explicit permission for every push.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `bin/check_skill_conformance.py` | **Modify.** R5 → full standard field set; new R8 `name` must equal parent directory. |
| `skills/freya-*/` (10 dirs) | **Rename** from `skills/*`; `name:` updated to match. |
| `skills/freya-{behavior-graph,behavior-runner,status}/scripts/*.py`, `skills/freya-spec-manager/scripts/project_shape.py` | **Modify.** 9 sibling-path literals. |
| `bin/commands.json` | **Modify.** 15 path values gain the `freya-` prefix; keys unchanged. |
| `bin/installer.py` | **Create.** Discovery, link planning, apply, uninstall, launcher-on-PATH. |
| `bin/test_installer.py` | **Create.** Unit tests, temp-dir fixtures. |
| `install.sh`, `install.ps1` | **Create.** Bootstraps. |
| `bin/freya_cli.py` | **Modify.** Wire `freya install`/`uninstall`; extend `doctor`. |
| `skills/freya-spec-manager/scripts/drift.py` | **Modify.** Replace textual `../..` reach. |
| `README.md`, `CONTRIBUTING.md`, `docs/{skill-reference,conventions,patterns,architecture,philosophy}.md` | **Modify.** 47 slash refs + 1 `${CLAUDE_PLUGIN_ROOT}` + install instructions. |

---

### Task 1: Teach the checker the real spec

Two fixes, both guarding later tasks. R8 is what makes Task 2's rename verifiable.

**Files:**
- Modify: `bin/check_skill_conformance.py`
- Test: `bin/test_check_skill_conformance.py`

**Interfaces:**
- Consumes: the existing `check_file(path, rel, allowed)`, `scan(root, rules=None)`, `frontmatter_keys(lines)`.
- Produces: rule `R8`; a widened `ALLOWED_FRONTMATTER`. Task 2 depends on R8.

- [ ] **Step 1: Write the failing tests**

Add to `bin/test_check_skill_conformance.py`, inside `class RuleTest`:

```python
    def test_standard_optional_frontmatter_is_allowed(self):
        """license, metadata, compatibility and allowed-tools are in the spec."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(
                tmp,
                skill_md=(
                    "---\nname: demo\ndescription: d\nlicense: MIT\n"
                    "compatibility: Requires git\nallowed-tools: Read\nmetadata:\n  author: x\n---\n"
                ),
            )
            self.assertNotIn("R5", rules_hit(root))

    def test_unknown_frontmatter_key_is_still_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: demo\ndescription: d\ninvented: x\n---\n")
            self.assertIn("R5", rules_hit(root))
```

And a new class:

```python
class NameMatchesDirectoryTest(unittest.TestCase):
    """The Agent Skills spec requires `name` to equal the parent directory name."""

    def test_matching_name_is_accepted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: demo\ndescription: d\n---\n")
            self.assertNotIn("R8", rules_hit(root))

    def test_mismatched_name_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\nname: not-demo\ndescription: d\n---\n")
            self.assertIn("R8", rules_hit(root))

    def test_missing_name_is_flagged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, skill_md="---\ndescription: d\n---\n")
            self.assertIn("R8", rules_hit(root))

    def test_reference_file_is_not_checked_for_name(self):
        """Only SKILL.md carries the name contract; references/*.md must not trip R8."""
        with tempfile.TemporaryDirectory() as tmp:
            root = build_root(tmp, reference_md="Some notes.\n")
            self.assertNotIn("R8", rules_hit(root))
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd bin && python3 -m unittest test_check_skill_conformance -v`
Expected: FAIL — `test_standard_optional_frontmatter_is_allowed` (R5 fires on `license`), and the three `R8` tests fail because no rule `R8` exists.

- [ ] **Step 3: Implement**

In `bin/check_skill_conformance.py`, replace the `ALLOWED_FRONTMATTER` definition:

```python
#: The Agent Skills specification (https://agentskills.io/specification) defines
#: exactly these frontmatter keys. `name` and `description` are required; the rest
#: are optional. Anything else is a client-specific extension and hurts portability.
ALLOWED_FRONTMATTER = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)
```

Add `R8` to `RULES`:

```python
    "R8": "SKILL.md `name` must equal the parent directory name (Agent Skills spec)",
```

Add a helper beside `frontmatter_keys`:

```python
def frontmatter_name(lines):
    """Return the value of the top-level `name:` key, or None if absent.

    Strips one layer of YAML quoting: `name: "code-graph"` is as valid as the
    bare form, and some YAML formatters add the quotes on their own, so a
    quoted value must not read as a mismatch against the directory name.
    """
    if not lines or lines[0].strip() != "---":
        return None
    for line in lines[1:]:
        if line.strip() == "---":
            return None
        if line.startswith("name:"):
            value = line.split(":", 1)[1].strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
    return None
```

In `check_file`, after the frontmatter-key loop, add:

```python
    if path.name == "SKILL.md":
        declared = frontmatter_name(lines)
        expected = path.parent.name
        if declared != expected:
            violations.append((rel, 1, "R8", f"name: {declared!r} != directory {expected!r}"))
```

`check_file` needs the real `path` for `path.parent.name`; it already receives it.

- [ ] **Step 4: Run to verify they pass**

Run: `cd bin && python3 -m unittest test_check_skill_conformance -v`
Expected: PASS — 55 tests, `OK`, output pristine.

- [ ] **Step 5: Confirm the real tree**

Run: `python3 bin/check_skill_conformance.py; echo "exit=$?"`
Expected: `exit=0`. Every skill's `name:` already equals its directory today, so R8 starts green — and stays green only if Task 2 renames both together. That is the point.

- [ ] **Step 6: Mutation-check the new guards**

1. In `frontmatter_name`, change `line.startswith("name:")` to `line.startswith("nome:")`.
   Expected: FAIL on `test_matching_name_is_accepted`. **Restore.**
2. In `check_file`, change `if path.name == "SKILL.md":` to `if False:`.
   Expected: FAIL on `test_mismatched_name_is_flagged` and `test_missing_name_is_flagged`. **Restore.**
3. Remove `"license"` from `ALLOWED_FRONTMATTER`.
   Expected: FAIL on `test_standard_optional_frontmatter_is_allowed`. **Restore.**

Re-run after restoring all three: PASS, 55 tests.

- [ ] **Step 7: Commit**

```bash
git add bin/check_skill_conformance.py bin/test_check_skill_conformance.py
git commit -F - <<'EOF'
fix(conformance): align frontmatter rules with the Agent Skills spec

R5 allowed only `name` and `description`, rejecting `license`,
`compatibility`, `metadata` and `allowed-tools` — all standard optional
fields. The design called `compatibility` non-standard; it is not.

Adds R8: SKILL.md `name` must equal the parent directory name, which the
spec requires and which the Phase 3 rename depends on. It is green today
and stays green only if directories and `name:` fields move together.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 2: Rename the ten skills to their installed names

The prerequisite for a rewrite-free installer. Purely mechanical, and R8 plus the 17 suites verify it.

**Files:**
- Rename: all 10 `skills/<name>/` → `skills/freya-<name>/`
- Modify: the `name:` frontmatter in each of the 10 `SKILL.md`
- Modify: 9 sibling-path literals in 5 scripts
- Modify: `bin/commands.json` — 15 path values

**Interfaces:**
- Consumes: R8 from Task 1.
- Produces: a store whose directory names are the installed names. Tasks 3–5 depend on it.

**The renames** (`git mv` each, to preserve history):

| From | To |
|---|---|
| `skills/behavior-graph` | `skills/freya-behavior-graph` |
| `skills/behavior-runner` | `skills/freya-behavior-runner` |
| `skills/code-graph` | `skills/freya-code-graph` |
| `skills/codebase-security-resolver` | `skills/freya-codebase-security-resolver` |
| `skills/codebase-security-scan` | `skills/freya-codebase-security-scan` |
| `skills/dependency-vulnerability-check` | `skills/freya-dependency-vulnerability-check` |
| `skills/docs-manager` | `skills/freya-docs-manager` |
| `skills/spec-manager` | `skills/freya-spec-manager` |
| `skills/status` | `skills/freya-status` |
| `skills/wrap-up` | `skills/freya-wrap-up` |

`freya-codebase-security-resolver` is 34 characters — well inside the spec's 64-character limit. No name needs shortening.

**The 10 sibling-path literals.** Nine are a `Path(__file__).resolve().parents[2] / "<skill>" / …` reach across the `skills/` tree; the tenth (`drift.py`) uses `os.path.join` with a textual `../..`, which is why a `parents[2]` grep does not find it. Add the prefix to the quoted directory name only:

```
skills/freya-behavior-runner/scripts/run_behaviors.py:18   "spec-manager"    -> "freya-spec-manager"
skills/freya-behavior-runner/scripts/run_behaviors.py:19   "code-graph"      -> "freya-code-graph"
skills/freya-behavior-graph/scripts/behavior_graph.py:19   "spec-manager"    -> "freya-spec-manager"
skills/freya-behavior-graph/scripts/behavior_graph.py:24   "behavior-runner" -> "freya-behavior-runner"
skills/freya-behavior-graph/scripts/behavior_graph.py:25   "code-graph"      -> "freya-code-graph"
skills/freya-behavior-graph/scripts/behavior_graph.py:27   "behavior-runner" -> "freya-behavior-runner"
skills/freya-spec-manager/scripts/project_shape.py:21      "docs-manager"    -> "freya-docs-manager"
skills/freya-status/scripts/collect_status.py:17           "spec-manager"    -> "freya-spec-manager"
skills/freya-status/scripts/collect_status.py:18           "behavior-graph"  -> "freya-behavior-graph"
skills/freya-spec-manager/scripts/drift.py:38              "code-graph"      -> "freya-code-graph"
```

**Do not blanket-replace these strings.** A continuation-aware scan of every quoted skill name in `skills/*/scripts/*.py` found exactly these ten paths; every other occurrence is a *data* value and must not change:

- `"status"` as a spec/ADR frontmatter field — `frontmatter.py:47,68,435`, `adr.py:99,110,154`, `search_specs.py:76`, `verify_intent.py:168`, `collect_status.py:148`
- `'status'` as a `graph_ops.py` result key — `1082, 1117, 1240`
- `"code-graph"` as drift's *source label* — `drift.py:95`, asserted by `test_drift.py:108`

Change those ten and nothing else.

**`bin/commands.json`.** The **keys stay exactly as they are** — `freya code-graph` must keep working, and all 81 command sites in the skill markdown depend on it. Only the path values change:

```json
{
  "code-graph": "freya-code-graph/scripts/graph_ops.py",
  "behavior-graph": "freya-behavior-graph/scripts/behavior_graph.py",
  "behavior-runner": "freya-behavior-runner/scripts/run_behaviors.py",
  "status": "freya-status/scripts/collect_status.py",
  "detect-project": "freya-docs-manager/scripts/detect_project.py",
  "spec": "freya-spec-manager/scripts/search_specs.py",
  "adapters": "freya-spec-manager/scripts/adapters.py",
  "adr": "freya-spec-manager/scripts/adr.py",
  "contradictions": "freya-spec-manager/scripts/contradictions.py",
  "drift": "freya-spec-manager/scripts/drift.py",
  "intent": "freya-spec-manager/scripts/intent.py",
  "principles": "freya-spec-manager/scripts/principles.py",
  "project-shape": "freya-spec-manager/scripts/project_shape.py",
  "verify-intent": "freya-spec-manager/scripts/verify_intent.py",
  "verify-links": "freya-spec-manager/scripts/verify_links.py"
}
```

- [ ] **Step 1: Rename the directories**

```bash
for s in behavior-graph behavior-runner code-graph codebase-security-resolver \
         codebase-security-scan dependency-vulnerability-check docs-manager \
         spec-manager status wrap-up; do
  git mv "skills/$s" "skills/freya-$s"
done
git status --short | head -20
```

- [ ] **Step 2: Update the ten `name:` fields**

In each `skills/freya-*/SKILL.md`, change the frontmatter `name:` to match its new directory. Example:

```
skills/freya-code-graph/SKILL.md
-name: code-graph
+name: freya-code-graph
```

Verify all ten at once:

```bash
for d in skills/*/; do
  n=$(basename "$d")
  fm=$(awk '/^---$/{c++; next} c==1 && /^name:/{print $2; exit}' "$d/SKILL.md")
  [ "$n" = "$fm" ] && echo "ok   $n" || echo "MISMATCH $n != $fm"
done
```
Expected: `ok` for all ten.

- [ ] **Step 3: Update the 9 sibling paths and the manifest**

Apply the table above, then write `bin/commands.json` exactly as given.

- [ ] **Step 4: Verify — the engine still resolves siblings**

The 17 suites are the real test here: `behavior_graph`, `run_behaviors`, `collect_status` and `project_shape` all import or exec across the tree, so a missed path fails loudly.

```bash
fail=0
for t in bin/test_*.py skills/*/scripts/test_*.py; do
  d=$(dirname "$t"); m=$(basename "$t" .py)
  ( cd "$d" && python3 -m unittest "$m" -q ) >/dev/null 2>&1 && echo "ok    $t" || { echo "FAIL  $t"; fail=1; }
done
exit $fail
```
Expected: `ok` for all 17.

- [ ] **Step 5: Verify — conformance, launcher, and no stale references**

```bash
python3 bin/check_skill_conformance.py; echo "exit=$?"
```
Expected: `exit=0` — R8 confirms all ten directory/`name:` pairs agree.

```bash
./bin/freya doctor; echo "exit=$?"
for c in drift behavior-graph spec contradictions code-graph principles adr \
         verify-intent status verify-links behavior-runner project-shape intent adapters; do
  printf '%-16s ' "$c"; ./bin/freya "$c" --help >/dev/null 2>&1 && echo ok || echo FAILED
done
```
Expected: `exit=0`, and `ok` for all 14 — the command *names* are unchanged, so every markdown invocation still resolves.

```bash
python3 - <<'EOF'
import re, pathlib
NAMES = ("behavior-graph|behavior-runner|code-graph|docs-manager|spec-manager")
pat = re.compile(r'''(?<!freya-)['"](%s)['"]''' % NAMES)
for f in sorted(pathlib.Path("skills").glob("*/scripts/*.py")):
    if f.name.startswith("test_"): continue
    for i, line in enumerate(f.read_text().splitlines(), 1):
        w = line
        if pat.search(line) and any(k in w for k in ("parents[", "..", "join(")):
            print(f"{f}:{i}: {line.strip()}")
EOF
```
Expected: no output — all ten sibling reaches now carry the prefix. This checks both
the `parents[2]` and the `os.path.join`/`..` styles, so it cannot miss `drift.py`.

- [ ] **Step 6: Commit**

```bash
git add -A skills/ bin/commands.json
git commit -F - <<'EOF'
refactor(skills): rename skill directories to their installed names

The Agent Skills spec requires a skill's `name` to equal its parent directory
name, so the `freya-` prefix cannot be applied at install time without
rewriting every SKILL.md. Renaming here instead means the installer is pure
symlinking and the installed tree is spec-valid.

Renames all ten directories and their `name:` fields, plus the nine sibling
path literals the engine uses to reach across the tree and the fifteen paths
in bin/commands.json. Command *names* are unchanged: `freya code-graph` still
works, so all 81 invocation sites in the skill markdown are unaffected.

Phase 2 already wrote every cross-reference as freya-<skill>, so this makes
the repo self-consistent.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 3: Installer — discovery and link planning

Pure functions: work out *what should happen* without touching the filesystem. Split from Task 4 so the safety classification — the part that must never delete user data — is tested in isolation.

**Files:**
- Create: `bin/installer.py`
- Test: `bin/test_installer.py`

**Interfaces:**
- Produces, for Task 4 and the entry points:
  - `AGENT_TARGETS: dict[str, Path]` — agent name → personal skills dir
  - `store_root() -> Path` — the checkout, via `Path(__file__).resolve().parents[1]`
  - `discover_skills(store: Path) -> list[Path]` — sorted `skills/freya-*` dirs containing a `SKILL.md`
  - `LinkPlan` — namedtuple `(target: Path, source: Path, status: str)` where status is one of `"create"`, `"ok"`, `"foreign"`, `"occupied"`
  - `classify(target: Path, source: Path) -> str` — the safety decision for one link
  - `plan_agent(store: Path, agent: str) -> list[LinkPlan]`
  - `blockers(plans: list[LinkPlan], force: bool) -> list[LinkPlan]` — entries that stop the install

Status meanings, which drive everything downstream:

| status | Meaning | Action in Task 4 |
|---|---|---|
| `create` | nothing at the target | make the link |
| `ok` | already a symlink into this store | leave it (idempotent) |
| `foreign` | a symlink pointing elsewhere | replace only with `--force` |
| `occupied` | a real file or directory | **never** touched; always a blocker |

- [ ] **Step 1: Write the failing tests**

Create `bin/test_installer.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the suite installer."""

import os
import tempfile
import unittest
from pathlib import Path

import installer


def make_store(tmp, skills=("freya-code-graph", "freya-status")):
    """Materialize a store with the given skill directories."""
    store = Path(tmp) / "store"
    for name in skills:
        d = store / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n", encoding="utf-8")
    (store / "bin").mkdir(parents=True, exist_ok=True)
    return store


class DiscoverTest(unittest.TestCase):
    def test_finds_prefixed_skills_sorted(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            found = [p.name for p in installer.discover_skills(store)]
            self.assertEqual(found, ["freya-code-graph", "freya-status"])

    def test_ignores_directories_without_skill_md(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "skills" / "freya-empty").mkdir()
            found = [p.name for p in installer.discover_skills(store)]
            self.assertNotIn("freya-empty", found)

    def test_ignores_unprefixed_directories(self):
        """Only freya-* ships; anything else in skills/ is not ours to install."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            other = store / "skills" / "somebody-elses"
            other.mkdir()
            (other / "SKILL.md").write_text("---\nname: somebody-elses\ndescription: d\n---\n")
            found = [p.name for p in installer.discover_skills(store)]
            self.assertNotIn("somebody-elses", found)

    def test_missing_skills_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(installer.discover_skills(Path(tmp) / "nope"), [])


class ClassifyTest(unittest.TestCase):
    def test_absent_target_is_create(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            self.assertEqual(installer.classify(Path(tmp) / "missing", source), "create")

    def test_link_into_store_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            target = Path(tmp) / "link"
            target.symlink_to(source)
            self.assertEqual(installer.classify(target, source), "ok")

    def test_link_elsewhere_is_foreign(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            other = Path(tmp) / "other"; other.mkdir()
            target = Path(tmp) / "link"
            target.symlink_to(other)
            self.assertEqual(installer.classify(target, source), "foreign")

    def test_real_directory_is_occupied(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            target = Path(tmp) / "real"; target.mkdir()
            self.assertEqual(installer.classify(target, source), "occupied")

    def test_real_file_is_occupied(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            target = Path(tmp) / "real"; target.write_text("x")
            self.assertEqual(installer.classify(target, source), "occupied")

    def test_broken_symlink_into_store_is_still_ok(self):
        """A dangling link we own is ours to refresh, not a blocker."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"
            target = Path(tmp) / "link"
            target.symlink_to(source)
            self.assertEqual(installer.classify(target, source), "ok")


class PlanTest(unittest.TestCase):
    def test_plan_targets_the_agent_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            self.assertEqual([p.target.parent for p in plans], [target_dir, target_dir])
            self.assertEqual([p.target.name for p in plans],
                             ["freya-code-graph", "freya-status"])
            self.assertTrue(all(p.status == "create" for p in plans))

    def test_plan_sources_point_into_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            plans = installer.plan_agent(store, "claude", target_dir=Path(tmp) / "agentdir")
            for p in plans:
                self.assertEqual(p.source.parent, store / "skills")

    def test_unknown_agent_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                installer.plan_agent(make_store(tmp), "nosuchagent")

    def test_known_agents_are_claude_and_copilot(self):
        self.assertEqual(sorted(installer.AGENT_TARGETS), ["claude", "copilot"])

    def test_copilot_targets_the_cross_agent_directory(self):
        """Copilot reads ~/.agents/skills; writing ~/.copilot/skills too would double-register."""
        self.assertEqual(installer.AGENT_TARGETS["copilot"].parts[-2:], (".agents", "skills"))

    def test_claude_targets_its_own_directory(self):
        self.assertEqual(installer.AGENT_TARGETS["claude"].parts[-2:], (".claude", "skills"))


class BlockerTest(unittest.TestCase):
    def _plans(self, statuses):
        return [installer.LinkPlan(Path(f"/t/{s}"), Path("/s"), s) for s in statuses]

    def test_occupied_always_blocks(self):
        found = installer.blockers(self._plans(["occupied"]), force=True)
        self.assertEqual([p.status for p in found], ["occupied"])

    def test_foreign_blocks_without_force(self):
        self.assertEqual(len(installer.blockers(self._plans(["foreign"]), force=False)), 1)

    def test_foreign_clears_with_force(self):
        self.assertEqual(installer.blockers(self._plans(["foreign"]), force=True), [])

    def test_create_and_ok_never_block(self):
        self.assertEqual(installer.blockers(self._plans(["create", "ok"]), force=False), [])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd bin && python3 -m unittest test_installer -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'installer'`

- [ ] **Step 3: Implement**

Create `bin/installer.py`:

```python
#!/usr/bin/env python3
"""Install the freya-devkit suite for one or more coding agents.

The checkout is the canonical store: installing means symlinking each skill
directory into the agent's personal skills directory. Nothing is rewritten,
which is only possible because the store's directory names are already the
installed names (`freya-*`) — the Agent Skills spec requires a skill's `name`
to equal its parent directory.
"""

from __future__ import annotations

import os
from collections import namedtuple
from pathlib import Path

#: Only directories with this prefix are ours to install.
SKILL_PREFIX = "freya-"

#: Where each agent reads personal-scope skills. Verified 2026-07-30:
#: - Claude Code reads ~/.claude/skills only; its docs list no cross-agent path.
#: - Copilot reads both ~/.copilot/skills and ~/.agents/skills, so we use the
#:   shared location and skip ~/.copilot/skills to avoid registering twice.
AGENT_TARGETS = {
    "claude": Path.home() / ".claude" / "skills",
    "copilot": Path.home() / ".agents" / "skills",
}

#: One intended link. `status` is create | ok | foreign | occupied.
LinkPlan = namedtuple("LinkPlan", "target source status")


def store_root():
    """The canonical store — the checkout this file lives in."""
    return Path(__file__).resolve().parents[1]


def discover_skills(store):
    """Return the sorted freya-* skill directories in the store."""
    skills_dir = store / "skills"
    if not skills_dir.is_dir():
        return []
    return sorted(
        path
        for path in skills_dir.iterdir()
        if path.is_dir() and path.name.startswith(SKILL_PREFIX) and (path / "SKILL.md").is_file()
    )


def classify(target, source):
    """Decide what a single target path means for us.

    Never reports a real file or directory as anything but `occupied`: the
    installer must not be able to destroy something the user created.
    """
    if target.is_symlink():
        try:
            points_at = Path(os.readlink(target))
        except OSError:
            return "foreign"
        if not points_at.is_absolute():
            points_at = (target.parent / points_at)
        return "ok" if os.path.normpath(points_at) == os.path.normpath(source) else "foreign"
    if target.exists():
        return "occupied"
    return "create"


def plan_agent(store, agent, target_dir=None):
    """Return the LinkPlan list for installing every skill for one agent."""
    if target_dir is None:
        try:
            target_dir = AGENT_TARGETS[agent]
        except KeyError:
            raise ValueError(f"unknown agent: {agent!r} (known: {', '.join(sorted(AGENT_TARGETS))})")
    plans = []
    for source in discover_skills(store):
        target = target_dir / source.name
        plans.append(LinkPlan(target, source, classify(target, source)))
    return plans


def blockers(plans, force):
    """Entries that must stop the install.

    `occupied` always blocks — we will not remove something we did not create.
    `foreign` blocks unless --force, which permits replacing a symlink only.
    """
    return [p for p in plans if p.status == "occupied" or (p.status == "foreign" and not force)]
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd bin && python3 -m unittest test_installer -v`
Expected: PASS — 20 tests, `OK`

- [ ] **Step 5: Mutation-check the safety classification**

This is the code that must never delete user data.

1. In `classify`, change `if target.exists(): return "occupied"` to `return "create"`.
   Expected: FAIL on `test_real_directory_is_occupied` and `test_real_file_is_occupied`. **Restore.**
2. In `blockers`, drop the `p.status == "occupied" or` clause.
   Expected: FAIL on `test_occupied_always_blocks`. **Restore.**
3. In `classify`, make the symlink comparison always return `"ok"`.
   Expected: FAIL on `test_link_elsewhere_is_foreign`. **Restore.**

Re-run after restoring: PASS, 20 tests.

- [ ] **Step 6: Commit**

```bash
git add bin/installer.py bin/test_installer.py
git commit -F - <<'EOF'
feat(installer): skill discovery and link planning

Pure planning half of the installer: find the store's freya-* skills, and
classify each intended link target as create / ok / foreign / occupied.

The classification is the safety boundary. A real file or directory is always
`occupied` and always blocks — --force may replace a foreign symlink, never
something the user created. Mutation-tested.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 4: Installer — apply, uninstall, and the launcher on PATH

**Files:**
- Modify: `bin/installer.py`
- Modify: `bin/test_installer.py`

**Interfaces:**
- Consumes: everything from Task 3.
- Produces:
  - `apply_plan(plans, *, copy=False, force=False, dry_run=False) -> list[tuple[LinkPlan, str]]` — each result action is `"linked" | "copied" | "skipped" | "replaced"`
  - `uninstall_agent(store, agent, target_dir=None) -> list[Path]` — removed targets
  - `launcher_target() -> Path` — `~/.local/bin/freya`
  - `link_launcher(store, *, bin_dir=None, force=False, dry_run=False) -> str`
  - `path_contains(directory) -> bool`

- [ ] **Step 1: Write the failing tests**

Append to `bin/test_installer.py`:

```python
class ApplyTest(unittest.TestCase):
    def test_creates_symlinks_that_resolve_into_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            results = installer.apply_plan(plans)
            self.assertEqual([a for _, a in results], ["linked", "linked"])
            link = target_dir / "freya-code-graph"
            self.assertTrue(link.is_symlink())
            self.assertTrue((link / "SKILL.md").is_file())
            self.assertEqual(link.resolve(), (store / "skills" / "freya-code-graph").resolve())

    def test_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=target_dir))
            again = installer.apply_plan(installer.plan_agent(store, "claude", target_dir=target_dir))
            self.assertEqual([a for _, a in again], ["skipped", "skipped"])

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            installer.apply_plan(plans, dry_run=True)
            self.assertFalse(target_dir.exists())

    def test_copy_mode_materializes_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            results = installer.apply_plan(plans, copy=True)
            self.assertEqual([a for _, a in results], ["copied", "copied"])
            copied = target_dir / "freya-code-graph"
            self.assertFalse(copied.is_symlink())
            self.assertTrue((copied / "SKILL.md").is_file())

    def test_refuses_to_touch_a_real_directory_even_with_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            occupied = target_dir / "freya-code-graph"
            occupied.mkdir(parents=True)
            (occupied / "precious.txt").write_text("do not delete", encoding="utf-8")
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            with self.assertRaises(RuntimeError):
                installer.apply_plan(plans, force=True)
            self.assertEqual((occupied / "precious.txt").read_text(encoding="utf-8"),
                             "do not delete")

    def test_force_replaces_a_foreign_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            target_dir.mkdir()
            elsewhere = Path(tmp) / "elsewhere"; elsewhere.mkdir()
            (target_dir / "freya-code-graph").symlink_to(elsewhere)
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            results = installer.apply_plan(plans, force=True)
            self.assertIn("replaced", [a for _, a in results])
            self.assertEqual((target_dir / "freya-code-graph").resolve(),
                             (store / "skills" / "freya-code-graph").resolve())

    def test_foreign_symlink_without_force_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            target_dir.mkdir()
            elsewhere = Path(tmp) / "elsewhere"; elsewhere.mkdir()
            (target_dir / "freya-code-graph").symlink_to(elsewhere)
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            with self.assertRaises(RuntimeError):
                installer.apply_plan(plans)


class UninstallTest(unittest.TestCase):
    def test_removes_only_links_into_this_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=target_dir))
            elsewhere = Path(tmp) / "elsewhere"; elsewhere.mkdir()
            (target_dir / "someone-else").symlink_to(elsewhere)
            keep = target_dir / "freya-not-ours"; keep.mkdir()

            removed = installer.uninstall_agent(store, "claude", target_dir=target_dir)

            self.assertEqual(sorted(p.name for p in removed),
                             ["freya-code-graph", "freya-status"])
            self.assertTrue((target_dir / "someone-else").is_symlink())
            self.assertTrue(keep.is_dir())

    def test_uninstall_is_safe_when_nothing_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            self.assertEqual(installer.uninstall_agent(store, "claude",
                                                       target_dir=Path(tmp) / "nope"), [])


class LauncherTest(unittest.TestCase):
    def test_links_freya_into_the_bin_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            action = installer.link_launcher(store, bin_dir=bindir)
            self.assertEqual(action, "linked")
            self.assertEqual((bindir / "freya").resolve(), (store / "bin" / "freya").resolve())

    def test_launcher_link_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            installer.link_launcher(store, bin_dir=bindir)
            self.assertEqual(installer.link_launcher(store, bin_dir=bindir), "skipped")

    def test_path_contains_detects_membership(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp) / "somebin"
            old = os.environ.get("PATH", "")
            try:
                os.environ["PATH"] = f"{old}{os.pathsep}{d}"
                self.assertTrue(installer.path_contains(d))
                self.assertFalse(installer.path_contains(Path(tmp) / "absent"))
            finally:
                os.environ["PATH"] = old
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd bin && python3 -m unittest test_installer -v`
Expected: FAIL — `AttributeError: module 'installer' has no attribute 'apply_plan'`

- [ ] **Step 3: Implement**

Append to `bin/installer.py` (and add `import shutil` at the top):

```python
def apply_plan(plans, *, copy=False, force=False, dry_run=False):
    """Execute a link plan. Returns [(plan, action)] where action is
    linked | copied | replaced | skipped.

    Raises RuntimeError before changing anything if any entry blocks, so a
    partial install cannot happen.
    """
    stopped = blockers(plans, force)
    if stopped:
        detail = "\n".join(f"  {p.target} ({p.status})" for p in stopped)
        raise RuntimeError(
            "cannot install — these targets are in the way:\n" + detail
            + "\n\nA real file or directory is never removed. Move it aside, or "
              "re-run with --force to replace foreign symlinks."
        )

    results = []
    for plan in plans:
        if plan.status == "ok":
            results.append((plan, "skipped"))
            continue
        if dry_run:
            results.append((plan, "copied" if copy else "linked"))
            continue
        plan.target.parent.mkdir(parents=True, exist_ok=True)
        replaced = plan.status == "foreign"
        if replaced:
            plan.target.unlink()
        if copy:
            shutil.copytree(plan.source, plan.target)
            results.append((plan, "copied"))
        else:
            plan.target.symlink_to(plan.source, target_is_directory=True)
            results.append((plan, "replaced" if replaced else "linked"))
    return results


def uninstall_agent(store, agent, target_dir=None):
    """Remove only the symlinks that point into this store. Returns them."""
    if target_dir is None:
        try:
            target_dir = AGENT_TARGETS[agent]
        except KeyError:
            raise ValueError(f"unknown agent: {agent!r}")
    if not target_dir.is_dir():
        return []
    skills_dir = (store / "skills").resolve()
    removed = []
    for entry in sorted(target_dir.iterdir()):
        if not entry.is_symlink():
            continue
        try:
            points_at = Path(os.path.normpath(entry.parent / os.readlink(entry)))
            # Resolve the *parent* before comparing: the link target itself may be
            # dangling, and on macOS a temp/symlinked prefix (/var -> /private/var)
            # otherwise makes a link we own look foreign, so uninstall silently
            # removes nothing.
            owner = points_at.parent.resolve()
        except OSError:
            continue
        if owner == skills_dir:
            entry.unlink()
            removed.append(entry)
    return removed


def launcher_target():
    """Where the `freya` launcher goes on PATH."""
    return Path.home() / ".local" / "bin" / "freya"


def path_contains(directory):
    """Is `directory` on PATH?"""
    wanted = os.path.normpath(str(directory))
    return any(
        os.path.normpath(part) == wanted
        for part in os.environ.get("PATH", "").split(os.pathsep)
        if part
    )


def link_launcher(store, *, bin_dir=None, force=False, dry_run=False):
    """Put bin/freya on PATH. Returns linked | replaced | skipped."""
    source = store / "bin" / "freya"
    target = (bin_dir / "freya") if bin_dir is not None else launcher_target()
    status = classify(target, source)
    if status == "occupied" or (status == "foreign" and not force):
        raise RuntimeError(
            f"cannot place the launcher — {target} already exists ({status}). "
            "Move it aside, or re-run with --force to replace a foreign symlink."
        )
    if status == "ok":
        return "skipped"
    if dry_run:
        return "linked"
    target.parent.mkdir(parents=True, exist_ok=True)
    if status == "foreign":
        target.unlink()
    target.symlink_to(source)
    return "replaced" if status == "foreign" else "linked"
```

- [ ] **Step 4: Run to verify they pass**

Run: `cd bin && python3 -m unittest test_installer -v`
Expected: PASS — 32 tests, `OK`

- [ ] **Step 5: Mutation-check the destructive paths**

1. In `apply_plan`, replace `stopped = blockers(plans, force)` with `stopped = []`.
   Expected: FAIL on `test_foreign_symlink_without_force_raises`. **Restore.**
   (After Task 5 this mutation also fails `test_blocked_install_exits_two_and_explains`, but that test does not exist yet at this point in the plan.)
2. In `uninstall_agent`, change `if owner == skills_dir:` to `if True:`.
   Expected: FAIL on `test_removes_only_links_into_this_store`. **Restore.**

> Do **not** expect a failure from removing `uninstall_agent`'s `if not entry.is_symlink(): continue`. That check is a fast path, not a guard: without it `os.readlink` raises `OSError` on a real directory and the `except OSError: continue` below catches it, so behaviour is unchanged and the suite still passes. Verified 2026-07-30. The protection that matters — a real `freya-*` directory in the agent directory surviving uninstall — is asserted directly by `test_removes_only_links_into_this_store`'s `keep` case, and mutation 2 above proves the ownership check is load-bearing.

Re-run after restoring: PASS, 32 tests.

- [ ] **Step 6: Commit**

```bash
git add bin/installer.py bin/test_installer.py
git commit -F - <<'EOF'
feat(installer): apply, uninstall, and launcher placement

apply_plan refuses the whole install if any target blocks, so a partial
install cannot happen; supports symlink and --copy modes and is idempotent.
uninstall_agent removes only symlinks pointing into this store, leaving other
skills and any real directory untouched. link_launcher puts bin/freya on PATH
under the same safety rules.

All three destructive paths are mutation-tested.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 5: Entry points — `install.sh`, `install.ps1`, `freya install`

Three ways in, one implementation. The shell scripts exist only to solve the bootstrap problem: before installation, `freya` is not on `PATH`.

**Files:**
- Create: `install.sh` (mode 755), `install.ps1`
- Modify: `bin/installer.py` — add `main(argv)`
- Modify: `bin/freya_cli.py` — route `install` and `uninstall`
- Modify: `bin/test_installer.py`, `bin/test_freya_cli.py`

**Interfaces:**
- Consumes: Tasks 3 and 4.
- Produces: `installer.main(argv=None) -> int`; `freya install|uninstall` routed from `freya_cli.main`.

CLI surface:

```
install.sh [--agent claude|copilot]... [--copy] [--force] [--dry-run] [--uninstall]
```
`--agent` is repeatable; with none given, install for every agent whose directory already exists, and if none exists, report that and exit 1 rather than guessing.

- [ ] **Step 1: Write the failing tests**

Append to `bin/test_installer.py`:

```python
class MainTest(unittest.TestCase):
    def test_dry_run_reports_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            code, out, _ = run_main([
                "--agent", "claude", "--dry-run",
                "--store", str(store), "--target-dir", str(target_dir),
                "--bin-dir", str(Path(tmp) / "localbin"),
            ])
            self.assertEqual(code, 0)
            self.assertIn("freya-code-graph", out)
            self.assertFalse(target_dir.exists())

    def test_install_then_uninstall_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            common = ["--agent", "claude", "--store", str(store),
                      "--target-dir", str(target_dir), "--bin-dir", str(Path(tmp) / "localbin")]
            self.assertEqual(run_main(common)[0], 0)
            self.assertTrue((target_dir / "freya-code-graph").is_symlink())
            self.assertEqual(run_main(common + ["--uninstall"])[0], 0)
            self.assertFalse((target_dir / "freya-code-graph").exists())

    def test_blocked_install_exits_two_and_explains(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            (target_dir / "freya-code-graph").mkdir(parents=True)
            code, _, err = run_main([
                "--agent", "claude", "--store", str(store),
                "--target-dir", str(target_dir), "--bin-dir", str(Path(tmp) / "localbin"),
            ])
            self.assertEqual(code, 2)
            self.assertIn("occupied", err)

    def test_unknown_agent_exits_two(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, err = run_main(["--agent", "nosuch", "--store", str(make_store(tmp))])
            self.assertEqual(code, 2)
            self.assertIn("unknown agent", err)
```

Add the capture helper near the top of the file (same shape as the conformance suite's):

```python
import contextlib
import io


def run_main(argv):
    """Call installer.main with output captured, so the suite stays quiet."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = installer.main(argv)
    return code, out.getvalue(), err.getvalue()
```

And in `bin/test_freya_cli.py`:

```python
    def test_install_is_routed_to_the_installer(self):
        with mock.patch("installer.main", return_value=0) as installer_main:
            code = freya_cli.main(["install", "--agent", "claude"])
        self.assertEqual(code, 0)
        installer_main.assert_called_once_with(["--agent", "claude"])

    def test_uninstall_is_routed_to_the_installer(self):
        with mock.patch("installer.main", return_value=0) as installer_main:
            freya_cli.main(["uninstall"])
        installer_main.assert_called_once_with(["--uninstall"])
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd bin && python3 -m unittest test_installer test_freya_cli -v`
Expected: FAIL — no `installer.main`, and `freya install` still exits 2 as an unknown command.

- [ ] **Step 3: Implement `installer.main`**

Append to `bin/installer.py`:

```python
def default_agents():
    """Agents whose skills directory already exists — what to install without --agent."""
    return sorted(name for name, path in AGENT_TARGETS.items() if path.parent.is_dir())


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="freya install",
        description="Install the freya-devkit suite for one or more coding agents.",
    )
    parser.add_argument("--agent", action="append", metavar="NAME",
                        help=f"repeatable; one of: {', '.join(sorted(AGENT_TARGETS))}")
    parser.add_argument("--copy", action="store_true",
                        help="copy instead of symlinking (Windows, or committed skills)")
    parser.add_argument("--force", action="store_true",
                        help="replace foreign symlinks (never a real file or directory)")
    parser.add_argument("--dry-run", action="store_true", help="print the plan, change nothing")
    parser.add_argument("--uninstall", action="store_true",
                        help="remove links pointing into this store")
    parser.add_argument("--store", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--target-dir", type=Path, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--bin-dir", type=Path, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    store = args.store if args.store is not None else store_root()
    agents = args.agent or default_agents()
    if not agents:
        print("no agent directory found — pass --agent "
              f"({', '.join(sorted(AGENT_TARGETS))})", file=sys.stderr)
        return 1

    unknown = [a for a in agents if a not in AGENT_TARGETS]
    if unknown:
        print(f"unknown agent: {', '.join(unknown)} "
              f"(known: {', '.join(sorted(AGENT_TARGETS))})", file=sys.stderr)
        return 2

    try:
        if args.uninstall:
            for agent in agents:
                removed = uninstall_agent(store, agent, target_dir=args.target_dir)
                print(f"{agent}: removed {len(removed)} link(s)")
                for path in removed:
                    print(f"  - {path.name}")
            return 0

        for agent in agents:
            plans = plan_agent(store, agent, target_dir=args.target_dir)
            if not plans:
                print(f"{agent}: no skills found in {store / 'skills'}", file=sys.stderr)
                return 1
            for plan, action in apply_plan(plans, copy=args.copy, force=args.force,
                                           dry_run=args.dry_run):
                print(f"{agent}: {action:<8} {plan.target.name}")

        action = link_launcher(store, bin_dir=args.bin_dir, force=args.force,
                               dry_run=args.dry_run)
        target = (args.bin_dir / "freya") if args.bin_dir else launcher_target()
        print(f"launcher: {action:<8} {target}")
        if not args.dry_run and not path_contains(target.parent):
            print(f"\nNote: {target.parent} is not on PATH. Add it:\n"
                  f'  export PATH="{target.parent}:$PATH"')
    except (RuntimeError, ValueError, OSError) as exc:
        print(f"install failed: {exc}", file=sys.stderr)
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Add `import argparse` and `import sys` at the top.

- [ ] **Step 4: Route `install` / `uninstall` from the launcher**

In `bin/freya_cli.py`, inside `main()`, before the manifest lookup:

```python
    if command in ("install", "uninstall"):
        import installer

        passthrough = list(args)
        if command == "uninstall":
            passthrough.append("--uninstall")
        return installer.main(passthrough)
```

The import is local so `freya <command>` for ordinary commands never pays for it.

- [ ] **Step 5: Write the bootstraps**

Create `install.sh` (then `chmod 755 install.sh`):

```sh
#!/bin/sh
# Bootstrap for the freya-devkit installer.
#
# All logic lives in bin/installer.py — this only finds a Python 3 and
# delegates, because before installation `freya` is not on PATH.
set -eu

here=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)

for py in python3 python; do
    if command -v "$py" >/dev/null 2>&1 && "$py" -c 'import sys; sys.exit(sys.version_info[0] < 3)'; then
        exec "$py" "$here/bin/installer.py" "$@"
    fi
done

echo "install.sh: no Python 3 found on PATH." >&2
exit 1
```

Create `install.ps1`:

```powershell
# Bootstrap for the freya-devkit installer on Windows.
#
# All logic lives in bin/installer.py — this only finds a Python 3 and
# delegates. Symlinks on Windows need Developer Mode or an elevated shell;
# pass --copy if link creation is refused.
$ErrorActionPreference = 'Stop'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

foreach ($py in @('python3', 'python', 'py')) {
    $cmd = Get-Command $py -ErrorAction SilentlyContinue
    if ($cmd) {
        & $cmd.Source (Join-Path $here 'bin/installer.py') @args
        exit $LASTEXITCODE
    }
}

Write-Error 'install.ps1: no Python 3 found on PATH.'
exit 1
```

> `install.ps1` is **untested** — this phase is developed on macOS. Design §10 already lists Windows as needing a real test; Phase 6 owns it. It is deliberately thin so that what is untested is only interpreter discovery.

- [ ] **Step 6: Run the tests**

Run: `cd bin && python3 -m unittest test_installer test_freya_cli -v`
Expected: PASS — 36 installer tests and 34 launcher tests, `OK`

- [ ] **Step 7: Verify the bootstrap end to end, without touching your real config**

```bash
./install.sh --agent claude --dry-run --target-dir /tmp/freya-probe --bin-dir /tmp/freya-probe-bin
echo "exit=$?"
ls /tmp/freya-probe 2>/dev/null && echo "UNEXPECTED: dry run created files" || echo "dry run touched nothing ✓"
```
Expected: ten `linked freya-*` lines plus a `launcher:` line, `exit=0`, and no files created.

- [ ] **Step 8: Commit**

```bash
chmod 755 install.sh
git add install.sh install.ps1 bin/installer.py bin/freya_cli.py bin/test_installer.py bin/test_freya_cli.py
git commit -F - <<'EOF'
feat(installer): install.sh, install.ps1 and `freya install`

Three entry points over one implementation. The shell bootstraps exist only
because `freya` is not on PATH until after installation; each is ~20 lines of
interpreter discovery that then delegates to bin/installer.py.

--agent is repeatable and defaults to whichever agent directories exist.
install.ps1 is untested on Windows and deliberately thin; Phase 6 owns it.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 6: `freya doctor` reports the install, and `drift.py` stops guessing

**Files:**
- Modify: `bin/freya_cli.py` — extend `doctor_checks()`
- Modify: `bin/test_freya_cli.py`
- Modify: `skills/freya-spec-manager/scripts/drift.py` (the directory name was already fixed in Task 2; this is the `abspath` → `.resolve()` change only)

**Interfaces:**
- Consumes: `installer.AGENT_TARGETS`, `installer.plan_agent`, `installer.path_contains`.
- Produces: two new `doctor` checks.

- [ ] **Step 1: Write the failing tests**

Add to `bin/test_freya_cli.py`:

```python
    def test_doctor_reports_agent_link_status(self):
        labels = [label for label, _, _ in freya_cli.doctor_checks()]
        self.assertIn("agents", labels)

    def test_doctor_warns_when_the_claude_plugin_is_also_installed(self):
        """Plugin + personal install means every skill is registered twice."""
        labels = [label for label, _, _ in freya_cli.doctor_checks()]
        self.assertIn("duplicate install", labels)
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: FAIL — neither label is present.

- [ ] **Step 3: Implement the checks**

In `bin/freya_cli.py`, inside `doctor_checks()`, after the existing checks:

```python
    import installer

    linked = []
    for agent in sorted(installer.AGENT_TARGETS):
        try:
            plans = installer.plan_agent(root, agent)
        except (OSError, ValueError):
            continue
        count = sum(1 for p in plans if p.status == "ok")
        if count:
            linked.append(f"{agent} ({count})")
    if linked:
        checks.append(("agents", "ok", ", ".join(linked)))
    else:
        checks.append(("agents", "warn", "no agent is linked — run `freya install`"))

    plugin_dir = Path.home() / ".claude" / "plugins" / "marketplaces" / "freya-devkit"
    try:
        personally_installed = any(
            p.status == "ok" for p in installer.plan_agent(root, "claude")
        )
    except (OSError, ValueError):
        personally_installed = False
    both = plugin_dir.is_dir() and personally_installed
    if both:
        checks.append((
            "duplicate install", "warn",
            "the Claude marketplace plugin and the personal install are both present; "
            "every skill appears twice (`/freya-devkit:freya-x` and `/freya-x`). "
            "Remove one.",
        ))
    else:
        checks.append(("duplicate install", "ok", "none"))
```

- [ ] **Step 4: Replace `drift.py`'s textual reach**

`skills/freya-spec-manager/scripts/drift.py:37-38` reaches `graph_ops.py` with `os.path.abspath` plus a textual `../..`. `abspath` does **not** resolve symlinks, so under an installed layout it can point outside the store. Every other script in the suite uses `Path(__file__).resolve().parents[2]`; make this one match. The variable is `_GRAPH_OPS`:

```python
-_GRAPH_OPS = os.path.join(os.path.dirname(os.path.abspath(__file__)),
-                          "..", "..", "code-graph", "scripts", "graph_ops.py")
+_GRAPH_OPS = str(Path(__file__).resolve().parents[2]
+                 / "freya-code-graph" / "scripts" / "graph_ops.py")
```

Note the directory name also gains the `freya-` prefix — but Task 2 already changed it, so after that task the line reads `"freya-code-graph"` and only the `abspath` → `.resolve()` part remains. Add `from pathlib import Path` if it is not already imported, and leave `_GRAPH_OPS` a `str` — its callers pass it to `subprocess`.

- [ ] **Step 5: Verify**

```bash
cd bin && python3 -m unittest test_freya_cli -q
cd ../skills/freya-spec-manager/scripts && python3 -m unittest test_drift -q
```
Expected: both `OK`.

```bash
./bin/freya doctor
```
Expected: exits 0 and prints an `[ok]` or `[warn]` line for both `agents` and `duplicate install`.

- [ ] **Step 6: Commit**

```bash
git add bin/freya_cli.py bin/test_freya_cli.py skills/freya-spec-manager/scripts/drift.py
git commit -F - <<'EOF'
feat(doctor): report agent links and flag a duplicate Claude install

doctor now says which agents are linked to this store, and warns when the
marketplace plugin and the personal install are both present — Claude
namespaces plugin skills, so that combination registers all ten skills twice.

Also replaces drift.py's abspath + textual "../.." reach into graph_ops.py
with the .resolve()-based form every other script uses. abspath does not
resolve symlinks, so the old form could point outside the store once
installed.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

### Task 7: User-facing documentation

The 47 references Phase 2 deferred, plus the install instructions that now exist.

**Files:**
- Modify: `README.md` (13), `docs/skill-reference.md` (17), `docs/conventions.md` (10), `docs/patterns.md` (3), `docs/architecture.md` (1 slash + 1 `${CLAUDE_PLUGIN_ROOT}`), `docs/philosophy.md` (1), `CONTRIBUTING.md` (2)

**Interfaces:**
- Consumes: the finished installer and the renamed skills.

- [ ] **Step 1: Rewrite the slash references**

`/freya-devkit:<skill>` → `freya-<skill>`, matching what the skill layer already says. Where the text tells a *human what to type*, give both forms, because they genuinely differ:

| Install path | Typed form |
|---|---|
| Portable (`install.sh`, any agent) | `/freya-wrap-up` |
| Claude marketplace plugin | `/freya-devkit:freya-wrap-up` |

Do **not** rewrite `docs/design/`, `docs/explanations/`, `docs/migrations/`, or `docs/superpowers/plans/` — historical record, and `check_skill_conformance.py` does not scan them.

- [ ] **Step 2: Fix the one `${CLAUDE_PLUGIN_ROOT}` in `docs/architecture.md`**

Replace it with the `freya <command>` form, matching how the skill layer now invokes scripts.

- [ ] **Step 3: Add an Installation section to `README.md`**

Cover both paths, and state the duplicate-install hazard:

````markdown
## Installation

### Any agent (Claude Code, GitHub Copilot, …)

```bash
git clone https://github.com/AlexSendula/freya-devkit.git
cd freya-devkit
./install.sh
```

The checkout is the store: `install.sh` symlinks each skill into your agent's
skills directory and puts the `freya` launcher on `PATH`. Pick agents explicitly
with `--agent claude --agent copilot`; use `--copy` where symlinks are awkward
(Windows without Developer Mode), `--dry-run` to preview, and `--uninstall` to
remove. Verify with `freya doctor`.

Skills install as `freya-code-graph`, `freya-wrap-up`, and so on.

### Claude Code, via the plugin marketplace

```
/plugin marketplace add AlexSendula/freya-devkit
/plugin install freya-devkit@freya-devkit
```

Skills appear as `/freya-devkit:freya-code-graph`.

> Use one path or the other. With both, Claude registers every skill twice —
> once namespaced by the plugin and once from your personal directory.
> `freya doctor` warns when it sees this.
````

- [ ] **Step 4: Verify**

```bash
grep -rn '/freya-devkit:' README.md CONTRIBUTING.md docs/*.md
```
Expected: only lines that deliberately document the Claude plugin's typed form.

```bash
grep -rn 'CLAUDE_PLUGIN_ROOT' README.md CONTRIBUTING.md docs/*.md
```
Expected: only `CONTRIBUTING.md`'s audit-Workflow bullet, which Phase 4b removes.

- [ ] **Step 5: Commit**

```bash
git add README.md CONTRIBUTING.md docs/*.md
git commit -F - <<'EOF'
docs: update user-facing docs for the portable install

Rewrites the 47 /freya-devkit: references Phase 2 deferred, and adds an
Installation section covering both paths — install.sh for any agent, and the
Claude marketplace plugin — including the warning that using both registers
every skill twice.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
```

---

## Definition of done

- `python3 bin/check_skill_conformance.py` exits 0, with R8 confirming all ten `name`/directory pairs.
- All 19 test suites pass (17 existing + `bin/test_installer.py`, and `test_freya_cli.py` grown).
- `./install.sh --dry-run --target-dir /tmp/… --bin-dir /tmp/…` prints a ten-skill plan and creates nothing.
- A real install into a temp target round-trips: links resolve into the store, a second run is a no-op, `--uninstall` removes exactly what was added.
- `./bin/freya doctor` exits 0 and reports `agents` and `duplicate install`.
- All 14 `freya <command>` names still resolve — the rename changed paths, not command names.
- `.claude-plugin/` and `workflows/` unchanged from `main`.
- **Nothing pushed.**

## Carried forward

- **Phase 4:** the three LLM fan-out flows, including "using parallel subagents" in `freya-codebase-security-scan`'s `description:`.
- **Phase 4b:** the audit Workflow — two `${CLAUDE_PLUGIN_ROOT}` lines and four "Workflow tool" references in `skills/freya-codebase-security-scan/SKILL.md`, the `AUDIT_WORKFLOW_MARKER` exemption and `AGENT_TOOL_NAMES` omission in the checker, and `CONTRIBUTING.md`'s Workflow bullet. Removing them together is the completeness proof.
- **Phase 5:** `freya update` (re-fetch the store, re-link) and the throttled notify-only check; `freya init` for a per-project `AGENTS.md`. `BUILTIN_COMMANDS` in the checker already allows `update` and `init`; after Phase 5 they will be real.
- **Phase 6:** validate on both agents from a clean install — including Windows, where `install.ps1` has never run, and the `/freya-<skill>` vs `/freya-devkit:freya-<skill>` naming under each install path.
- **Deliberately not built here: `--project` scope.** Design §4 lists `install.sh [--project|--global]`, with `--project` writing into a repo's `.github/skills` (Copilot) or `.claude/skills` (Claude) for teams that vendor their tooling. Decision 2 already makes personal scope the default, and the MVP's definition of done (design §9) only exercises personal scope. Adding it is small — `plan_agent` takes a `target_dir` already, so it is a flag plus a per-agent project path table — but it doubles the install matrix Phase 6 must validate. Build it when someone wants a committed install, not before.
- The marketplace copy at `~/.claude/plugins/marketplaces/freya-devkit` is stale (7 skills, predates the behavior layer). Refresh it as part of the release, not here.
