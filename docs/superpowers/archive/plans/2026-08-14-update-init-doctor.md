# Phase 5 Implementation Plan — `freya update`, the notify check, `freya init`, orphan-aware `doctor`

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A user can refresh the store with one command, is told at most once a day when it is stale, can drop a freya-devkit primer into a project's `AGENTS.md`, and is warned by `doctor` when their install links point at a store that has moved.

**Architecture:** Two new stdlib modules — `bin/updater.py` (git interrogation, the update, the notify check) and `bin/agents_md.py` (render and merge the `AGENTS.md` block). Both are pure library code with injected side effects (`run`, `out`, `now`), so every test is offline. `bin/freya_cli.py` wires the two new commands and extends `doctor`; `bin/installer.py` gains one new function, `audit_agent()`, which both `update` and `doctor` consume.

**Tech Stack:** Python 3 stdlib only (`argparse`, `json`, `os`, `pathlib`, `shutil`, `subprocess`, `time`, `unittest`). Real `git` in temp directories for the updater tests.

## Context

This is **Phase 5 of 6** of the portability track ([`docs/design/portability/01-design.md`](../../../design/portability/01-design.md) §8, §11), designed in [`docs/superpowers/specs/2026-08-14-phase-5-update-init-design.md`](../specs/2026-08-14-phase-5-update-init-design.md). Branch `feat/polyglot-portability` stays open. Phases 1–4b are built and reviewed; phase 6 is end-to-end validation on Copilot and Claude and depends on this phase existing.

### Three facts verified against the tree (2026-08-14), each of which shapes a task

**1. `plan_agent()` cannot see an orphan.** It iterates `discover_skills(store)` — the skills present *in the store* — and derives a target path per skill. An entry sitting in the agent's directory whose skill no longer exists in the store is therefore invisible to it, and so is a link left behind when the checkout moved. That is precisely the case `doctor` must warn about and `update` must prune, which is why Task 1 adds a function that scans the **agent directory** instead.

**2. Every `SKILL.md` writes `description` as a YAML block scalar.** For example:

```yaml
description: |
  Build and query code dependency graphs for impact analysis and blast radius tracking.
  Use this skill when you need to:
```

`frontmatter_name()` in `bin/check_skill_conformance.py` only reads inline values, so a naive generalization returns `"|"` for every skill and the `AGENTS.md` table ships ten empty cells. Task 8 handles both forms.

**3. `update` and `init` are already in `BUILTIN_COMMANDS`** ([`bin/check_skill_conformance.py:20`](../../../../bin/check_skill_conformance.py)), so documenting them cannot trip rule R3. (`uninstall` is *not* in that set — out of scope, carried forward.)

## Global Constraints

- **Python 3 stdlib only.** No third-party imports anywhere.
- **Shebang `#!/usr/bin/env python3`** on executable scripts. **Never invoke bare `python`** — in code, in docs, or in commands you run.
- **Tests colocated in `bin/`, `unittest`**, run as `cd bin && python3 -m unittest test_<module> -v`. Match the fixture style of `bin/test_installer.py`.
- **Resolve temp directories in tests.** On macOS `/var` is a symlink to `/private/var`, so a path built from `tempfile.TemporaryDirectory()` and a path read back from a symlink compare unequal. Every fixture below uses `Path(tmp).resolve()`. This is not hypothetical — it already bit `uninstall_agent` (see its comment about resolving the parent).
- **Never destroy user data.** New code may remove only what `audit_agent` has classified `ok` or `orphan-skill` — that is, a symlink into this store or a copy carrying our `MARKER` naming this store. `stale-store`, `foreign` and `occupied` are reported and left alone, always.
- **Injected side effects.** `updater` takes `run=` (git), `out=` (printing) and `now=` (the clock); `agents_md` takes `out=`. No test may spawn a network call or read the real `~/.freya`.
- **The notify check may never change a command's exit code**, never print a traceback, and never write to stdout.
- **Two names, one character apart:** `freya <command>` (space) is the CLI; `freya-<skill>` (hyphen) is a skill name.
- **`python3 bin/check_skill_conformance.py` must exit 0** before every commit.
- **Commit locally after each task. Do NOT push.** The user requires explicit permission for every push.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

## File Structure

| File | Responsibility |
|---|---|
| `bin/installer.py` | **Modify.** `AgentEntry`, `audit_agent()`, `blocker_error()`; `main()` plans every agent before mutating any. |
| `bin/test_installer.py` | **Modify.** Audit classification; all-or-nothing multi-agent install. |
| `bin/updater.py` | **Create.** git queries, `update()`, `relink()`, the throttled notify check. |
| `bin/test_updater.py` | **Create.** Real-git fixtures; injected-runner notify tests. |
| `bin/agents_md.py` | **Create.** `render_block()`, `merge()`, `init()`. |
| `bin/test_agents_md.py` | **Create.** Render, merge, idempotency, malformed markers. |
| `bin/check_skill_conformance.py` | **Modify.** `frontmatter_value()` (inline + block scalar); `frontmatter_name()` becomes a wrapper. |
| `bin/test_check_skill_conformance.py` | **Modify.** Block-scalar reading. |
| `bin/freya_cli.py` | **Modify.** Wire `update` / `init`, call the notify check, extend `doctor_checks()`. |
| `bin/test_freya_cli.py` | **Modify.** Doctor's new checks; notify wiring; unknown-command list unchanged. |
| `README.md`, `docs/skill-reference.md` | **Modify.** Document both new commands. |

---

### Task 1: `audit_agent()` — see what is actually in the agent's directory

The one function both `update` and `doctor` need, and the one thing `plan_agent` structurally cannot do.

**Files:**
- Modify: `bin/installer.py`
- Test: `bin/test_installer.py`

**Interfaces:**
- Consumes: existing `SKILL_PREFIX`, `MARKER`, `AGENT_TARGETS`, `discover_skills`.
- Produces: `AgentEntry = namedtuple("AgentEntry", "path points_at status")` and
  `audit_agent(store, agent, target_dir=None) -> list[AgentEntry]`, with `status` one of
  `ok | stale-store | orphan-skill | foreign | occupied`. Tasks 2, 5 and 6 depend on both.

- [ ] **Step 1: Write the failing tests**

Append to `bin/test_installer.py`:

```python
class AuditAgentTest(unittest.TestCase):
    def _fixture(self, tmp):
        """A store plus an empty agent directory, both resolved."""
        root = Path(tmp).resolve()
        return make_store(root), root / "agent"

    def test_a_link_into_this_store_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            agent.mkdir()
            (agent / "freya-status").symlink_to(store / "skills" / "freya-status")
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual([(e.path.name, e.status) for e in entries],
                             [("freya-status", "ok")])

    def test_a_link_into_a_moved_store_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            agent.mkdir()
            gone = Path(tmp).resolve() / "old-checkout" / "skills" / "freya-status"
            (agent / "freya-status").symlink_to(gone)
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual([e.status for e in entries], ["stale-store"])
            self.assertEqual(entries[0].points_at, gone)

    def test_a_link_to_a_skill_deleted_from_this_store_is_an_orphan(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            agent.mkdir()
            (agent / "freya-gone").symlink_to(store / "skills" / "freya-gone")
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual([e.status for e in entries], ["orphan-skill"])

    def test_a_copy_carrying_our_marker_is_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            plans = installer.plan_agent(store, "claude", target_dir=agent)
            installer.apply_plan(plans, copy=True)
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual({e.status for e in entries}, {"ok"})

    def test_a_copy_whose_marker_names_another_store_is_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            copied = agent / "freya-status"
            copied.mkdir(parents=True)
            (copied / installer.MARKER).write_text(
                str(Path(tmp).resolve() / "elsewhere" / "skills" / "freya-status"),
                encoding="utf-8")
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual([e.status for e in entries], ["stale-store"])

    def test_a_bare_directory_is_occupied_not_ours(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            (agent / "freya-status").mkdir(parents=True)
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual([e.status for e in entries], ["occupied"])

    def test_a_link_pointing_somewhere_unrelated_is_foreign(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            agent.mkdir()
            (agent / "freya-status").symlink_to(Path(tmp).resolve() / "random")
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual([e.status for e in entries], ["foreign"])

    def test_entries_that_are_not_ours_by_name_are_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            agent.mkdir()
            (agent / "someone-elses-skill").mkdir()
            self.assertEqual(installer.audit_agent(store, "claude", target_dir=agent), [])

    def test_a_missing_agent_directory_audits_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            self.assertEqual(installer.audit_agent(store, "claude", target_dir=agent), [])

    def test_an_unknown_agent_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, _ = self._fixture(tmp)
            with self.assertRaises(ValueError):
                installer.audit_agent(store, "emacs")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_installer -v`
Expected: 10 errors, `AttributeError: module 'installer' has no attribute 'audit_agent'`.

- [ ] **Step 3: Implement**

In `bin/installer.py`, after `LinkPlan`:

```python
#: One entry found in an agent's skills directory, as seen from this store.
#: `status` is ok | stale-store | orphan-skill | foreign | occupied.
AgentEntry = namedtuple("AgentEntry", "path points_at status")
```

and after `plan_agent`:

```python
def _link_target(entry):
    """The absolute path a symlink names, normalized but not resolved.

    Deliberately not `.resolve()`: a link left behind by a moved checkout is
    dangling, and resolving it would either raise or silently rewrite the very
    path we need to show the user.
    """
    points_at = Path(os.readlink(entry))
    if not points_at.is_absolute():
        points_at = entry.parent / points_at
    return Path(os.path.normpath(points_at))


def _entry_status(points_at, skills_dir, name):
    """Where an entry's target places it relative to this store."""
    if points_at.parent == skills_dir:
        # Ours by location. It is only an orphan if the skill itself is gone.
        return "ok" if points_at.exists() else "orphan-skill"
    if points_at.parent.name == "skills" and points_at.name == name:
        # Same shape, different store: a moved checkout, or a second one.
        # We cannot tell those apart and do not need to — both mean "not here".
        return "stale-store"
    return "foreign"


def audit_agent(store, agent, target_dir=None):
    """Classify every `freya-*` entry in an agent's skills directory.

    The counterpart to `plan_agent`, which iterates the skills in the *store*
    and so cannot see an entry whose skill no longer exists there, nor one left
    behind when the checkout moved. This walks the *agent's* directory instead,
    which is what `freya update` needs to prune and `freya doctor` needs to warn.

    Ownership rules are exactly `classify`'s: a symlink is ours if it points
    into this store's `skills/`, and a real directory is ours only if it carries
    our MARKER naming this store. Anything else is reported, never touched.
    """
    if target_dir is None:
        try:
            target_dir = AGENT_TARGETS[agent]
        except KeyError:
            raise ValueError(f"unknown agent: {agent!r} (known: {', '.join(sorted(AGENT_TARGETS))})")
    if not target_dir.is_dir():
        return []
    skills_dir = Path(os.path.normpath(store / "skills"))
    entries = []
    for path in sorted(target_dir.iterdir()):
        if not path.name.startswith(SKILL_PREFIX):
            continue
        if path.is_symlink():
            try:
                points_at = _link_target(path)
            except OSError:
                entries.append(AgentEntry(path, None, "foreign"))
                continue
        elif path.is_dir() and (path / MARKER).is_file():
            try:
                content = (path / MARKER).read_text(encoding="utf-8").strip()
            except OSError:
                entries.append(AgentEntry(path, None, "foreign"))
                continue
            points_at = Path(os.path.normpath(content))
        else:
            entries.append(AgentEntry(path, None, "occupied"))
            continue
        entries.append(AgentEntry(path, points_at, _entry_status(points_at, skills_dir, path.name)))
    return entries
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_installer -v`
Expected: PASS, all tests including the pre-existing ones.

- [ ] **Step 5: Mutation-check the status ladder**

> **Delete `__pycache__` between mutations, or run `python3 -B`.** Edits within the same
> mtime tick make Python reuse stale bytecode, and a mutation that was never loaded looks
> killed. This caught out phase 4b's validation run twice.

1. In `_entry_status`, drop the `points_at.exists()` test and return `"ok"` unconditionally
   for the in-store branch.
   Expected: FAIL on `test_a_link_to_a_skill_deleted_from_this_store_is_an_orphan`. **Restore.**
2. In `_entry_status`, delete the `points_at.name == name` half of the stale-store condition.
   Expected: FAIL on `test_a_link_into_another_store_under_a_different_name_is_foreign`.
   `test_a_link_pointing_somewhere_unrelated_is_foreign` does **not** discriminate this
   mutation, despite first appearances: `random`'s parent is the temp dir itself, never named
   `skills`, so the first clause (`points_at.parent.name == "skills"`) already returns false
   and the entry lands on `"foreign"` whether or not the second clause exists. Killing this
   half needs a target whose parent really is a `skills/` directory — the shape of another
   store's layout — but named for a *different* skill than the entry itself, which is what
   the added test supplies. **Restore.**
3. In `audit_agent`, drop the `startswith(SKILL_PREFIX)` filter.
   Expected: FAIL on `test_entries_that_are_not_ours_by_name_are_ignored`. **Restore.**
4. In `audit_agent`, treat any directory as ours by removing the `(path / MARKER).is_file()`
   condition.
   Expected: FAIL on `test_a_bare_directory_is_occupied_not_ours`. **Restore.**

Re-run after restoring all four: PASS.

- [ ] **Step 6: Commit**

```bash
git add bin/installer.py bin/test_installer.py
git commit -F - <<'EOF'
feat(installer): audit_agent sees what plan_agent structurally cannot

plan_agent iterates the skills in the store and derives one target per skill,
so an entry in the agent's directory whose skill no longer exists there is
invisible to it — and so is every link left behind when the checkout moved.
That is exactly the case doctor must warn about and update must prune, so it
needed a function that walks the agent's directory instead.

The ownership rules are classify's, unchanged: a symlink is ours by pointing
into this store's skills/, a real directory only by carrying the marker that
names this store. stale-store and orphan-skill are new vocabulary for two
shapes classify collapsed into "foreign" — the distinction matters because one
is fixed by re-installing and the other by pruning.

_link_target deliberately does not resolve: a link from a moved checkout is
dangling, and resolving it would discard the path the user needs to see.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 2: `doctor` reports orphans, and says how the suite is installed

**Files:**
- Modify: `bin/freya_cli.py` (the `agents` block of `doctor_checks`, lines 141–155)
- Test: `bin/test_freya_cli.py`

**Interfaces:**
- Consumes: `installer.audit_agent` (Task 1).
- Produces: `doctor_checks(root=None, targets=None)` — `targets` is an optional
  `{agent: Path}` override so the suite never reads the real home directory. Two check
  labels: the reworded `agents`, and a new `orphaned entries`.

> **Addendum (final review fix wave, 2026-08-14):** a whole-branch review found four more
> problems in the version below. `except (OSError, ValueError): continue` around
> `audit_agent` swallowed an unauditable agent directory entirely, so `doctor` fell through
> to "the suite is not installed for any agent — run `freya install`" — the wrong remedy for
> a directory that is merely unreadable, and the same condition `updater.relink` already
> counts as a failure rather than hiding. It now appends a dedicated `agent: <name>` warn
> check naming the error. Second, a `foreign` or `occupied` entry whose name IS a skill the
> store still has means that skill is silently not installed — `relink` printed "left alone"
> and `doctor`'s orphan clause never looked at `foreign`/`occupied` at all, so the install
> looked complete when a name was actually shadowed. The orphan clause now has two more
> sub-clauses for exactly that, worded for their remedy (`--force` for a foreign symlink,
> "move it aside" for a real path). Third, the `orphan-skill` clause named only the entry,
> not the path it pointed at, unlike its `stale-store` sibling — both now do. Fourth, the
> mode computation (`"copy" if any(not e.path.is_symlink() for e in ours) else "symlink"`)
> duplicated `updater.install_mode`; it now calls that function instead. The code block below
> is the corrected version.

- [ ] **Step 1: Write the failing tests**

Append to `bin/test_freya_cli.py`:

```python
class DoctorAgentsTest(unittest.TestCase):
    def _store_and_agent(self, tmp):
        root = Path(tmp).resolve()
        store = root / "store"
        (store / "bin").mkdir(parents=True)
        for name in ("freya-status",):
            d = store / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n",
                                        encoding="utf-8")
        agent = root / "agent"
        agent.mkdir()
        return store, agent

    def _check(self, checks, label):
        return next((c for c in checks if c[0] == label), None)

    def test_reports_the_install_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            (agent / "freya-status").symlink_to(store / "skills" / "freya-status")
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            self.assertEqual(self._check(checks, "agents")[1], "ok")
            self.assertIn("claude (1, symlink)", self._check(checks, "agents")[2])

    def test_warns_about_a_link_into_a_moved_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            (agent / "freya-status").symlink_to(
                Path(tmp).resolve() / "old" / "skills" / "freya-status")
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            orphaned = self._check(checks, "orphaned entries")
            self.assertEqual(orphaned[1], "warn")
            self.assertIn("old", orphaned[2])
            self.assertIn("freya install --force", orphaned[2])

    def test_reports_a_copy_install_as_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            installer.apply_plan(
                installer.plan_agent(store, "claude", target_dir=agent), copy=True)
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            self.assertEqual(self._check(checks, "agents")[1], "ok")
            self.assertIn("claude (1, copy)", self._check(checks, "agents")[2])

    def test_says_nothing_is_installed_when_the_directory_is_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._store_and_agent(tmp)
            checks = freya_cli.doctor_checks(store, targets={"claude": agent})
            self.assertEqual(self._check(checks, "agents")[1], "warn")
            self.assertEqual(self._check(checks, "orphaned entries")[1], "ok")
```

`bin/test_freya_cli.py` needs `import installer`, `import tempfile` and `from pathlib import Path` if they are not already present.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: FAIL — `doctor_checks() got an unexpected keyword argument 'targets'`.

- [ ] **Step 3: Implement**

In `bin/freya_cli.py`, change the signature to `def doctor_checks(root=None, targets=None):`
and replace the `agents` block (everything from `linked = []` through the `else` that appends
`"no agent is linked"`) with:

```python
    store_skill_names = {s.name for s in installer.discover_skills(root)}

    installed, orphaned, shadowed, unauditable = [], [], [], []
    for agent in sorted(installer.AGENT_TARGETS):
        target_dir = None if targets is None else targets.get(agent)
        if targets is not None and target_dir is None:
            continue
        try:
            entries = installer.audit_agent(root, agent, target_dir=target_dir)
        except (OSError, ValueError) as exc:
            unauditable.append((agent, exc))
            continue
        ours = [e for e in entries if e.status == "ok"]
        if ours:
            # A copy is a real directory; a link is not. That is the whole
            # distinction, and it is why the old wording ("linked") was wrong
            # for a --copy install that is perfectly well installed.
            mode = updater.install_mode(entries)
            installed.append(f"{agent} ({len(ours)}, {mode})")
        orphaned += [(agent, e) for e in entries
                     if e.status in ("stale-store", "orphan-skill")]
        # A `foreign`/`occupied` entry whose name IS a skill this store still
        # has means that skill is not installed for this agent — the target
        # name it needs is taken by something else.
        shadowed += [(agent, e) for e in entries
                     if e.status in ("foreign", "occupied")
                     and e.path.name in store_skill_names]

    for agent, exc in unauditable:
        checks.append((f"agent: {agent}", "warn", f"could not be audited ({exc})"))

    if installed:
        checks.append(("agents", "ok", ", ".join(installed)))
    else:
        checks.append(("agents", "warn", "the suite is not installed for any agent — "
                                         "run `freya install`"))

    if orphaned or shadowed:
        # Four different failures with four different fixes (a
        # moved/duplicated checkout, a skill deleted from this one, a
        # symlink to replace, or a real path to move aside), so they cannot
        # share one message — each gets its own clause, and only non-empty
        # kinds are shown.
        stale = [(agent, e) for agent, e in orphaned if e.status == "stale-store"]
        orphan_skill = [(agent, e) for agent, e in orphaned if e.status == "orphan-skill"]
        shadowed_foreign = [(agent, e) for agent, e in shadowed if e.status == "foreign"]
        shadowed_occupied = [(agent, e) for agent, e in shadowed if e.status == "occupied"]
        clauses = []
        if stale:
            agent, entry = stale[0]
            clauses.append(
                f"{len(stale)} pointing at a different store "
                f"(e.g. {agent}: {entry.path.name} -> {entry.points_at}) — "
                "the checkout moved; re-run `freya install --force`"
            )
        if orphan_skill:
            agent, entry = orphan_skill[0]
            clauses.append(
                f"{len(orphan_skill)} naming a skill this store no longer has "
                f"(e.g. {agent}: {entry.path.name} -> {entry.points_at}) — "
                "`freya update` prunes them"
            )
        if shadowed_foreign:
            agent, entry = shadowed_foreign[0]
            clauses.append(
                f"{len(shadowed_foreign)} foreign symlink occupying the name of a skill "
                f"this store still has (e.g. {agent}: {entry.path.name}) — that skill is "
                "not installed; re-run `freya install --force` to replace it"
            )
        if shadowed_occupied:
            agent, entry = shadowed_occupied[0]
            clauses.append(
                f"{len(shadowed_occupied)} occupying the name of a skill this store still "
                f"has (e.g. {agent}: {entry.path.name}) — that skill is not installed; "
                "move it aside, then re-run `freya install`"
            )
        checks.append(("orphaned entries", "warn", "; ".join(clauses)))
    else:
        checks.append(("orphaned entries", "ok", "none"))
```

`stale-store`, `orphan-skill`, `foreign` and `occupied` are diagnosed and fixed
differently — a moved/duplicated checkout, a skill deleted from *this* store, a symlink a
`--force` reinstall would replace, and a real path only a human can move — so a single
sentence covering all of them always misdescribes most of them; the fix is a clause per
kind, not a phrase that tries to fit them all. This also imports `updater` at the top of
the function (alongside `installer`), since the `mode` line now calls
`updater.install_mode` rather than duplicating its logic.

Note that the `duplicate install` check below still calls `plan_agent(root, "claude")` against
the real home. Leave it: it is asking a different question (is the marketplace plugin *also*
present), and Task 2 does not change its behaviour. (A later review closed this gap after all —
see the addendum at the end of Task 7, which is where the `targets` parameter's own contract
finally reached this check.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_freya_cli -v`
Expected: PASS.

Then confirm the real installation still reports sensibly:

Run: `./bin/freya doctor; echo "exit=$?"`
Expected: exit 0; an `agents` line naming a mode, and `orphaned entries: none`.

- [ ] **Step 5: Commit**

```bash
git add bin/freya_cli.py bin/test_freya_cli.py
git commit -F - <<'EOF'
fix(doctor): warn about orphaned entries and stop calling copies unlinked

Phase 3 left doctor able to see a moved checkout but not to say so: it counted
only entries that matched the current store and printed nothing about the rest.
Moving the checkout orphans every install link, which is the one failure mode a
user cannot diagnose from the symptom (skills simply stop appearing).

doctor now audits the agent directory and names the first offender with the path
it points at, because "3 entries point at a store that is not this one" is not
actionable without knowing which store.

The wording is fixed too. A --copy install is installed; it just is not linked.
It now reports as `claude (10, copy)` rather than being described as absent.

targets= is an injection point for the tests, which must never read the real
home directory.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 3: A multi-agent install is all-or-nothing across agents

**Files:**
- Modify: `bin/installer.py` (`apply_plan`, `main`)
- Test: `bin/test_installer.py`

**Interfaces:**
- Produces: `blocker_error(stopped) -> RuntimeError`, used by both `apply_plan` and `main`.
- `main`'s behaviour changes: with `--agent a --agent b`, a blocker under `b` now leaves `a`
  untouched.

> **Addendum (final review fix wave, 2026-08-14):** the barrier below covered every agent
> but not the launcher. `link_launcher` runs after the `for agent, plans in planned:` loop
> and performs its own blocker check there — so a real file at `~/.local/bin/freya` let every
> agent install in full and only then exited 2, the exact mutated-but-reported-as-failed shape
> this task exists to remove, and it made the comment below ("makes the guarantee per
> invocation") false. The fix hoists an equivalent check — `installer.launcher_plan` /
> `installer.launcher_blocked`, factored out of `link_launcher` so the two call sites can never
> compute a different status for the same target — into the same pre-flight pass, before the
> per-agent `apply_plan` loop runs. `link_launcher` keeps its own check too; it is called from
> outside `main` and must still refuse on its own. The code block below includes this.

- [ ] **Step 1: Write the failing test**

Append to `bin/test_installer.py`:

```python
class MultiAgentAtomicityTest(unittest.TestCase):
    def test_a_blocker_under_the_second_agent_leaves_the_first_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = make_store(root)
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            # A real directory the installer may never remove.
            (second / "freya-status").mkdir()
            targets = {"claude": first, "copilot": second}
            with unittest.mock.patch.dict(installer.AGENT_TARGETS, targets, clear=True):
                code, _, err = run_main(["--agent", "claude", "--agent", "copilot"])
            self.assertEqual(code, 2)
            self.assertIn("in the way", err)
            self.assertEqual(sorted(p.name for p in first.iterdir()), [])
```

`bin/test_installer.py` needs `import unittest.mock` at the top.

- [ ] **Step 2: Run the test to verify it fails**

Run: `cd bin && python3 -m unittest test_installer.MultiAgentAtomicityTest -v`
Expected: FAIL — `first` contains `freya-code-graph` and `freya-status`; the first agent was
installed before the second one raised.

- [ ] **Step 3: Implement**

In `bin/installer.py`, extract the message so both callers share one wording:

```python
def blocker_error(stopped):
    """The single refusal message for anything standing in the install's way."""
    detail = "\n".join(f"  {p.target} ({p.status})" for p in stopped)
    return RuntimeError(
        "cannot install — these targets are in the way:\n" + detail
        + "\n\nA real file or directory is never removed. Move it aside, or "
          "re-run with --force to replace foreign symlinks."
    )
```

In `apply_plan`, replace the inline construction with:

```python
    stopped = blockers(plans, force)
    if stopped:
        raise blocker_error(stopped)
```

In `main`, replace the install loop with a plan-everything-first pass. This alone still has a
gap: planning every agent before applying any of them means each `LinkPlan.status` is only a
snapshot of disk state at planning time, and two agent names can resolve to the same physical
target directory (`--agent claude --agent claude`, or two distinct agents sharing the hidden
`--target-dir`). Both plans get computed against the same pre-install disk, so both say
`status="create"` for the same path; applying the first one mutates disk out from under the
second one's snapshot, and applying the second raises `FileExistsError` — the exact
half-installed-but-reported-as-failed behaviour this task exists to remove, just relocated to a
new trigger. The fix dedupes the agent list up front, order preserved, and then — once every
agent is planned — drops any plan whose target a prior agent in this invocation already claimed,
so the duplicate is skipped instead of replayed:

```python
    store = args.store if args.store is not None else store_root()
    agents = args.agent or default_agents()
    # Dedup, order preserved: `--agent claude --agent claude` must behave
    # exactly like a single `--agent claude`, not plan (and try to apply)
    # the same install twice.
    deduped_agents = []
    for agent in agents:
        if agent not in deduped_agents:
            deduped_agents.append(agent)
    agents = deduped_agents
    if not agents:
        ...
```

```python
        # Plan every agent before mutating any of them. apply_plan's
        # "raises before changing anything" guarantee is per agent, which
        # still let `--agent claude --agent copilot` leave claude fully
        # installed when copilot was blocked. Collecting blockers across the
        # whole invocation — the agents' AND the launcher's — makes the
        # guarantee per invocation. The launcher used to be checked only
        # inside link_launcher, which runs after every agent below is
        # already applied: a real file at the launcher target let every
        # agent install in full and only then exited 2, which is exactly the
        # mutated-but-reported-as-failed shape this pass exists to prevent.
        #
        # But planning everything up front, before any of it is applied,
        # means each plan's `status` is only a snapshot of disk state at
        # planning time. Two agent names can resolve to the same physical
        # target directory — `--target-dir` is shared, or (after the dedup
        # above) two distinct agents just happen to point at one location —
        # and both snapshots are taken against the same pre-install disk, so
        # both say `status="create"` for the same path. Applying the first
        # one then invalidates the second one's snapshot: the path it was
        # planned against no longer matches disk, and applying it too would
        # call symlink_to on a path that now exists. So once every agent is
        # planned, drop any plan whose target path a prior agent in this
        # invocation already claimed — the duplicate describes the same
        # physical install, already handled, not a second one to apply.
        planned = []
        claimed_targets = set()
        for agent in agents:
            plans = plan_agent(store, agent, target_dir=args.target_dir)
            if not plans:
                print(f"{agent}: no skills found in {store / 'skills'}", file=sys.stderr)
                return 1
            deduped = [p for p in plans if p.target not in claimed_targets]
            claimed_targets.update(p.target for p in plans)
            planned.append((agent, deduped))

        stopped = [p for _, plans in planned for p in blockers(plans, args.force)]
        if stopped:
            raise blocker_error(stopped)

        launcher_target_path, _, launcher_status = launcher_plan(store, bin_dir=args.bin_dir)
        if launcher_blocked(launcher_status, args.force):
            raise launcher_blocker_error(launcher_target_path, launcher_status)

        for agent, plans in planned:
            for plan, action in apply_plan(plans, copy=args.copy, force=args.force,
                                           dry_run=args.dry_run):
                print(f"{agent}: {action:<8} {plan.target.name}")
```

(`launcher_plan`, `launcher_blocked` and `launcher_blocker_error` are the addendum's factoring
out of `link_launcher`'s own check, defined next to it further down the file — see the
launcher section for the shipped signatures.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_installer -v`
Expected: PASS, including every pre-existing install test.

- [ ] **Step 5: Commit**

```bash
git add bin/installer.py bin/test_installer.py
git commit -F - <<'EOF'
fix(installer): a blocked multi-agent install no longer half-installs

apply_plan raises before mutating anything, but main applied one agent at a
time, so the guarantee held per agent and not per invocation: with two agents
and a blocker under the second, the first came out fully installed and the
command still exited 2. The user then had an install they did not ask for and
an error saying the install failed.

Planning every agent first and collecting blockers across all of them makes the
guarantee per invocation. The refusal message moves into blocker_error so the
two call sites cannot drift apart.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 4: `bin/updater.py` — the git layer

Pure queries, no mutation. Tested against real git repositories in temp directories, because
phase 4b's finding was that mocks model a well-behaved dependency and leave the failure paths
unexamined; git is free and deterministic, so there is no reason to repeat that here.

**Files:**
- Create: `bin/updater.py`
- Test: `bin/test_updater.py`

**Interfaces:**
- Produces: `git(args, cwd, timeout=DEFAULT_TIMEOUT) -> (returncode, stdout)`,
  `is_git_store(store, run=git) -> bool`, `upstream(store, run=git) -> str | None`,
  `is_clean(store, run=git) -> bool`, `head(store, run=git) -> str | None`,
  `remote_head(store, tracking, run=git) -> str | None`,
  `preconditions(store, run=git) -> list[str]`.
  Every function takes `run=` so callers can inject. Tasks 5, 6 and 7 consume these.

- [ ] **Step 1: Write the failing tests**

Create `bin/test_updater.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the store updater and the notify check."""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import updater

HAS_GIT = shutil.which("git") is not None


def git(args, cwd):
    """Run git in a fixture, failing loudly — fixtures must not fail silently."""
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


def make_origin(root):
    """A bare origin with one commit, plus the clone that will act as the store."""
    origin, work, store = root / "origin.git", root / "work", root / "store"
    git(["init", "--bare", "--initial-branch=main", str(origin)], root)
    git(["clone", str(origin), str(work)], root)
    git(["config", "user.email", "t@example.com"], work)
    git(["config", "user.name", "T"], work)
    (work / "README.md").write_text("one\n", encoding="utf-8")
    git(["add", "-A"], work)
    git(["commit", "-m", "one"], work)
    git(["push", "-u", "origin", "main"], work)
    git(["clone", str(origin), str(store)], root)
    git(["config", "user.email", "t@example.com"], store)
    git(["config", "user.name", "T"], store)
    return origin, work, store


def advance(work):
    """Add one commit to the upstream via the second working copy."""
    (work / "README.md").write_text("two\n", encoding="utf-8")
    git(["commit", "-am", "two"], work)
    git(["push"], work)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class GitLayerTest(unittest.TestCase):
    def test_a_clone_is_a_git_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            self.assertTrue(updater.is_git_store(store))

    def test_a_plain_directory_is_not_a_git_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp).resolve() / "plain"
            plain.mkdir()
            self.assertFalse(updater.is_git_store(plain))

    def test_a_subdirectory_of_a_repo_is_not_the_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            inner = store / "skills"
            inner.mkdir()
            self.assertFalse(updater.is_git_store(inner))

    def test_upstream_is_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            self.assertEqual(updater.upstream(store), "origin/main")

    def test_a_branch_without_an_upstream_reports_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            git(["checkout", "-b", "local-only"], store)
            self.assertIsNone(updater.upstream(store))

    def test_a_dirty_tree_is_not_clean(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            self.assertTrue(updater.is_clean(store))
            (store / "README.md").write_text("dirty\n", encoding="utf-8")
            self.assertFalse(updater.is_clean(store))

    def test_an_untracked_file_also_counts_as_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            (store / "scratch.txt").write_text("x\n", encoding="utf-8")
            self.assertFalse(updater.is_clean(store))

    def test_remote_head_moves_when_the_upstream_advances(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            before = updater.remote_head(store, "origin/main")
            self.assertEqual(before, updater.head(store))
            advance(work)
            self.assertNotEqual(updater.remote_head(store, "origin/main"), before)


@unittest.skipUnless(HAS_GIT, "git is not installed")
class PreconditionsTest(unittest.TestCase):
    def test_a_clean_clone_has_none(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            self.assertEqual(updater.preconditions(store), [])

    def test_a_non_git_store_says_so_first(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp).resolve() / "plain"
            plain.mkdir()
            self.assertIn("not a git checkout", updater.preconditions(plain)[0])

    def test_a_missing_upstream_names_the_fix(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            git(["checkout", "-b", "local-only"], store)
            reason = updater.preconditions(store)[0]
            self.assertIn("no upstream", reason)
            self.assertIn("--set-upstream-to", reason)

    def test_a_dirty_tree_refuses_before_anything_is_fetched(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            (store / "README.md").write_text("dirty\n", encoding="utf-8")
            self.assertIn("uncommitted changes", updater.preconditions(store)[0])

    def test_git_missing_from_path_is_its_own_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            with unittest.mock.patch("shutil.which", return_value=None):
                self.assertIn("git is not on PATH", updater.preconditions(store)[0])
```

Add `import unittest.mock` to the test module's imports.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_updater -v`
Expected: `ModuleNotFoundError: No module named 'updater'`.

- [ ] **Step 3: Implement**

Create `bin/updater.py`:

```python
#!/usr/bin/env python3
"""Refresh the canonical store, and say when it is stale.

`freya update` fast-forwards the checkout that *is* the store and re-applies
the install; a throttled, notify-only check tells the user when the remote has
moved. Nothing here ever applies an update on its own — a toolkit that gates
wrap-up must not change under a running task.

Every function that touches git takes `run=`, so the whole module is testable
without a network and the CLI has exactly one place where a subprocess is born.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

#: Local git commands are instant; a fetch is not, and ls-remote sits in front
#: of an ordinary command the user is waiting on, so it gets the tight bound.
DEFAULT_TIMEOUT = 10
FETCH_TIMEOUT = 60
LS_REMOTE_TIMEOUT = 2


def git(args, cwd, timeout=DEFAULT_TIMEOUT):
    """Run git in `cwd`; return (returncode, stripped stdout).

    Never raises. A missing git, a timeout or a killed process all come back as
    a non-zero code, because every caller's next move is the same either way and
    an update check must not be able to crash the command it precedes.
    """
    try:
        proc = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return 1, ""
    return proc.returncode, proc.stdout.strip()


def is_git_store(store, run=git):
    """Is `store` itself the root of a git work tree?

    The equality matters: a checkout nested inside some other repository would
    otherwise pass, and `freya update` would fast-forward the wrong project.
    """
    code, out = run(["rev-parse", "--show-toplevel"], store)
    if code != 0 or not out:
        return False
    try:
        return Path(out).resolve() == Path(store).resolve()
    except OSError:
        return False


def upstream(store, run=git):
    """The tracking branch (`origin/main`), or None if the branch has no upstream."""
    code, out = run(["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{u}"], store)
    return out if code == 0 and out else None


def is_clean(store, run=git):
    """True when the work tree has no changes, staged, unstaged or untracked."""
    code, out = run(["status", "--porcelain"], store)
    return code == 0 and out == ""


def head(store, run=git):
    """The SHA of HEAD, or None."""
    code, out = run(["rev-parse", "HEAD"], store)
    return out if code == 0 and out else None


def remote_head(store, tracking, run=git):
    """The SHA the upstream branch points at, or None if it cannot be learned.

    Deliberately `ls-remote`: it asks the remote without writing a single byte
    into the local repository, which is what lets the notify check and
    `--dry-run` both run without side effects.
    """
    remote, _, branch = tracking.partition("/")
    code, out = run(["ls-remote", remote, branch], store, LS_REMOTE_TIMEOUT)
    if code != 0 or not out:
        return None
    return out.split()[0]


def preconditions(store, run=git):
    """Reasons `freya update` must refuse. Empty means go.

    Ordered and short-circuiting: there is no point asking a plain directory
    about its upstream, and a dirty tree must be reported before anything is
    fetched. At most one reason comes back, which keeps the CLI's output to the
    one thing the user has to fix next.
    """
    if shutil.which("git") is None:
        return ["git is not on PATH — freya update refreshes the store with git."]
    if not is_git_store(store, run=run):
        return [f"{store} is not a git checkout — freya update refreshes the store "
                "with git. Re-clone the repository and run the installer again."]
    tracking = upstream(store, run=run)
    if tracking is None:
        _, branch = run(["rev-parse", "--abbrev-ref", "HEAD"], store)
        branch = branch or "HEAD"
        return [f"branch {branch} has no upstream — set one with: "
                f"git branch --set-upstream-to origin/{branch}"]
    if not is_clean(store, run=run):
        return [f"the store has uncommitted changes ({store}) — commit, stash or discard "
                "them. freya update never merges over local work."]
    return []
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_updater -v`
Expected: PASS, 13 tests.

- [ ] **Step 5: Commit**

```bash
git add bin/updater.py bin/test_updater.py
git commit -F - <<'EOF'
feat(update): the git layer freya update is built on

Six queries and an ordered precondition list, each taking an injectable runner.
git() swallows OSError and SubprocessError and reports them as a non-zero code,
because every caller's next move is identical either way and the notify check
built on this must never be able to crash the command it precedes.

is_git_store compares the work-tree root to the store rather than merely asking
whether git knows this path: a checkout nested inside another repository would
otherwise pass, and update would fast-forward the wrong project.

The tests drive real git in temp directories. Phase 4b's review found that
mocks model a well-behaved dependency and leave the failure paths unexamined;
git is free and deterministic, so mocking it here would buy nothing and cost
exactly that.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 5: `update()` — fetch and fast-forward

**Files:**
- Modify: `bin/updater.py`
- Test: `bin/test_updater.py`

**Interfaces:**
- Consumes: Task 4's queries.
- Produces: `update(store, *, dry_run=False, out=print, run=git) -> int` (0 success or
  already-current, 2 refusal). Task 6 calls `relink()` from inside it; Task 7's CLI wiring
  calls `update()`.

- [ ] **Step 1: Write the failing tests**

Append to `bin/test_updater.py`:

```python
@unittest.skipUnless(HAS_GIT, "git is not installed")
class UpdateTest(unittest.TestCase):
    def _run(self, store, **kw):
        lines = []
        code = updater.update(store, out=lines.append, **kw)
        return code, "\n".join(lines)

    def test_fast_forwards_and_reports_the_move(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            before = updater.head(store)
            advance(work)
            code, output = self._run(store)
            self.assertEqual(code, 0)
            self.assertIn("1 commit", output)
            self.assertNotEqual(updater.head(store), before)
            self.assertEqual((store / "README.md").read_text(encoding="utf-8"), "two\n")

    def test_an_unchanged_remote_is_already_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            code, output = self._run(store)
            self.assertEqual(code, 0)
            self.assertIn("already up to date", output)

    def test_a_dirty_tree_refuses_and_changes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            advance(work)
            (store / "README.md").write_text("mine\n", encoding="utf-8")
            code, output = self._run(store)
            self.assertEqual(code, 2)
            self.assertIn("uncommitted changes", output)
            self.assertEqual((store / "README.md").read_text(encoding="utf-8"), "mine\n")

    def test_a_diverged_branch_refuses_rather_than_merging(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            advance(work)
            (store / "local.txt").write_text("local\n", encoding="utf-8")
            git(["add", "-A"], store)
            git(["commit", "-m", "local"], store)
            before = updater.head(store)
            code, output = self._run(store)
            self.assertEqual(code, 2)
            self.assertIn("diverged", output)
            self.assertEqual(updater.head(store), before)

    def test_dry_run_reports_the_move_without_making_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            before = updater.head(store)
            advance(work)
            code, output = self._run(store, dry_run=True)
            self.assertEqual(code, 0)
            self.assertIn("would fast-forward", output)
            self.assertEqual(updater.head(store), before)

    def test_a_non_git_store_refuses(self):
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp).resolve() / "plain"
            plain.mkdir()
            code, output = self._run(plain)
            self.assertEqual(code, 2)
            self.assertIn("not a git checkout", output)

    def test_an_unreachable_remote_refuses_without_touching_the_store(self):
        # Not a structural test. Without the fetch guard the flow falls through
        # to merge-base against the *stale* local ref, which succeeds, and the
        # command reports "already up to date" on a store that is not — the one
        # wrong answer this command must never give.
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            advance(work)
            before = updater.head(store)

            def offline(args, cwd, timeout=None):
                # A real repository with the network failing at one point only.
                return (1, "") if args[0] == "fetch" else updater.git(args, cwd, timeout)

            code, output = self._run(store, run=offline)
            self.assertEqual(code, 2)
            self.assertIn("could not fetch", output)
            self.assertEqual(updater.head(store), before)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_updater.UpdateTest -v`
Expected: 6 errors, `module 'updater' has no attribute 'update'`.

- [ ] **Step 3: Implement**

Append to `bin/updater.py`:

```python
def update(store, *, dry_run=False, out=print, run=git):
    """Fast-forward the store to its upstream. Returns an exit code.

    Fast-forward only, by design: a merge commit or a rebase in the user's
    toolkit checkout is a surprise they did not ask for, and a store that has
    diverged is a situation only they can resolve.
    """
    reasons = preconditions(store, run=run)
    if reasons:
        for reason in reasons:
            out(f"freya update: {reason}")
        return 2

    tracking = upstream(store, run=run)
    remote_name = tracking.partition("/")[0]
    before = head(store, run=run)

    if dry_run:
        remote = remote_head(store, tracking, run=run)
        if remote is None:
            out(f"dry run: could not reach {remote_name}; nothing checked")
        elif remote == before:
            out(f"dry run: already up to date with {tracking}")
        else:
            out(f"dry run: {tracking} has moved to {remote[:8]} — "
                "freya update would fast-forward and re-link")
        return 0

    code, _ = run(["fetch", remote_name], store, FETCH_TIMEOUT)
    if code != 0:
        out(f"freya update: could not fetch {remote_name} — check your network "
            "and try again.")
        return 2

    # --is-ancestor is the question "can this fast-forward?" asked before
    # attempting it, so a diverged store gets its own message instead of git's.
    code, _ = run(["merge-base", "--is-ancestor", "HEAD", tracking], store)
    if code != 0:
        out(f"freya update: your store has diverged from {tracking} — freya update "
            "only fast-forwards. Reconcile it with git, then run this again.")
        return 2

    code, _ = run(["merge", "--ff-only", tracking], store)
    if code != 0:
        out(f"freya update: fast-forwarding to {tracking} failed. Reconcile the "
            "store with git, then run this again.")
        return 2

    after = head(store, run=run)
    if after == before:
        out("already up to date")
    else:
        _, count = run(["rev-list", "--count", f"{before}..{after}"], store)
        out(f"updated {before[:8]} -> {after[:8]} ({count} commit(s))")
    return 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_updater -v`
Expected: PASS, 19 tests.

- [ ] **Step 5: Mutation-check the refusals**

1. Delete the `merge-base --is-ancestor` guard.
   Expected: FAIL on `test_a_diverged_branch_refuses_rather_than_merging`. (`merge --ff-only`
   fails too, but only after a fetch and with git's generic wording — the guard exists to
   answer the question before acting on it.) **Restore.**
2. In `preconditions`, delete the `is_clean` check.
   Expected: FAIL on `test_a_dirty_tree_refuses_before_anything_is_fetched` and
   `test_a_dirty_tree_refuses_and_changes_nothing`. **Restore.**
3. In `update`, replace `if dry_run:` with `if False:`.
   Expected: FAIL on `test_dry_run_reports_the_move_without_making_it`. **Restore.**
4. In `update`, delete the `if code != 0` guard after the fetch.
   Expected: FAIL on `test_an_unreachable_remote_refuses_without_touching_the_store` — and
   note *how* it fails: the command reports "already up to date" and exits 0, because
   `merge-base` then compares against a stale local ref. **Restore.**

**One path stays deliberately unpinned:** a fetch that *hangs* past its timeout. Injecting a
return value cannot reproduce a hang, and a fixture that sleeps buys a slow suite and no
information. Phase 6 covers it on a real machine.

- [ ] **Step 6: Commit**

```bash
git add bin/updater.py bin/test_updater.py
git commit -F - <<'EOF'
feat(update): freya update fast-forwards the store

Preconditions first and all of them before anything is fetched: git present,
the store is a work-tree root, the branch has an upstream, the tree is clean.
Then fetch, then an explicit --is-ancestor question before the merge, so a
diverged store gets a message naming its situation rather than git's generic
refusal.

Fast-forward only. A merge commit or a rebase inside the user's toolkit
checkout is a surprise they did not ask for, and divergence is a state only
they can resolve.

--dry-run asks ls-remote rather than fetching, so a preview writes nothing at
all into the repository — not even a ref.

Two paths are deliberately untested here and belong to phase 6: an unreachable
remote, and a fetch that times out. Neither can be produced honestly by a
temp-directory fixture.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 6: `relink()` — a pulled store is not an installed store

**Files:**
- Modify: `bin/updater.py`
- Test: `bin/test_updater.py`

**Interfaces:**
- Consumes: `installer.audit_agent`, `installer.plan_agent`, `installer.apply_plan` (Task 1).
- Produces: `install_mode(entries) -> "symlink" | "copy"` and
  `relink(store, *, dry_run=False, out=print) -> int` (agents touched). `update()` calls it
  after a successful fast-forward.

> **Addendum (final review fix wave, 2026-08-14):** two more fixes landed in the code blocks
> below, both in `_relink_agent`'s "left alone" line and `relink`'s own guard. First, a
> `foreign`/`occupied` entry whose name IS a skill this store still has is more than "left
> alone" — it means that skill is not installed for this agent, and the plain line gave no
> signal of that. It now says so explicitly, but only when the name actually collides with a
> current skill; a stray `freya-*` entry naming nothing in the store isn't "shadowing"
> anything and keeps the plain wording. Second, the `if not any(e.status == "ok" for e in
> entries): continue` guard in `relink` had only ever been commented for its first reason (not
> installed for this agent); it is also the only thing preventing a catastrophic prune when
> the store's `skills/` directory itself goes missing or unreadable, since every entry then
> audits as `orphan-skill` and the removal branch below would otherwise delete every one of
> them. The comment now records both reasons, and a test proves an all-orphan-skill agent has
> nothing removed.

- [ ] **Step 1: Write the failing tests**

Add `import installer` and `import unittest.mock` to `bin/test_updater.py`'s header
(alongside the `shutil` import Task 4 added), then append:

```python
class RelinkTest(unittest.TestCase):
    def _store(self, root, skills=("freya-code-graph", "freya-status")):
        store = root / "store"
        (store / "bin").mkdir(parents=True)
        for name in skills:
            d = store / "skills" / name
            d.mkdir(parents=True)
            (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n",
                                        encoding="utf-8")
        return store

    def test_a_skill_added_to_the_store_gets_linked(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root, skills=("freya-status",))
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent))
            new = store / "skills" / "freya-new"
            new.mkdir()
            (new / "SKILL.md").write_text("---\nname: freya-new\ndescription: d\n---\n",
                                          encoding="utf-8")
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                updater.relink(store, out=lambda _: None)
            self.assertTrue((agent / "freya-new").is_symlink())

    def test_a_skill_removed_from_the_store_is_pruned(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root)
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent))
            shutil.rmtree(store / "skills" / "freya-status")
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                updater.relink(store, out=lambda _: None)
            self.assertFalse((agent / "freya-status").exists(follow_symlinks=False))
            self.assertTrue((agent / "freya-code-graph").is_symlink())

    def test_a_copy_install_is_refreshed_not_left_stale(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root, skills=("freya-status",))
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent),
                                 copy=True)
            (store / "skills" / "freya-status" / "SKILL.md").write_text(
                "---\nname: freya-status\ndescription: updated\n---\n", encoding="utf-8")
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                updater.relink(store, out=lambda _: None)
            self.assertIn("updated",
                          (agent / "freya-status" / "SKILL.md").read_text(encoding="utf-8"))

    def test_a_copy_refresh_touches_one_skill_at_a_time(self):
        # Both copy tests above use a single-skill store, so an implementation
        # that deleted every copy before re-copying any of them would still
        # pass them. Only a two-skill store, with an assertion made from
        # *inside* the first copytree call, can tell "per-skill refresh" apart
        # from "delete all, then copy all".
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root)  # freya-code-graph, freya-status
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent),
                                 copy=True)
            for name in ("freya-code-graph", "freya-status"):
                (store / "skills" / name / "SKILL.md").write_text(
                    f"---\nname: {name}\ndescription: updated\n---\n", encoding="utf-8")

            real_copytree = shutil.copytree
            calls = []

            def wrapper(src, dst, *a, **kw):
                calls.append(Path(dst).name)
                if len(calls) == 1:
                    self.assertTrue(
                        (agent / "freya-status").exists(),
                        "freya-status was removed before freya-code-graph "
                        "was refreshed — refresh is not per-skill")
                return real_copytree(src, dst, *a, **kw)

            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                with unittest.mock.patch.object(shutil, "copytree", wrapper):
                    updater.relink(store, out=lambda _: None)

            self.assertEqual(calls, ["freya-code-graph", "freya-status"])
            for name in ("freya-code-graph", "freya-status"):
                self.assertIn("updated",
                              (agent / name / "SKILL.md").read_text(encoding="utf-8"))

    def test_an_agent_with_nothing_installed_is_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root)
            agent = root / "agent"
            agent.mkdir()
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                result = updater.relink(store, out=lambda _: None)
            self.assertEqual(result, (0, 0))
            self.assertEqual(list(agent.iterdir()), [])

    def test_an_occupied_target_does_not_crash_relink(self):
        # The reproduction a later review supplied: freya-code-graph correctly
        # linked, plus a real directory occupying freya-status's target name
        # (a name that exists in the store). apply_plan raises RuntimeError
        # for an "occupied" plan; relink must report and count that, never
        # let it escape as an uncaught traceback after orphan removals above
        # have already run.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root)  # freya-code-graph, freya-status
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent))
            (agent / "freya-status").unlink()
            (agent / "freya-status").mkdir()  # a bare real directory, not ours

            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                result = updater.relink(store, out=lines.append)
            self.assertEqual(result.failed, 0)
            self.assertTrue((agent / "freya-status").is_dir())
            self.assertFalse((agent / "freya-status").is_symlink())
            self.assertTrue((agent / "freya-code-graph").is_symlink())

    def test_a_mixed_install_leaves_the_symlink_alone(self):
        # install_mode is per agent, not per entry: a single --copy skill
        # makes install_mode report "copy" for the whole agent, which used to
        # make every `ok` entry — symlinks included — a refresh candidate.
        # shutil.rmtree on a symlink raises OSError.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root)  # freya-code-graph, freya-status
            agent = root / "agent"
            agent.mkdir()
            plans = installer.plan_agent(store, "claude", target_dir=agent)
            code_graph = [p for p in plans if p.source.name == "freya-code-graph"]
            status = [p for p in plans if p.source.name == "freya-status"]
            installer.apply_plan(code_graph)  # symlinked
            installer.apply_plan(status, copy=True)  # copied — a mixed install
            self.assertTrue((agent / "freya-code-graph").is_symlink())

            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                result = updater.relink(store, out=lambda _: None)
            self.assertEqual(result.failed, 0)
            self.assertTrue((agent / "freya-code-graph").is_symlink())

    def test_an_unreadable_agent_directory_is_reported_and_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root)
            agent = root / "agent"
            agent.mkdir()

            def explode(*_a, **_k):
                raise OSError("permission denied")

            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                with unittest.mock.patch.object(installer, "audit_agent", explode):
                    result = updater.relink(store, out=lines.append)
            self.assertEqual(result.failed, 1)
            self.assertEqual(result.touched, 0)
            self.assertIn("could not be audited", "\n".join(lines))

    def test_a_failed_orphan_removal_is_not_reported_as_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            # Two skills, not one: relink() skips an agent with zero `ok`
            # entries entirely, so an orphan-only fixture would never reach
            # the removal code this test exercises.
            store = self._store(root)  # freya-code-graph, freya-status
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent))
            shutil.rmtree(store / "skills" / "freya-status")  # orphan just this link

            def exploding_unlink(*_a, **_k):
                raise OSError("disk went away")

            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                with unittest.mock.patch.object(Path, "unlink", exploding_unlink):
                    result = updater.relink(store, out=lines.append)
            self.assertEqual(result.failed, 1)
            # "removed" is printed only after the removal succeeds; a failed
            # one must never be reported as done.
            self.assertNotIn("removed freya-status", "\n".join(lines))

    def test_a_failure_partway_is_reported_and_counted_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root, skills=("freya-status",))
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent))

            def explode(*_a, **_k):
                raise OSError("disk went away")

            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                with unittest.mock.patch.object(installer, "plan_agent", explode):
                    result = updater.relink(store, out=lines.append)
            self.assertEqual(result.failed, 1)
            self.assertIn("relink failed", "\n".join(lines))
            # Not the manifest error freya_cli.main would have printed.
            self.assertNotIn("manifest", "\n".join(lines))

    def test_a_foreign_entry_is_reported_and_untouched(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root, skills=("freya-status",))
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent))
            (agent / "freya-other").symlink_to(root / "elsewhere")
            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                updater.relink(store, out=lines.append)
            self.assertTrue((agent / "freya-other").is_symlink())
            self.assertIn("freya-other", "\n".join(lines))

    def test_dry_run_reports_a_copy_refresh_it_does_not_perform(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root, skills=("freya-status",))
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent),
                                 copy=True)
            before = (agent / "freya-status" / "SKILL.md").read_text(encoding="utf-8")
            (store / "skills" / "freya-status" / "SKILL.md").write_text(
                "---\nname: freya-status\ndescription: updated\n---\n", encoding="utf-8")
            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                updater.relink(store, dry_run=True, out=lines.append)
            self.assertIn("would re-copy", "\n".join(lines))
            self.assertEqual((agent / "freya-status" / "SKILL.md").read_text(encoding="utf-8"),
                             before)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_updater.RelinkTest -v`
Expected: 12 errors, `module 'updater' has no attribute 'relink'`.

- [ ] **Step 3: Implement**

Add `import shutil`, `import installer` and `from collections import namedtuple` to
`bin/updater.py`'s imports, then append:

```python
def install_mode(entries):
    """How this agent's suite is installed: `copy` or `symlink`.

    A copy is a real directory and a link is not — that single distinction is
    the whole test, and it is why an install must never be assumed to be links.
    """
    for entry in entries:
        if entry.status == "ok" and not entry.path.is_symlink():
            return "copy"
    return "symlink"


#: What a relink did: how many agents were brought back in step, and how many
#: failed partway. `failed` is not cosmetic — it is what stops `freya update`
#: from exiting 0 over a half-finished install.
RelinkResult = namedtuple("RelinkResult", "touched failed")


def relink(store, *, dry_run=False, out=print):
    """Bring every agent that already has the suite back in step with the store.

    Pulling is not enough. A symlink picks up an edit inside a skill for free,
    but a skill *added* to the store has no link at all and one *deleted* leaves
    a dangling link behind; a copy tracks nothing whatsoever.
    """
    touched = failed = 0
    for agent in sorted(installer.AGENT_TARGETS):
        try:
            entries = installer.audit_agent(store, agent)
        except (OSError, ValueError) as exc:
            # Silently skipping here used to mean an agent whose skills
            # directory turned unreadable was simply never mentioned again.
            # It must count against the run, not vanish from it.
            failed += 1
            out(f"{agent}: could not be audited ({exc})")
            continue
        if not any(e.status == "ok" for e in entries):
            # Two reasons this guard must never be relaxed. First, updating
            # must not install the suite for an agent that never had it — an
            # agent with zero `ok` entries has nothing here that is ours.
            # Second, and load-bearing: if the store's skills/ directory
            # itself goes missing or turns unreadable, every entry in every
            # agent audits as orphan-skill (its symlink target no longer
            # exists), and without this guard the removal loop below would
            # delete every single one of them — a catastrophic prune
            # triggered by a broken store, not a deliberate uninstall.
            continue
        touched += 1
        copy = install_mode(entries) == "copy"
        try:
            _relink_agent(store, agent, entries, copy=copy, dry_run=dry_run, out=out)
        # The skip in _relink_agent's plan loop below is the actual fix for a
        # plan whose status audit_agent already reported as foreign/occupied:
        # apply_plan raises RuntimeError for exactly those statuses, and such
        # a plan must never reach it a second time. Catching RuntimeError here
        # too is only the backstop, in case some future change reopens that
        # path — without it the error would escape all the way to
        # freya_cli.main's `except (OSError, ValueError)`, which reports it as
        # "cannot read the command manifest" after the orphan removals above
        # have already run, and a copytree that failed partway leaves a
        # directory with no marker, which audits as occupied next time too.
        except (OSError, RuntimeError) as exc:
            failed += 1
            out(f"{agent}: relink failed ({exc}). The store itself is updated; "
                "re-run `freya update` to finish linking.")
    return RelinkResult(touched, failed)


def _relink_agent(store, agent, entries, *, copy, dry_run, out):
    """Re-apply one agent's install. Raises OSError (or, only as a backstop,
    RuntimeError); `relink` reports either and counts it as a failure."""
    # Only used to decide whether a `foreign`/`occupied` entry is shadowing a
    # skill the store still has — see the branch below. A stray freya-*
    # entry that names nothing in the store shadows nothing, so it gets the
    # plain "left alone" line, not the "not installed" one.
    store_skill_names = {s.name for s in installer.discover_skills(store)}
    refresh = set()
    for entry in entries:
        if entry.status == "orphan-skill":
            if dry_run:
                out(f"{agent}: would remove {entry.path.name} (no longer in the store)")
            else:
                # Remove first, report after: if this raises, the caller must
                # see a failure, not a log line claiming a removal that never
                # happened.
                if entry.path.is_symlink():
                    entry.path.unlink()
                else:
                    shutil.rmtree(entry.path)
                out(f"{agent}: removed {entry.path.name} (no longer in the store)")
        elif entry.status in ("stale-store", "foreign", "occupied"):
            if entry.status in ("foreign", "occupied") and entry.path.name in store_skill_names:
                out(f"{agent}: left alone {entry.path.name} ({entry.status}) — "
                    f"{entry.path.name} is therefore not installed")
            else:
                out(f"{agent}: left alone {entry.path.name} ({entry.status})")
        elif copy and not entry.path.is_symlink():
            # install_mode is per agent, not per entry: one --copy skill makes
            # every `ok` entry here a refresh candidate, including symlinks
            # from a mixed install. shutil.rmtree on a symlink raises OSError,
            # so only a real (non-symlink) `ok` directory is ever queued.
            refresh.add(entry.path)
            if dry_run:
                out(f"{agent}: would re-copy {entry.path.name}")

    for plan in installer.plan_agent(store, agent):
        # audit_agent already classified and reported this exact target above
        # (foreign/occupied entries are logged and left alone, never queued
        # into refresh); plan_agent's own classify() would call the same
        # target foreign/occupied again, and apply_plan raises RuntimeError
        # for both. Skipping here is what stops that raise from ever
        # happening — the except (OSError, RuntimeError) in relink() is only
        # a backstop for anything this skip does not anticipate.
        if plan.status in ("foreign", "occupied") and plan.target not in refresh:
            continue
        if plan.target in refresh:
            if dry_run:
                continue  # already reported above
            # One at a time, and only entries audit_agent proved are ours. A
            # copy must be removed before it can be rewritten; deleting all of
            # them up front would leave the agent with no skills at all for the
            # length of ten copytrees, where this window is one. It is the same
            # shape as apply_plan's own --force path: remove this target, write
            # this target.
            shutil.rmtree(plan.target)
            plan = plan._replace(status="create")  # it no longer exists
        for done, action in installer.apply_plan([plan], copy=copy, dry_run=dry_run):
            if action != "skipped":
                # apply_plan's own dry-run branch reports the same action verb
                # a real run would use ("linked", "copied", "replaced") — it
                # never learns dry_run itself, so the conditional voice has to
                # be added here, or this line would be the one place in an
                # otherwise all-"would" preview that claims the work is done.
                verb = f"would {action}" if dry_run else action
                out(f"{agent}: {verb} {done.target.name}")
```

A later review found two escapes this task's own tests never reached. The first: `apply_plan`
raises `RuntimeError` for a plan whose status is `foreign` or `occupied`, and the plan loop
above could still hand it one — an agent with `freya-code-graph` correctly linked plus a real
directory occupying `freya-status`'s target name (a name that exists in the store) produced
exactly that plan, and the crash surfaced as an uncaught traceback *after* the orphan removals
had already run. It is also self-perpetuating: a copytree that fails partway leaves a directory
without a marker, which then audits as `occupied` too, so every subsequent `freya update` would
crash the same way and never self-heal. The skip above is the actual fix — a plan whose status
audit_agent already reported must never reach `apply_plan` a second time; the widened
`except (OSError, RuntimeError)` is only the backstop for anything the skip does not anticipate.
The second: `install_mode` decides copy-vs-symlink once per agent, not per entry, so a single
`--copy` skill used to make every `ok` entry a refresh candidate — symlinks included — and
`shutil.rmtree` on a symlink raises `OSError`. The refresh decision now happens per entry
(`copy and not entry.path.is_symlink()`), so a mixed install only ever refreshes the copies.

Then wire it into `update()`. Immediately before `return 0` in the success path:

```python
    after = head(store, run=run)
    if after == before:
        out("already up to date")
    else:
        _, count = run(["rev-list", "--count", f"{before}..{after}"], store)
        out(f"updated {before[:8]} -> {after[:8]} ({count} commit(s))")
    relinked = relink(store, out=out)
    return 1 if relinked.failed else 0
```

`relink` runs even when nothing was fetched: an interrupted earlier run, or a skill added by
hand, leaves the same drift a pull would, and re-linking an already-linked store is a no-op.
A relink failure exits 1, not 0 — the fetch and merge did succeed, so it is not the same
refusal as a precondition (2), but `freya update && something-else` must not proceed as
though the install were whole.

The same review also caught the dry-run branch (Task 5) claiming to preview a re-link it never
actually called — the message said "freya update would fast-forward and re-link", but `update`
returned right after printing it. Immediately before `return 0` in the dry-run branch:

```python
        # The re-link preview runs against the store as it sits on disk right
        # now (dry_run never fetches or merges), which is the same limitation
        # the "would fast-forward" message above already has — it is still
        # the only preview of the re-link step a dry run can honestly give,
        # and a dry-run relink is guaranteed to write nothing.
        relinked = relink(store, dry_run=True, out=out)
        # An agent that could not be audited must fail a preview exactly as it
        # fails a real run — discarding the result here used to let a dry run
        # exit 0 over the same condition that exits 1 on the real path.
        return 1 if relinked.failed else 0
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_updater -v`
Expected: PASS, 32 tests.

- [ ] **Step 5: Mutation-check the pruning boundary**

1. In `_relink_agent`, extend the removal branch to `stale-store` as well as `orphan-skill`.
   Expected: no existing test fails — **this is a gap, close it.** Add to `RelinkTest`:

```python
    def test_a_stale_store_entry_is_never_removed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root, skills=("freya-status",))
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent))
            (agent / "freya-elsewhere").symlink_to(root / "other" / "skills" / "freya-elsewhere")
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                updater.relink(store, out=lambda _: None)
            self.assertTrue((agent / "freya-elsewhere").is_symlink())
```

   Re-run the mutation: it must now FAIL on that test. **Restore.**
2. In `relink`, delete the `if not any(... == "ok")` guard.
   Expected: FAIL on `test_an_agent_with_nothing_installed_is_left_alone` — update would
   silently install the suite for an agent the user never chose. **Restore.**
3. In `install_mode`, return `"symlink"` unconditionally.
   Expected: FAIL on `test_a_copy_install_is_refreshed_not_left_stale`. **Restore.**
4. In `_relink_agent`, drop the `plan._replace(status="create")` after the rmtree.
   Expected: FAIL on `test_a_copy_install_is_refreshed_not_left_stale` — the stale plan still
   says `ok`, so `apply_plan` skips it and the skill is deleted without being rewritten.
   **Restore.** (This is why the refresh re-labels the plan rather than trusting the status
   computed before the directory was removed.)
5. In `relink`, change `except OSError` to re-raise.
   Expected: FAIL on `test_a_failure_partway_is_reported_and_counted_not_raised`. **Restore.**

Re-run after restoring: PASS, 33 tests.

**A later review closed six further gaps.** Same drill — mutate, confirm the right test fails,
restore:

6. In `_relink_agent`'s plan loop, drop the `if plan.status in ("foreign", "occupied") and
   plan.target not in refresh: continue` line.
   Expected: `test_an_occupied_target_does_not_crash_relink` **errors** with an uncaught
   `RuntimeError` — this is the CRITICAL finding's crash, reproduced. **Restore.**
7. In `relink`, narrow `except (OSError, RuntimeError)` back to `except OSError`.
   Expected: no test fails alone — the skip above already stops the RuntimeError from ever being
   raised, so the backstop has nothing to catch under the current test suite. It is deliberately
   defense in depth, not a path any fixture can trigger honestly without reopening the skip
   itself. **Restore anyway** — it is still the second half of the CRITICAL fix.
8. In `_relink_agent`'s entries loop, widen `elif copy and not entry.path.is_symlink()` back to
   `elif copy:`.
   Expected: FAIL on `test_a_mixed_install_leaves_the_symlink_alone` — `shutil.rmtree` on the
   symlink raises `OSError`, `result.failed` becomes 1. **Restore.**
9. In `relink`, drop the `except (OSError, ValueError) as exc:` handling around `audit_agent`
   back to a silent `continue`.
   Expected: FAIL on `test_an_unreadable_agent_directory_is_reported_and_counted` — an agent
   whose skills directory turned unreadable vanished from the output instead of counting as a
   failure. **Restore.**
10. In `_relink_agent`, move the orphan-removal `out(...)` call back before the
    unlink/rmtree instead of after.
    Expected: FAIL on `test_a_failed_orphan_removal_is_not_reported_as_removed` — a removal that
    raises would still have been reported as done. **Restore.**
11. In `update`'s dry-run branch, delete the `relink(store, dry_run=True, out=out)` call.
    Expected: FAIL on `test_dry_run_previews_the_relink_without_writing_anything` — the "would
    re-copy" line the test asserts on is never printed, because dry-run silently skipped the
    re-link preview it claims to give. **Restore.**

Mutation 11 pins a test that lives in `UpdateTest` (Task 5's class), not `RelinkTest`.
`test_a_relink_failure_fails_an_otherwise_successful_update` and
`test_a_clean_relink_leaves_the_fast_forward_successful` went in alongside it, in the same
class, for the same reason: the wiring between `update()` and `relink()` — that a
`RelinkResult.failed` becomes `update()`'s own exit code — had no test at all before this
review.

**A further review closed two more gaps, both about mutation 11's own fix telling half the
truth.** `update`'s dry-run branch now calls `relink(store, dry_run=True, out=out)`, but that
call sat inside `_relink_agent`'s final `apply_plan` loop, which still printed the bare action
verb — `claude: linked freya-new` — under `dry_run=True`, exactly as it would after a real
link. Every sibling branch in `_relink_agent` already spoke in the conditional ("would remove",
"would re-copy"); this was the one line still speaking in the past tense, and it was the one a
user would see for the single most common case a preview exists to describe: a skill the store
gained that an agent does not yet have. Separately, `update`'s own dry-run branch discarded the
`RelinkResult` that call returns, so an agent that could not be audited during a preview still
exited 0 — the exact condition that exits 1 on the real path, one function away.

12. In `_relink_agent`'s final `apply_plan` loop, drop the `f"would {action}"` conditional and
    go back to printing the bare `action`.
    Expected: FAIL on `test_dry_run_reports_a_new_link_in_the_conditional_not_the_past_tense` —
    the preview reports `claude: linked freya-new` instead of speaking in the conditional voice
    the rest of the function uses. **Restore.**
13. In `update`'s dry-run branch, change `return 1 if relinked.failed else 0` back to a bare
    `return 0`.
    Expected: FAIL on `test_a_dry_run_relink_failure_fails_the_preview_too` — a preview whose
    relink could not be audited still exits 0, the one answer this command must never give for
    a condition that fails the real path. **Restore.**

Re-run after restoring all thirteen: PASS, 39 tests.

- [ ] **Step 6: Commit**

```bash
git add bin/updater.py bin/test_updater.py
git commit -F - <<'EOF'
feat(update): re-link after pulling, because a pull is not an install

A symlink picks up edits inside a skill for free, which makes it tempting to
believe a fast-forward finishes the job. It does not: a skill added to the
store has no link at all, one deleted leaves a dangling link behind, and a
--copy install tracks nothing whatsoever.

relink only ever touches agents that already have the suite — updating must not
install it somewhere the user never chose — and only ever removes entries
audit_agent has proved are ours. stale-store, foreign and occupied entries are
named in the output and left exactly where they are; a test now pins that,
after a mutation showed nothing was stopping the pruning branch from growing to
include them.

It runs even when the fetch changed nothing, since an interrupted earlier run
leaves the same drift a pull would, and re-linking a linked store is a no-op.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 7: The notify check, and wiring both commands into the CLI

**Files:**
- Modify: `bin/updater.py`, `bin/freya_cli.py`
- Test: `bin/test_updater.py`, `bin/test_freya_cli.py`

**Interfaces:**
- Produces: `state_path()`, `read_state(path)`, `write_state(path, data)`,
  `update_message(store, *, now, path=None, run=git, env=None) -> str | None`,
  `notify(store, *, stream=sys.stderr, now=None, **kw)`, and the constants `CHECK_INTERVAL`,
  `OPT_OUT`, `MESSAGE`.
- `freya update` reaches `updater.update`; `freya doctor` gains an `updates` check.

- [ ] **Step 1: Write the failing tests**

Append to `bin/test_updater.py`:

```python
class NotifyTest(unittest.TestCase):
    def _runner(self, calls, remote="bbbb", local="aaaa"):
        """A fake git that records what it was asked."""
        def run(args, cwd, timeout=None):
            calls.append(args[0])
            if args[0] == "rev-parse" and args[1] == "--show-toplevel":
                return 0, str(cwd)
            if args[0] == "rev-parse" and "@{u}" in args:
                return 0, "origin/main"
            if args[0] == "rev-parse":
                return 0, local
            if args[0] == "ls-remote":
                return 0, f"{remote}\trefs/heads/main"
            return 1, ""
        return run

    def test_a_moved_remote_produces_the_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            calls = []
            message = updater.update_message(root, now=1000.0, path=root / "state.json",
                                             run=self._runner(calls), env={})
            self.assertEqual(message, updater.MESSAGE)
            self.assertIn("ls-remote", calls)

    def test_a_fresh_cache_makes_no_network_call(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "state.json"
            updater.write_state(state, {"checked_at": 1000.0, "behind": True})
            calls = []
            message = updater.update_message(root, now=1001.0, path=state,
                                             run=self._runner(calls), env={})
            self.assertEqual(message, updater.MESSAGE)
            self.assertEqual(calls, [])

    def test_a_stale_cache_checks_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "state.json"
            updater.write_state(state, {"checked_at": 0.0, "behind": False})
            calls = []
            updater.update_message(root, now=updater.CHECK_INTERVAL + 1.0, path=state,
                                   run=self._runner(calls), env={})
            self.assertIn("ls-remote", calls)

    def test_an_unreachable_remote_is_silent_and_still_stamps_the_clock(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "state.json"

            def failing(args, cwd, timeout=None):
                if args[0] == "rev-parse" and args[1] == "--show-toplevel":
                    return 0, str(cwd)
                if args[0] == "rev-parse" and "@{u}" in args:
                    return 0, "origin/main"
                return 1, ""

            self.assertIsNone(updater.update_message(root, now=5000.0, path=state,
                                                     run=failing, env={}))
            self.assertEqual(updater.read_state(state)["checked_at"], 5000.0)

    def test_the_opt_out_skips_everything(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            calls = []
            message = updater.update_message(root, now=1000.0, path=root / "state.json",
                                             run=self._runner(calls),
                                             env={updater.OPT_OUT: "1"})
            self.assertIsNone(message)
            self.assertEqual(calls, [])

    def test_a_non_git_store_is_silent(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertIsNone(updater.update_message(
                root, now=1000.0, path=root / "state.json",
                run=lambda *a, **k: (1, ""), env={}))

    def test_a_corrupt_state_file_is_treated_as_no_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "state.json"
            state.write_text("{not json", encoding="utf-8")
            self.assertEqual(updater.read_state(state), {})

    def test_notify_swallows_anything_the_check_raises(self):
        class Boom:
            def get(self, *_a, **_k):
                raise RuntimeError("boom")

        stream = io.StringIO()
        self.assertIsNone(updater.notify(Path("/nonexistent"), stream=stream,
                                         now=1.0, env=Boom()))
        self.assertEqual(stream.getvalue(), "")
```

Add `import io` to `bin/test_updater.py`.

Append to `bin/test_freya_cli.py`:

```python
class NotifyWiringTest(unittest.TestCase):
    def test_an_exploding_notify_does_not_change_the_exit_code(self):
        def boom(*_a, **_k):
            raise RuntimeError("boom")

        with unittest.mock.patch("updater.notify", boom):
            out, err = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = freya_cli.main(["definitely-not-a-command"])
        self.assertEqual(code, 2)

    def test_the_notice_is_not_printed_for_update_itself(self):
        seen = []
        with unittest.mock.patch("updater.notify", lambda *a, **k: seen.append(a)):
            with unittest.mock.patch("updater.update", return_value=0):
                out, err = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                    freya_cli.main(["update"])
        self.assertEqual(seen, [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_updater test_freya_cli -v`
Expected: errors for `update_message`, `notify`, and an unknown `update` command.

- [ ] **Step 3: Implement the check**

Add `import json`, `import sys`, `import time` and `import traceback` to `bin/updater.py`,
then append:

```python
#: Where the throttle lives. One file, one job: when we last asked, and what we
#: were told. Deliberately outside any agent's directory — the answer is about
#: the store, not about an agent.
STATE_DIR = Path.home() / ".freya"
STATE_FILE = "update-check.json"
CHECK_INTERVAL = 24 * 60 * 60
OPT_OUT = "FREYA_NO_UPDATE_CHECK"
#: Opt-in traceback for the one code path that is designed to fail silently.
DEBUG = "FREYA_DEBUG"
MESSAGE = "freya: an update is available — run `freya update`"


def state_path():
    return STATE_DIR / STATE_FILE


def read_state(path):
    """The throttle state, or {} for anything unreadable or malformed."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_state(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh)


def update_message(store, *, now, path=None, run=git, env=None):
    """The one-line notice to print, or None.

    Notify-only, and throttled: at most one network call a day, bounded by
    ls-remote's short timeout. A failure stamps the clock exactly like a success
    does, so an offline machine goes quiet for a day instead of paying the
    timeout on every single command.
    """
    env = os.environ if env is None else env
    if env.get(OPT_OUT):
        return None
    path = state_path() if path is None else Path(path)
    state = read_state(path)
    try:
        checked_at = float(state.get("checked_at", 0))
    except (TypeError, ValueError):
        checked_at = 0.0
    if now - checked_at < CHECK_INTERVAL:
        return MESSAGE if state.get("behind") else None

    behind = False
    if is_git_store(store, run=run):
        tracking = upstream(store, run=run)
        if tracking:
            remote = remote_head(store, tracking, run=run)
            local = head(store, run=run)
            behind = bool(remote and local and remote != local)
    write_state(path, {"checked_at": now, "behind": behind})
    return MESSAGE if behind else None


def notify(store, *, stream=sys.stderr, now=None, env=None, **kwargs):
    """Print the update notice, if there is one. Swallows everything.

    The only bare `except` in the suite, and it is the correct one: a
    notification that can break the command it precedes is worse than no
    notification. It writes to stderr so stdout stays parseable for the agent
    that invoked the command.

    The write is *inside* the guard, not after it: a BrokenPipeError on stderr
    would otherwise escape a function whose whole contract is that nothing
    escapes. And because a permanently broken check is otherwise
    indistinguishable from "no update available" forever, FREYA_DEBUG prints
    the traceback — opt-in, so the default path stays silent.
    """
    env = os.environ if env is None else env
    try:
        message = update_message(store, now=time.time() if now is None else now,
                                 env=env, **kwargs)
        if message:
            stream.write(message + "\n")
        return message
    except Exception:  # noqa: BLE001 - see docstring
        # os.environ, not `env`: the injected mapping is a plausible source of
        # the exception we are already handling, and the recovery path must not
        # be able to raise the same failure a second time.
        if os.environ.get(DEBUG):
            traceback.print_exc(file=stream)
        return None
```

Add two tests to `NotifyTest`, pinning both corrections:

```python
    def test_a_broken_stderr_cannot_escape(self):
        class Unwritable:
            def write(self, _):
                raise BrokenPipeError("stderr is gone")

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            self.assertIsNone(updater.notify(root, stream=Unwritable(), now=1000.0,
                                             path=root / "state.json",
                                             run=self._runner([]), env={}))

    def test_debug_makes_a_silent_failure_visible(self):
        class Boom:
            def get(self, *_a, **_k):
                raise RuntimeError("boom")

        stream = io.StringIO()
        with unittest.mock.patch.dict(os.environ, {updater.DEBUG: "1"}):
            updater.notify(Path("/nonexistent"), stream=stream, now=1.0, env=Boom())
        self.assertIn("RuntimeError", stream.getvalue())
```

`bin/test_updater.py` needs `import os` for the second test.

- [ ] **Step 4: Implement the CLI wiring**

In `bin/freya_cli.py`, add `import os` to the imports and this constant near `MANIFEST_NAME`:

```python
#: Commands the update notice must not precede: `help` is the first thing a new
#: user runs, and the other three are the ones that would act on the notice.
NO_NOTIFY = frozenset({"help", "-h", "--help", "update", "install", "uninstall"})
```

In `main`, after `name, rest = argv[0], argv[1:]` and before the dispatch chain:

```python
        if name not in NO_NOTIFY:
            try:
                import updater

                updater.notify(suite_root())
            except Exception:  # noqa: BLE001
                # notify() already swallows its own failures; this covers the
                # import itself, so a broken or missing updater module can never
                # be the reason a working command fails.
                pass
```

and add the dispatch, next to the existing `doctor` branch:

```python
        if name == "update":
            import updater

            return updater.update(suite_root(), dry_run="--dry-run" in rest)
```

> `init` is **not** wired here. `bin/agents_md.py` does not exist until Task 9, and a
> dispatch branch that raises `ModuleNotFoundError` is worse than an unknown command. Task 9
> adds it.

Extend `format_help`'s built-in list:

```python
    lines += [
        "",
        "Built-ins:",
        "  doctor    Check that the installation is healthy",
        "  install   Install the suite for an agent (--uninstall to remove)",
        "  update    Fast-forward the store and re-link (--dry-run to preview)",
        "  init      Write a freya-devkit section into a project's AGENTS.md",
        "  help      Show this message",
        ...
```

Add the `updates` check to `doctor_checks`, after the `orphaned entries` check:

```python
    import updater

    if os.environ.get(updater.OPT_OUT):
        checks.append(("updates", "ok", f"not checked ({updater.OPT_OUT} is set)"))
    elif not updater.is_git_store(root):
        checks.append(("updates", "warn",
                       "the store is not a git checkout — `freya update` cannot run"))
    else:
        # Unthrottled on purpose: a diagnostic that reports a cached answer is
        # not diagnosing anything.
        tracking = updater.upstream(root)
        remote = updater.remote_head(root, tracking) if tracking else None
        if tracking is None:
            checks.append(("updates", "warn", "this branch has no upstream"))
        elif remote is None:
            checks.append(("updates", "warn", f"could not reach {tracking.partition('/')[0]}"))
        elif remote == updater.head(root):
            checks.append(("updates", "ok", f"up to date with {tracking}"))
        else:
            checks.append(("updates", "warn", f"{tracking} has moved — run `freya update`"))
```

- [ ] **Step 5: Stop a completed update from re-announcing itself**

`update()` runs before the state file knows anything changed, so the next command would
consult a cache that still says "behind" and print the notice to someone who just updated.
Add a test to `test_updater.py`:

```python
@unittest.skipUnless(HAS_GIT, "git is not installed")
class UpdateStampsTheCheckTest(unittest.TestCase):
    def test_a_successful_update_clears_a_stale_behind_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, work, store = make_origin(root)
            state = root / "state.json"
            updater.write_state(state, {"checked_at": 1000.0, "behind": True})
            advance(work)
            updater.update(store, out=lambda _: None, state=state)
            self.assertFalse(updater.read_state(state)["behind"])
```

Give `update()` the parameter and the write, at the end of the success path (after `relink`):

```python
def update(store, *, dry_run=False, out=print, run=git, state=None):
```

```python
    relinked = relink(store, out=out)
    # The cache still says "behind" from before this ran; leaving it would greet
    # the user's next command with a notice about the update they just applied.
    write_state(state_path() if state is None else state,
                {"checked_at": time.time(), "behind": False})
    return 1 if relinked.failed else 0
```

Run: `cd bin && python3 -m unittest test_updater.UpdateStampsTheCheckTest -v`
Expected: PASS.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_updater test_freya_cli test_installer -v`
Expected: PASS.

Run: `./bin/freya help`
Expected: `update` and `init` appear under Built-ins.

Run: `FREYA_NO_UPDATE_CHECK=1 ./bin/freya doctor; echo "exit=$?"`
Expected: exit 0, with `[ok] updates: not checked (FREYA_NO_UPDATE_CHECK is set)`.

- [ ] **Step 7: Mutation-check the guarantees**

1. In `update_message`, move the `write_state` call inside an `if behind:` branch.
   Expected: FAIL on `test_an_unreachable_remote_is_silent_and_still_stamps_the_clock`
   (and the machine would pay the 2s timeout on every command, forever). **Restore.**
2. In `update_message`, delete the throttle comparison.
   Expected: FAIL on `test_a_fresh_cache_makes_no_network_call`. **Restore.**
3. In `notify`, narrow `except Exception` to `except OSError`.
   Expected: FAIL on `test_notify_swallows_anything_the_check_raises`. **Restore.**
3b. In `notify`, move `stream.write(...)` back outside the `try`.
   Expected: FAIL on `test_a_broken_stderr_cannot_escape`. **Restore.**
4. In `freya_cli.main`, remove `"update"` from `NO_NOTIFY`.
   Expected: FAIL on `test_the_notice_is_not_printed_for_update_itself`. **Restore.**

**A later review closed one CRITICAL, two IMPORTANT and four MINOR gaps.** The CRITICAL one was
in the tests, not the production code: wiring `notify()` into `freya_cli.main` (Step 4 above)
silently changed four existing tests in `test_freya_cli.py` — `test_unknown_command_exits_2_with_stderr_hint`,
`test_returns_child_exit_code_for_known_command`, `test_main_dispatches_the_doctor_builtin` and
`test_main_propagates_doctor_failure_exit_code` — that call `freya_cli.main([...])` with a command
name outside `NO_NOTIFY` and never patched `updater.notify`. Unpatched, that call is real: it
writes `~/.freya/update-check.json` for real and runs a real `git ls-remote`, which is confirmed
on disk — the file existed on the review machine with an mtime matching a test run. `MainTest._run`
now patches `updater.notify` to a no-op, and the two `main(["doctor"])` tests that bypass `_run`
gained the same patch directly; `test_main_dispatches_the_doctor_builtin` additionally patches
`updater.git`, because `doctor()`'s own `updates` check (Step 4 above) is unthrottled by design
and has no other seam once `main()` calls it with no arguments. A second, related escape surfaced
during the audit this finding demanded: `UpdateTest._run` in `test_updater.py` (Task 5) never
passed `state=` to `updater.update`, so every successful fast-forward in that class stamped the
real throttle file too, once the write-state call (Step 5 above) existed to stamp anything. It now
defaults `state=` to a path inside the fixture's own temp directory. Every test in both files that
calls `freya_cli.main`, `doctor_checks`, `doctor`, `updater.update` or `updater.notify` was
re-audited by name for a real-home or network reach; the ones that legitimately exercise the real
checkout (`test_healthy_checkout_reports_ok` and its siblings) keep doing so, but now inject an
`_offline_git` stand-in for the `updates` check's git calls so that reach stops at reading this
repository's own files and never becomes a network call.

The two IMPORTANT gaps were both in production code. First: the `write_state` call at the end of
`update()`'s success path (Step 5 above) was unguarded, so an unwritable `$HOME` raised `OSError`
*after* the fetch and re-link had already succeeded — `freya_cli.main` caught it and reported
"freya: cannot read the command manifest", exit 2, misreporting a working update as broken.

```python
    relinked = relink(store, out=out)
    # The cache still says "behind" from before this ran; leaving it would greet
    # the user's next command with a notice about the update they just applied.
    try:
        write_state(state_path() if state is None else state,
                    {"checked_at": time.time(), "behind": False})
    except OSError:
        # A throttle stamp must never fail an update that already succeeded —
        # the fast-forward and re-link above are done by this point, and an
        # unwritable $HOME here just means the next command re-checks a day
        # early, not that this update gets reported as broken.
        pass
    return 1 if relinked.failed else 0
```

Second: `doctor_checks`'s `updates` block (Step 4 above) called `updater.is_git_store` /
`upstream` / `remote_head` / `head` with no injection point at all, so any test calling
`doctor_checks()` — including ones with no interest in the `updates` check — reached the real
network. `run=` now threads through, defaulting to `updater.git`:

```python
def doctor_checks(root=None, targets=None, run=None):
    ...
    import updater

    # `run` threads through every git call this check makes, defaulting to
    # updater.git — the injection point that lets a test exercise this whole
    # ladder (up to date / moved / no upstream / unreachable / not a checkout)
    # without ever reaching the real network.
    git_run = updater.git if run is None else run

    if os.environ.get(updater.OPT_OUT):
        checks.append(("updates", "ok", f"not checked ({updater.OPT_OUT} is set)"))
    elif not updater.is_git_store(root, run=git_run):
        checks.append(("updates", "warn",
                       "the store is not a git checkout — `freya update` cannot run"))
    else:
        tracking = updater.upstream(root, run=git_run)
        if tracking is None:
            checks.append(("updates", "warn", "this branch has no upstream"))
        else:
            remote = updater.remote_head(root, tracking, run=git_run)
            if remote is None:
                checks.append(("updates", "warn",
                               f"could not reach {tracking.partition('/')[0]}"))
            elif remote == updater.head(root, run=git_run):
                checks.append(("updates", "ok", f"up to date with {tracking}"))
            else:
                checks.append(("updates", "warn", f"{tracking} has moved — run `freya update`"))
```

`doctor(root=None, run=None)` threads the same parameter into `doctor_checks`. A new
`DoctorUpdatesCheckTest` in `test_freya_cli.py` drives the whole ladder through an injected
runner — up to date, remote moved, no upstream, unreachable remote, not a git checkout, and the
opt-out short-circuiting before any git call at all — none of it touching the network.

The four MINOR gaps, each a small production fix with its own test:

- `update_message`'s freshness check compared `now - checked_at < CHECK_INTERVAL` without a floor,
  so a `checked_at` in the future — clock skew, or a hand-edited state file — produced a negative
  difference that is always less than `CHECK_INTERVAL`, reading as permanently fresh and silencing
  the check forever. The comparison is now `0 <= now - checked_at < CHECK_INTERVAL`.
  `test_a_future_checked_at_checks_again_instead_of_going_silent_forever` pins it.
- `notify`'s signature bound `stream=sys.stderr` at import time, so `contextlib.redirect_stderr`
  wrapped around a call made later could never capture the notice — the write still went to
  whatever object `sys.stderr` was when `updater.py` was first imported. `stream` now defaults to
  `None` and is resolved inside the body. `test_the_default_stream_is_resolved_at_call_time_not_import_time`
  pins it.
- `doctor` was not in `NO_NOTIFY`, so `freya doctor` paid for two remote calls on one diagnostic:
  the throttled notice first, then its own unthrottled `updates` check.

  ```python
  #: Commands the update notice must not precede: `help` is the first thing a new
  #: user runs, `update`/`install`/`uninstall` are the ones that would act on the
  #: notice, and `doctor` asks the update question itself, unthrottled — running
  #: the throttled notice first would pay for two remote calls on one diagnostic.
  NO_NOTIFY = frozenset({"help", "-h", "--help", "update", "install", "uninstall", "doctor"})
  ```

  `test_the_notice_is_not_printed_for_doctor_either` pins it, mirroring the existing `update` test.
- The dispatch test `"--dry-run" in rest` matched `--dry-run=1` too (and any other argument), so
  a typo silently ran a real update instead of refusing. `update` now rejects anything that is not
  exactly `[]` or `["--dry-run"]`:

  ```python
          if name == "update":
              # Exact match only: `"--dry-run" in rest` used to also match
              # `--dry-run=1` (and any other argument), so an argument no one
              # meant as a real run silently ran one.
              if rest not in ([], ["--dry-run"]):
                  sys.stderr.write("usage: freya update [--dry-run]\n")
                  return 2
              import updater

              return updater.update(suite_root(), dry_run=rest == ["--dry-run"])
  ```

  A new `UpdateDispatchTest` covers `--dry-run=1`, an unknown flag, plain `--dry-run`, and no
  arguments at all.

Continuing the mutation drill above:

5. In `update`, remove the `try`/`except OSError` around `write_state` and simulate an unwritable
   `$HOME` by patching `updater.write_state` to raise `OSError`.
   Expected: FAIL on `test_a_failing_write_state_does_not_change_updates_return_code` — the
   already-successful update reports exit 2 instead of 0. **Restore.**
6. In `update_message`, drop the `0 <=` half of the freshness comparison.
   Expected: FAIL on `test_a_future_checked_at_checks_again_instead_of_going_silent_forever`.
   **Restore.**
7. In `notify`, put `stream=sys.stderr` back in the signature.
   Expected: FAIL on `test_the_default_stream_is_resolved_at_call_time_not_import_time` — the
   notice no longer appears inside the `contextlib.redirect_stderr` block. **Restore.**
8. In `freya_cli`, remove `"doctor"` from `NO_NOTIFY`.
   Expected: FAIL on `test_the_notice_is_not_printed_for_doctor_either`. **Restore.**
9. In `freya_cli.main`'s `update` dispatch, put `"--dry-run" in rest` back.
   Expected: FAIL on `test_dry_run_with_a_value_is_rejected_not_silently_run_for_real` — a real
   update runs for `--dry-run=1`. **Restore.**

Re-run after restoring all nine: PASS.

**A second review, after this task had already shipped, found one IMPORTANT gap and two MINOR
ones — none in the notify/update logic itself, all in how the tests around it were built.**

The IMPORTANT one was a hollow guard: the fix for the CRITICAL gap above (`MainTest._run` patching
`updater.notify` to a no-op) quietly removed the last test that exercised the `if name not in
NO_NOTIFY:` block in `freya_cli.main` at all. Every remaining test touching that block is negative
— asserting the notice is *not* printed for `update`, `install`, `doctor` — or checks only an exit
code. Deleting the entire block left all 187 tests in the suite green; this repo has a recorded
lesson about exactly this shape (a guard whose test passes without the guard), and this was another
instance of it. `NotifyWiringTest` gained a positive case:

```python
    def test_the_notice_precedes_an_ordinary_command(self):
        seen = []
        with unittest.mock.patch("updater.notify", lambda *a, **k: seen.append(a)):
            with unittest.mock.patch.object(freya_cli, "run_command", return_value=0):
                freya_cli.main(["code-graph"])
        self.assertEqual(seen, [(freya_cli.suite_root(),)])
```

Deleting the block and re-running confirms this is the one test that fails, with:
`AssertionError: Lists differ: [] != [(PosixPath('.../freya-devkit'),)]`.

The two MINOR ones were read-path escapes, not write-path ones — nothing here ever touched the real
`~/.freya`, but two things still consulted the real `~/.claude` or spawned real subprocesses that a
test has no business needing. First, the `duplicate install` check (documented as deliberately left
alone in Task 2's note above) called `installer.plan_agent(root, "claude")` with no `target_dir`,
so any `doctor_checks(targets=...)` call — the whole point of which is that a test never touches the
real home — still read the real `~/.claude` through this one check. It now honours `targets` the
same way the `agents` loop above it already does, and is skipped entirely when the caller has no
interest in `"claude"`:

```python
    if targets is None or "claude" in targets:
        claude_target_dir = None if targets is None else targets.get("claude")
        plugin_dir = Path.home() / ".claude" / "plugins" / "marketplaces" / "freya-devkit"
        try:
            personally_installed = any(
                p.status == "ok"
                for p in installer.plan_agent(root, "claude", target_dir=claude_target_dir)
            )
        except (OSError, ValueError):
            personally_installed = False
        both = plugin_dir.is_dir() and personally_installed
        ...
```

Second, several `doctor_checks(root=<tmp>)` calls in `test_freya_cli.py` passed no `run=`, so a real
`git rev-parse` ran against a temp directory on every suite run — harmless (the store is never a git
checkout, so `is_git_store` short-circuits before anything reaches `ls-remote`), but it made the
suite depend on git being installed and on subprocess timing for no reason. Each now passes the
existing `_offline_git` stand-in, unchanged in what it asserts.

- [ ] **Step 8: Commit**

```bash
git add bin/updater.py bin/freya_cli.py bin/test_updater.py bin/test_freya_cli.py
git commit -F - <<'EOF'
feat(update): notify-only staleness check, and freya update on the CLI

At most one ls-remote a day, bounded by a 2s timeout, printed to stderr so
stdout stays parseable for the agent that ran the command. It never applies
anything: a toolkit that gates wrap-up must not change under a running task.

Three properties are pinned by mutation checks rather than left to good
intentions. A failed check stamps the clock exactly like a successful one, or
an offline machine pays the timeout on every command forever. The throttle is
what makes it a daily notice instead of a per-invocation network call. And
notify()'s bare `except Exception` is deliberate and tested — a notification
that can break the command it precedes is worse than no notification.

doctor asks the same question unthrottled, because a diagnostic reporting a
cached answer is not diagnosing anything.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 8: `frontmatter_value()` — read the block scalars every SKILL.md actually uses

**Files:**
- Modify: `bin/check_skill_conformance.py`
- Test: `bin/test_check_skill_conformance.py`

**Interfaces:**
- Produces: `frontmatter_value(lines, key) -> str | None`, handling both an inline scalar and
  a `|`/`>` block scalar. `frontmatter_name(lines)` becomes a one-line wrapper, so the parser
  lives in exactly one place. Task 9 consumes it.

- [ ] **Step 1: Write the failing tests**

Append to `bin/test_check_skill_conformance.py`:

```python
class FrontmatterValueTest(unittest.TestCase):
    def test_reads_an_inline_value(self):
        lines = ["---", "name: freya-status", "description: short", "---"]
        self.assertEqual(check_skill_conformance.frontmatter_value(lines, "description"),
                         "short")

    def test_reads_a_block_scalar(self):
        lines = ["---", "name: freya-status", "description: |",
                 "  First line.", "  Second line.", "---", "body"]
        self.assertEqual(check_skill_conformance.frontmatter_value(lines, "description"),
                         "First line.\nSecond line.")

    def test_a_block_scalar_stops_at_the_next_key(self):
        lines = ["---", "description: |", "  Only this.", "license: MIT", "---"]
        self.assertEqual(check_skill_conformance.frontmatter_value(lines, "description"),
                         "Only this.")

    def test_strips_one_layer_of_quoting(self):
        lines = ["---", 'name: "freya-status"', "---"]
        self.assertEqual(check_skill_conformance.frontmatter_value(lines, "name"),
                         "freya-status")

    def test_an_absent_key_is_none(self):
        lines = ["---", "name: freya-status", "---"]
        self.assertIsNone(check_skill_conformance.frontmatter_value(lines, "description"))

    def test_the_real_skills_all_have_a_readable_description(self):
        root = Path(__file__).resolve().parents[1]
        for skill in sorted((root / "skills").iterdir()):
            md = skill / "SKILL.md"
            if not md.is_file():
                continue
            lines = md.read_text(encoding="utf-8").splitlines()
            value = check_skill_conformance.frontmatter_value(lines, "description")
            self.assertTrue(value and value not in ("|", ">"), f"{skill.name}: {value!r}")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_check_skill_conformance -v`
Expected: 6 errors — no `frontmatter_value`.

- [ ] **Step 3: Implement**

In `bin/check_skill_conformance.py`, replace `frontmatter_name` with:

```python
def frontmatter_value(lines, key):
    """Return a top-level frontmatter value, or None if the key is absent.

    Handles both forms this repo uses. `name:` is an inline scalar; every
    `description:` is a block scalar (`|` followed by indented lines), which a
    reader written only for inline values reports as the literal "|" — ten empty
    table cells, and nothing to tell you why.

    One layer of YAML quoting is stripped: some formatters add it on their own,
    and a quoted name must not read as a mismatch against its directory.
    """
    if not lines or lines[0].strip() != "---":
        return None
    prefix = key + ":"
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return None
        if not line.startswith(prefix):
            continue
        value = line.split(":", 1)[1].strip()
        if value not in ("|", "|-", ">", ">-"):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            return value
        body = []
        for follow in lines[index + 1:]:
            if follow.strip() == "---":
                break
            if follow.strip() and not follow.startswith((" ", "\t")):
                break  # an unindented line ends the block: it is the next key
            body.append(follow.strip())
        return "\n".join(body).strip()
    return None


def frontmatter_name(lines):
    """Return the value of the top-level `name:` key, or None if absent."""
    return frontmatter_value(lines, "name")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_check_skill_conformance -v`
Expected: PASS, including every pre-existing R8 test that depends on `frontmatter_name`.

Run: `python3 bin/check_skill_conformance.py; echo "exit=$?"`
Expected: `skill layer is conformant.`, exit 0.

- [ ] **Step 5: Commit**

```bash
git add bin/check_skill_conformance.py bin/test_check_skill_conformance.py
git commit -F - <<'EOF'
feat(conformance): frontmatter_value reads block scalars, not just inline ones

frontmatter_name only ever needed inline values, because `name:` is always
inline. Every `description:` in the repo is a block scalar, so generalizing the
old reader would have returned the literal "|" for all ten skills — and the
AGENTS.md table that consumes it would have shipped ten empty cells with
nothing to indicate why.

frontmatter_name becomes a wrapper so there is still exactly one frontmatter
parser. A test reads all ten real SKILL.md files and asserts each yields a
description that is neither empty nor a block-scalar marker, which is the check
that would have caught this had it existed before.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 9: `freya init` — the AGENTS.md block

**Files:**
- Create: `bin/agents_md.py`
- Test: `bin/test_agents_md.py`
- Modify: `bin/freya_cli.py` (the `init` dispatch deferred from Task 7)

**Interfaces:**
- Consumes: `installer.discover_skills`, `check_skill_conformance.frontmatter_value`.
- Produces: `BEGIN`, `END`, `first_sentence(text)`, `skill_rows(store)`,
  `render_block(store, newline="\n")`, `merge(existing, block, newline="\n")`,
  `init(store, project, *, dry_run=False, out=print) -> int`.

> **Addendum (phase 4b/5 review, 2026-08-14):** the version below is what actually shipped
> after a review found eight problems with the first pass — a CRLF file silently rewritten
> to LF, `--dry-run=1` performing a real write, an `OSError` misreported as a broken command
> manifest, a vacuous pipe-escaping assertion, marker matching that trusted the first
> occurrence of `BEGIN`/`END` wherever it appeared (including in the user's own prose), a
> whitespace-only file treated as empty, `first_sentence` truncating at "e.g.", and several
> test gaps. The code and test blocks below are the corrected versions; the mutation list
> at the end has been updated to match (mutation 3's original "Expected: FAIL" was wrong —
> see the note there).
>
> **Addendum 2 (phase 4b review, 2026-08-14):** a follow-up review found the marker fix from
> the first addendum was itself over-strict — it counted a marker *anywhere* in the file,
> so a user documenting freya-devkit in their own `AGENTS.md` (a sentence naming the marker,
> a fenced example showing it) locked themselves out of `freya init` forever with "malformed
> ... block" for a file that was not malformed. `_locate_marker` now considers only
> start-of-line occurrences; a mid-line mention is ignored rather than counted as ambiguity,
> and `merge`'s append fast-path is gated on that same start-of-line count. Two genuine
> markers at line start still refuse — that protection survives. Also fixed: `_write_target`
> used to `open(target, "w")`, which truncates before writing a byte, so a failure mid-write
> left the file empty instead of intact; it now writes to a sibling temp file and
> `os.replace`s it into place. And `init`'s `except OSError` used to wrap `render_block` too,
> so a broken SKILL.md in the store was reported as a fault in the project's AGENTS.md; the
> try now covers only the read and write of the target file. The code and test blocks below
> reflect all of this.
>
> **Addendum 3 (final review fix wave, 2026-08-14):** Addendum 2 scoped the try/except around
> `merge(render_block(...))` down to only the read and write of the target file — correct —
> but left it catching only `ValueError`, and `render_block → skill_rows` reads `SKILL.md`
> files from the *store*, which can raise `OSError` (permissions, a deleted file mid-read).
> That let an `OSError` there escape `init` entirely, past `freya_cli.main`'s own `except
> (OSError, ValueError)`, and get reported as "cannot read the command manifest" — the third
> time this phase found the same "only one of the two exception types is caught" shape (the
> first two are Addendum 1's manifest/scripts checks and Addendum 2's marker/write-target
> fixes above). The except now catches `(OSError, ValueError)` and names the store, not the
> project's `AGENTS.md`. Separately, `_write_target`'s `os.replace` could clobber a symlinked
> `AGENTS.md` with a plain file (`os.replace` does not follow symlinks) and reset a
> pre-existing file's permissions to the umask default; it now resolves the target before
> writing and `shutil.copystat`s the original's mode onto the temp file first. The code block
> below is the corrected version; `import shutil` was added to the module header for it.

- [ ] **Step 1: Write the failing tests**

Create `bin/test_agents_md.py`:

```python
#!/usr/bin/env python3
"""Unit tests for the AGENTS.md writer."""

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents_md

BLOCK_SCALAR = """---
name: {name}
description: |
  {summary} And a second sentence that must not appear.
  TRIGGER when: noise, noise, noise.
---
"""


def make_store(tmp, skills=(("freya-status", "Report where a project stands."),)):
    store = Path(tmp).resolve() / "store"
    (store / "bin").mkdir(parents=True)
    for name, summary in skills:
        d = store / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(BLOCK_SCALAR.format(name=name, summary=summary),
                                    encoding="utf-8")
    return store


class RenderTest(unittest.TestCase):
    def test_a_row_carries_only_the_first_sentence(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            block = agents_md.render_block(store)
            self.assertIn("| `freya-status` | Report where a project stands. |", block)
            self.assertNotIn("must not appear", block)
            self.assertNotIn("TRIGGER", block)

    def test_the_block_is_delimited_by_both_markers(self):
        with tempfile.TemporaryDirectory() as tmp:
            block = agents_md.render_block(make_store(tmp))
            self.assertTrue(block.startswith(agents_md.BEGIN))
            self.assertIn(agents_md.END, block)

    def test_a_pipe_in_a_description_cannot_break_the_table(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp, skills=(("freya-status", "Reports a | b."),))
            row = [ln for ln in agents_md.render_block(store).splitlines()
                   if "freya-status" in ln][0]
            # Asserting the *escaped* sequence is present is the only form
            # that actually fails if `.replace("|", r"\|")` is removed: a
            # bare `row.count("|") == 4` holds either way, since escaping
            # adds a backslash without deleting the pipe it precedes.
            self.assertIn(r"Reports a \| b.", row)
            # "Reports a | b." ends in a single-letter token ("b") followed
            # by a period — `first_sentence` used to mistake that for an
            # initial and run the fixture's second sentence on.
            self.assertNotIn("must not appear", row)

    def test_first_sentence_does_not_break_on_abbreviations(self):
        text = ("Handles config files (e.g. YAML, JSON) for setup. "
                "It also validates the schema.")
        self.assertEqual(
            agents_md.first_sentence(text),
            "Handles config files (e.g. YAML, JSON) for setup.",
        )

    def test_first_sentence_ends_at_a_single_letter_token_followed_by_a_capital(self):
        # The token before the period is a single letter ("b") and the next
        # word starts with a capital ("And") — a new sentence, not more of a
        # name, so this must terminate here rather than run on.
        text = "Reports a | b. And a second sentence that must not appear."
        self.assertEqual(agents_md.first_sentence(text), "Reports a | b.")

    def test_first_sentence_treats_a_single_letter_before_a_lowercase_word_as_an_initial(self):
        # The token before the period is a single letter ("a") and the next
        # word is lowercase ("b") — more of the same sentence, as in an
        # initial like "J. Smith" — so this must NOT terminate here.
        text = "See note a. b for details. This must not appear."
        self.assertEqual(agents_md.first_sentence(text), "See note a. b for details.")


class MergeTest(unittest.TestCase):
    def test_an_empty_file_becomes_the_block(self):
        self.assertEqual(agents_md.merge("", "BLOCK\n"), "BLOCK\n")

    def test_existing_prose_is_appended_to_never_rewritten(self):
        merged = agents_md.merge("# My project\n\nNotes.\n",
                                 f"{agents_md.BEGIN}\nx\n{agents_md.END}\n")
        self.assertTrue(merged.startswith("# My project\n\nNotes.\n"))
        self.assertIn(agents_md.BEGIN, merged)

    def test_a_second_run_produces_no_diff(self):
        block = f"{agents_md.BEGIN}\nx\n{agents_md.END}\n"
        once = agents_md.merge("# Mine\n", block)
        self.assertEqual(agents_md.merge(once, block), once)

    def test_the_block_is_replaced_in_place_leaving_both_sides_intact(self):
        old = f"before\n\n{agents_md.BEGIN}\nold\n{agents_md.END}\n\nafter\n"
        merged = agents_md.merge(old, f"{agents_md.BEGIN}\nnew\n{agents_md.END}\n")
        self.assertIn("new", merged)
        self.assertNotIn("old", merged)
        self.assertTrue(merged.startswith("before\n"))
        self.assertTrue(merged.endswith("after\n"))

    def test_an_unpaired_marker_refuses(self):
        with self.assertRaises(ValueError):
            agents_md.merge(f"text\n{agents_md.BEGIN}\nno end\n", "BLOCK\n")

    def test_reversed_markers_refuse(self):
        with self.assertRaises(ValueError):
            agents_md.merge(f"{agents_md.END}\nx\n{agents_md.BEGIN}\n", "BLOCK\n")

    def test_a_whitespace_only_file_is_not_discarded(self):
        # `if not existing.strip(): return block` used to treat a file of
        # pure whitespace as if it were empty, discarding those bytes.
        merged = agents_md.merge("   \n", f"{agents_md.BEGIN}\nx\n{agents_md.END}\n")
        self.assertTrue(merged.startswith("   \n"))
        self.assertIn(agents_md.BEGIN, merged)

    def test_a_prose_mention_updates_the_real_block_and_leaves_prose_untouched(self):
        # A file where someone documents freya-devkit and mentions the BEGIN
        # marker in prose, with a real block lower down. The prose mention
        # is mid-line, not at the start of a line — it is not a candidate
        # for the real marker, so it is ignored rather than counted as a
        # duplicate. Treating it as a duplicate used to refuse forever: the
        # user's file is not malformed, only ours was over-strict, and there
        # was no escape hatch.
        prose = f"We use {agents_md.BEGIN} to mark the managed region.\n\n"
        old_block = f"{agents_md.BEGIN}\nold\n{agents_md.END}\n"
        new_block = f"{agents_md.BEGIN}\nnew\n{agents_md.END}\n"
        merged = agents_md.merge(prose + old_block, new_block)
        self.assertTrue(merged.startswith(prose))
        self.assertIn("new", merged)
        self.assertNotIn("old", merged)

    def test_a_prose_mention_with_no_real_block_gets_the_block_appended(self):
        # Same prose mention, but no real (start-of-line) block exists yet.
        # This must go down the append path, not be refused and not be
        # matched to the prose mention as if it were the real thing.
        prose = f"We use {agents_md.BEGIN} to mark the managed region.\n"
        block = f"{agents_md.BEGIN}\nx\n{agents_md.END}\n"
        merged = agents_md.merge(prose, block)
        self.assertTrue(merged.startswith(prose))
        self.assertTrue(merged.endswith(block))
        # A second run must find the appended block — not the prose
        # mention — as the sole real marker, and produce no diff.
        self.assertEqual(agents_md.merge(merged, block), merged)

    def test_two_line_start_begin_markers_still_refuse(self):
        # Two BEGIN markers each genuinely at the start of their own line —
        # not a prose mention — is the ambiguity the earlier fix protects
        # against, and that protection must survive: this still refuses.
        existing = f"{agents_md.BEGIN}\nx\n{agents_md.END}\n\n{agents_md.BEGIN}\nrogue\n"
        with self.assertRaises(ValueError):
            agents_md.merge(existing, "BLOCK\n")

    def test_a_marker_present_twice_at_line_start_refuses(self):
        # Two END markers each at the start of a line are still an unusable
        # duplicate — regardless of anything mid-line before them — because
        # only the *first* line-start occurrence used to be consulted,
        # leaving an orphan marker behind and growing the file on every run.
        existing = (f"{agents_md.BEGIN}\ncontent\n{agents_md.END}\n"
                    f"more\n{agents_md.END}\n")
        with self.assertRaises(ValueError):
            agents_md.merge(existing, "BLOCK\n")


class InitTest(unittest.TestCase):
    def test_creates_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            code = agents_md.init(store, project, out=lambda _: None)
            self.assertEqual(code, 0)
            self.assertIn(agents_md.BEGIN,
                          (project / "AGENTS.md").read_text(encoding="utf-8"))

    def test_running_twice_leaves_the_file_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            agents_md.init(store, project, out=lambda _: None)
            first = (project / "AGENTS.md").read_text(encoding="utf-8")
            agents_md.init(store, project, out=lambda _: None)
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), first)

    def test_dry_run_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            agents_md.init(store, project, dry_run=True, out=lambda _: None)
            self.assertFalse((project / "AGENTS.md").exists())

    def test_dry_run_against_an_existing_file_leaves_it_byte_identical(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            agents_md.init(store, project, out=lambda _: None)
            before = (project / "AGENTS.md").read_bytes()
            agents_md.init(store, project, dry_run=True, out=lambda _: None)
            after = (project / "AGENTS.md").read_bytes()
            self.assertEqual(before, after)

    def test_a_crlf_file_is_preserved_byte_for_byte_outside_the_markers(self):
        # Path.read_text/write_text do universal-newline translation, so a
        # user's CRLF AGENTS.md used to come back with every line ending
        # silently turned into LF — a byte-for-byte violation of everything
        # outside the markers, which is this module's one hard rule.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            target = project / "AGENTS.md"
            original = b"# My project\r\n\r\nSome CRLF notes.\r\n"
            target.write_bytes(original)
            agents_md.init(store, project, out=lambda _: None)
            first = target.read_bytes()
            self.assertTrue(first.startswith(original))
            # Every "\n" in the file must be part of a "\r\n" — including in
            # the freshly inserted block — or a lone LF crept in somewhere.
            self.assertEqual(first.count(b"\n"), first.count(b"\r\n"))
            agents_md.init(store, project, out=lambda _: None)
            second = target.read_bytes()
            self.assertEqual(second, first)

    def test_a_failed_write_leaves_the_original_file_byte_identical(self):
        # `open(target, "w")` would empty the file before a single byte of
        # the replacement is written, so a failure mid-write used to leave
        # it truncated. `os.replace` is only called after the full
        # replacement has landed in a temp file, so patching it to raise —
        # after that temp write succeeds — proves the target itself was
        # never touched.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            target = project / "AGENTS.md"
            original = b"# Mine\r\n\r\nNotes.\r\n"
            target.write_bytes(original)
            lines = []
            with mock.patch("os.replace", side_effect=OSError("disk full")):
                code = agents_md.init(store, project, out=lines.append)
            self.assertEqual(code, 2)
            self.assertEqual(target.read_bytes(), original)
            self.assertIn("freya init:", "\n".join(lines))
            # No leftover temp file either.
            leftovers = [p.name for p in project.iterdir() if p.name != "AGENTS.md"]
            self.assertEqual(leftovers, [])

    def test_a_store_side_error_is_not_blamed_on_the_targets_agents_md(self):
        # A failure reading a SKILL.md in the store happens inside
        # `render_block`, which sits between the target read and the target
        # write. It must not be reported as if the project's AGENTS.md were
        # at fault.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            with mock.patch.object(Path, "read_text", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    agents_md.init(store, project, out=lambda _: None)

    def test_a_missing_project_directory_is_reported_not_raised(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "does-not-exist"
            lines = []
            code = agents_md.init(store, project, out=lines.append)
            self.assertEqual(code, 2)
            message = "\n".join(lines)
            self.assertIn("freya init:", message)
            self.assertNotIn("command manifest", message)
            self.assertFalse(project.exists())

    def test_a_malformed_block_refuses_without_touching_the_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            broken = f"keep me\n{agents_md.BEGIN}\nunclosed\n"
            (project / "AGENTS.md").write_text(broken, encoding="utf-8")
            lines = []
            code = agents_md.init(store, project, out=lines.append)
            self.assertEqual(code, 2)
            self.assertEqual((project / "AGENTS.md").read_text(encoding="utf-8"), broken)
            self.assertIn("malformed", "\n".join(lines))
```

Also add, alongside `UpdateDispatchTest` in `bin/test_freya_cli.py` (which already exercises the
same strictness for `freya update`):

```python
class InitDispatchTest(unittest.TestCase):
    """`freya init`'s own argument validation — mirrors UpdateDispatchTest.

    `"--dry-run" in rest` used to also match `--dry-run=1` and any other
    stray argument, so a malformed flag was silently dropped rather than
    rejected, performing a real write when a preview was intended.
    """

    def _run(self, argv):
        out, err = io.StringIO(), io.StringIO()
        with unittest.mock.patch("updater.notify", lambda *a, **k: None):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                code = freya_cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_dry_run_with_a_value_is_rejected_not_silently_run_for_real(self):
        with unittest.mock.patch("agents_md.init") as ran:
            code, _, err = self._run(["init", "--dry-run=1"])
        ran.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("usage: freya init", err)

    def test_an_unknown_flag_is_rejected(self):
        with unittest.mock.patch("agents_md.init") as ran:
            code, _, err = self._run(["init", "--unknown-flag"])
        ran.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("usage: freya init", err)

    def test_two_positionals_are_rejected(self):
        with unittest.mock.patch("agents_md.init") as ran:
            code, _, err = self._run(["init", "a", "b"])
        ran.assert_not_called()
        self.assertEqual(code, 2)
        self.assertIn("usage: freya init", err)

    def test_dispatches_to_agents_md_init(self):
        with unittest.mock.patch("agents_md.init", return_value=0) as ran:
            code, _, _ = self._run(["init", "/tmp/some-project"])
        self.assertEqual(code, 0)
        ran.assert_called_once_with(freya_cli.suite_root(), "/tmp/some-project",
                                     dry_run=False)

    def test_plain_dry_run_still_works(self):
        with unittest.mock.patch("agents_md.init", return_value=0) as ran:
            code, _, _ = self._run(["init", "--dry-run"])
        self.assertEqual(code, 0)
        ran.assert_called_once_with(freya_cli.suite_root(), ".", dry_run=True)

    def test_init_is_listed_in_the_builtins(self):
        # A bare `assertIn("init", ...)` would also pass on the word
        # "install" alone, never actually checking that `init` has its own
        # built-in line.
        self.assertIn(
            "  init      Write a freya-devkit section into a project's AGENTS.md",
            freya_cli.format_help(),
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd bin && python3 -m unittest test_agents_md -v`
Expected: `ModuleNotFoundError: No module named 'agents_md'`.

- [ ] **Step 3: Implement**

Create `bin/agents_md.py`:

```python
#!/usr/bin/env python3
"""Write the freya-devkit section of a project's AGENTS.md.

AGENTS.md is the cross-tool instructions file ~30 agents read. It is a per-repo
file by convention, which is why this is `freya init`, run on request, and not
part of the global install: writing into someone's repository unasked would be
intrusive.

The block is marker-delimited so a re-run replaces it in place and touches
nothing else in the file. Everything outside the markers is the user's file
and must survive byte-for-byte — including its line endings, which is why this
module never goes through `Path.read_text`/`write_text` (universal newlines
would silently turn every CRLF into LF on the way through).
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

import check_skill_conformance as conformance
import installer

BEGIN = "<!-- freya-devkit:begin (managed by `freya init` — edits inside are overwritten) -->"
END = "<!-- freya-devkit:end -->"

#: Tokens after which a period does not end a sentence — `first_sentence`
#: must not stop at "e.g." or a lone initial like "J.".
ABBREVIATIONS = frozenset({"e.g", "i.e", "vs", "etc"})

PREAMBLE = """## freya-devkit

This project uses the freya-devkit skill suite. Its skills are installed for
your agent under their own names, and its tools are reached through one launcher.

- `freya <command>` (a space) is the CLI — for example `freya code-graph --build`.
  Run `freya help` for the full list. Do not call the bundled scripts by path,
  and never with a bare `python`.
- `freya-<skill>` (a hyphen) is a skill name. Skills refer to each other this way.
- Generated artifacts — documentation, specs, security reports — are committed
  separately from the code change that prompted them: the two-commit pattern.
- Where a skill fans work out across several independent tasks, run them in
  parallel if your agent supports subagents, and one at a time if it does not."""


def first_sentence(text):
    """The first sentence of a description, whitespace-collapsed.

    A SKILL.md description is written for skill *selection*: a summary sentence
    followed by usage notes and a pile of TRIGGER keywords. Only the first
    sentence belongs in a table a human reads.

    A period does not end a sentence when the token right before it is a known
    abbreviation ("e.g", "i.e", "vs", "etc") — otherwise "e.g. widgets" or
    "vs. that" would truncate the summary mid-clause.

    A single-letter token before the period ("J.") is only treated as an
    initial — and so skipped — when the word right after it does *not* start
    with a capital letter: an initial is followed by more of a name ("J.
    Smith"), while an actual sentence end is followed by a new capitalized
    sentence. Without that check, a summary like "Reports a | b. And a
    second sentence." never terminates at "b." and runs the second sentence
    on.
    """
    collapsed = " ".join(text.split())
    search_from = 0
    while True:
        idx = collapsed.find(". ", search_from)
        if idx == -1:
            return collapsed
        word_start = idx
        while word_start > 0 and collapsed[word_start - 1] != " ":
            word_start -= 1
        token = collapsed[word_start:idx].strip("([{\"'").lower()
        if token in ABBREVIATIONS:
            search_from = idx + 2
            continue
        if len(token) == 1 and token.isalpha():
            next_start = idx + 2
            next_end = collapsed.find(" ", next_start)
            if next_end == -1:
                next_end = len(collapsed)
            next_word = collapsed[next_start:next_end]
            if not next_word[:1].isupper():
                search_from = idx + 2
                continue
        return collapsed[:idx] + "."


def skill_rows(store):
    """[(skill name, one-line summary)] for every skill in the store."""
    rows = []
    for path in installer.discover_skills(store):
        lines = (path / "SKILL.md").read_text(encoding="utf-8").splitlines()
        description = conformance.frontmatter_value(lines, "description") or ""
        # A pipe inside a description would silently split the table cell.
        summary = first_sentence(description).replace("|", r"\|")
        rows.append((path.name, summary))
    return rows


def render_block(store, newline="\n"):
    """The managed region, markers included, ending in exactly one newline.

    `newline` is whatever line ending the target file predominantly uses, so
    the inserted block matches the rest of a CRLF file instead of mixing
    conventions within one document. Built with "\\n" first and translated
    afterward rather than joined with `newline` directly, because PREAMBLE is
    itself a multi-line string — joining the top-level list would leave its
    *internal* line breaks as bare LF no matter what `newline` was.
    """
    lines = [BEGIN, "", PREAMBLE, "", "| Skill | Use it for |", "|---|---|"]
    lines += [f"| `{name}` | {summary} |" for name, summary in skill_rows(store)]
    lines += ["", END]
    block = "\n".join(lines) + "\n"
    return block if newline == "\n" else block.replace("\n", newline)


def _line_start_positions(text, marker):
    """Indexes where `marker` occurs at the start of a line.

    A mid-line occurrence — someone's prose naming the marker, or a fenced
    example showing it — cannot be the real thing, since the real marker is
    always written at the start of its own line. Only start-of-line
    occurrences are candidates; mid-line ones are ignored entirely rather
    than counted as ambiguity, or a user documenting freya-devkit in their
    own AGENTS.md would lock themselves out of `freya init` forever.
    """
    positions = []
    search_from = 0
    while True:
        pos = text.find(marker, search_from)
        if pos == -1:
            break
        if pos == 0 or text[pos - 1] == "\n":
            positions.append(pos)
        search_from = pos + 1
    return positions


def _locate_marker(text, marker):
    """Index of the sole start-of-line occurrence of `marker`, or None.

    None covers the two cases the caller must treat identically — absent, or
    present at the start of more than one line — because a marker that fails
    either cannot be trusted to bound a replace. Two real markers (say, one
    left over from a previous malformed run and one freshly written) still
    refuse rather than guessing which one is genuine.
    """
    positions = _line_start_positions(text, marker)
    if len(positions) != 1:
        return None
    return positions[0]


def merge(existing, block, newline="\n"):
    """AGENTS.md content with the managed block present exactly once.

    Never rewrites a byte outside the markers — the rest of the file is the
    user's. Raises ValueError if the markers are unusable at the start of a
    line (missing, reversed, or appearing more than once there), because
    guessing where a half-written block ends is how you eat someone's notes.
    A marker mentioned only mid-line — in prose, or a fenced example — is not
    an unusable marker; it is ignored, and the real block (if any) is still
    found and replaced.
    """
    if existing == "":
        return block
    if not _line_start_positions(existing, BEGIN) and not _line_start_positions(existing, END):
        if existing.endswith(newline * 2):
            separator = ""
        elif existing.endswith(newline):
            separator = newline
        else:
            separator = newline * 2
        return existing + separator + block
    start = _locate_marker(existing, BEGIN)
    end = _locate_marker(existing, END)
    if start is None or end is None or end < start:
        raise ValueError(
            "AGENTS.md has a malformed freya-devkit block (an unpaired, reversed, "
            "or duplicated marker) — fix or delete it, then run `freya init` again."
        )
    return existing[:start] + block.rstrip("\r\n") + existing[end + len(END):]


def _detect_newline(existing):
    """The line ending `existing` predominantly uses; "\\n" for a new file.

    Counts CRLF occurrences against LF-only occurrences (a `\\r\\n` also
    contains a `\\n`, so it is subtracted out first) rather than sniffing only
    the first line break, since a file can be inconsistent and the majority
    convention is the one a new block should match.
    """
    crlf = existing.count("\r\n")
    lf_only = existing.count("\n") - crlf
    return "\r\n" if crlf > lf_only else "\n"


def _read_target(target):
    """`target`'s contents with line endings untranslated, or "" if absent."""
    if not target.is_file():
        return ""
    with open(target, "r", encoding="utf-8", newline="") as fh:
        return fh.read()


def _write_target(target, content):
    """Write `content` to `target` atomically, line endings untranslated.

    Writes to a temporary file in the same directory first, then
    `os.replace`s it into place — same-filesystem, and atomic on both POSIX
    and Windows. `open(target, "w")` would truncate the user's file before a
    single byte of the replacement is written, so a failure mid-write (a
    full disk, a permissions change, the process being killed) would leave
    it empty instead of intact. That contradicts this module's one hard
    rule, so the original is never touched until the new content is
    completely and successfully written elsewhere.

    Two more ways an "atomic" write can still damage the original, both
    fixed here. First, `os.replace` does not follow a symlink — replacing
    the raw, unresolved `target` path when it is itself a symlink would
    unlink the symlink and put a plain file in its place, breaking whatever
    it pointed at. Resolving to the real file first makes the swap land on
    the file the symlink points to, leaving the symlink itself intact.
    Second, the temp file is born with the umask's default mode, not the
    original's — `shutil.copystat` carries the original's permissions (and
    mtime) onto the temp file before the swap, or a 0600 AGENTS.md would
    silently come back 0644 after every `freya init`.
    """
    real_target = target.resolve()
    tmp = real_target.with_name(f"{real_target.name}.freya-init-{os.getpid()}.tmp")
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(content)
        if real_target.exists():
            shutil.copystat(real_target, tmp)
        os.replace(tmp, real_target)
    except BaseException:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def init(store, project, *, dry_run=False, out=print):
    """Write or refresh the freya-devkit section of a project's AGENTS.md."""
    target = Path(project) / "AGENTS.md"
    try:
        existing = _read_target(target)
    except OSError as exc:
        out(f"freya init: {target}: {exc.strerror or exc}")
        return 2
    newline = _detect_newline(existing)
    # render_block/merge can fail on the *store* side (a broken or unreadable
    # SKILL.md raises OSError; a malformed block raises ValueError) or with
    # the merged block itself being malformed. Neither is a fault of the
    # project's AGENTS.md, so neither is reported as if it were one — only
    # the read and write of `target`, immediately above and below, are.
    # Catching only ValueError here once let an OSError from the store side
    # escape all the way to freya_cli.main, which reported it as "cannot read
    # the command manifest" — a message about the wrong file entirely.
    try:
        merged = merge(existing, render_block(store, newline=newline), newline=newline)
    except (OSError, ValueError) as exc:
        out(f"freya init: cannot read the skill store ({store}): {exc}")
        return 2
    if merged == existing:
        out(f"freya init: {target} is already up to date")
        return 0
    if dry_run:
        out(f"freya init: would {'update' if existing else 'create'} {target}")
        return 0
    try:
        _write_target(target, merged)
    except OSError as exc:
        out(f"freya init: {target}: {exc.strerror or exc}")
        return 2
    out(f"freya init: {'updated' if existing else 'created'} {target}")
    return 0
```

Then add the `init` dispatch to `bin/freya_cli.py`, next to the `update` branch added in
Task 7. It mirrors that branch's strictness for exactly the same reason: `"--dry-run" in rest`
also matches `--dry-run=1` (and any other stray argument), so a malformed flag used to be
silently dropped instead of rejected — performing a real write when a preview was intended.

```python
        if name == "init":
            # Mirrors the `update` branch below: accept at most one
            # positional path plus an optional exact `--dry-run`. Anything
            # else — a malformed `--dry-run=1`, an unrecognized flag, or two
            # positionals — used to be silently dropped instead of rejected,
            # so `--dry-run=1` performed a real write.
            positionals = [a for a in rest if not a.startswith("-")]
            flags = [a for a in rest if a.startswith("-")]
            if len(positionals) > 1 or flags not in ([], ["--dry-run"]):
                sys.stderr.write("usage: freya init [<project>] [--dry-run]\n")
                return 2
            import agents_md

            project = positionals[0] if positionals else "."
            return agents_md.init(suite_root(), project, dry_run=flags == ["--dry-run"])
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd bin && python3 -m unittest test_agents_md -v`
Expected: PASS, 26 tests.

Then see the real thing, against a scratch directory:

```bash
mkdir -p /tmp/freya-init-check && ./bin/freya init /tmp/freya-init-check && cat /tmp/freya-init-check/AGENTS.md
```
Expected: a table of all ten skills, each with a readable one-line summary — **no empty
cells and no bare `|` values.** Then run it a second time and confirm it reports
"already up to date" and the file is byte-identical.

- [ ] **Step 5: Mutation-check the merge**

1. In `merge`, change `existing[end + len(END):]` to `existing[end:]`.
   Expected: FAIL on `test_a_second_run_produces_no_diff` and
   `test_the_block_is_replaced_in_place_leaving_both_sides_intact` (a duplicated end marker
   grows the file on every run). **Restore.**
2. In `merge`, drop the `end < start` half of the malformed condition.
   Expected: FAIL on `test_reversed_markers_refuse`. **Restore.**
3. In `skill_rows`, delete the `.replace("|", r"\|")`.
   **Corrected expectation:** the original assertion here (`row.count("|") == 4`) does
   **not** fail against this mutation — escaping adds a backslash without deleting the
   pipe it precedes, so the count is 4 either way, and the test was vacuous. The fixed
   assertion (`self.assertIn(r"Reports a \| b.", row)`) does genuinely fail: with the
   `.replace` removed, the row contains the bare `a | b.` instead. Expected: FAIL on
   `test_a_pipe_in_a_description_cannot_break_the_table`. **Restore.**
4. In `first_sentence`, return `collapsed` unconditionally.
   Expected: FAIL on `test_a_row_carries_only_the_first_sentence`. **Restore.**
5. In `_locate_marker`, drop the `len(positions) != 1` check (accept any nonzero count).
   Expected: FAIL on `test_two_line_start_begin_markers_still_refuse` and
   `test_a_marker_present_twice_at_line_start_refuses` — two genuine markers at the start of
   a line are trusted (the first one found) instead of refused. **Restore.**
6. In `merge`, change `if existing == "":` back to `if not existing.strip():`.
   Expected: FAIL on `test_a_whitespace_only_file_is_not_discarded` — a file of pure
   whitespace is discarded instead of kept. **Restore.**
7. In `init`, read and write via `target.read_text(encoding="utf-8")` /
   `target.write_text(merged, encoding="utf-8")` instead of the newline-preserving helpers.
   Expected: FAIL on `test_a_crlf_file_is_preserved_byte_for_byte_outside_the_markers` —
   universal-newline translation turns every `\r\n` into `\n` on the way through. **Restore.**
8. In `init`, drop the `except OSError` clause around the target read/write.
   Expected: FAIL on `test_a_missing_project_directory_is_reported_not_raised` — the
   `FileNotFoundError` from the write propagates uncaught instead of being reported as
   `freya init: <path>: <reason>` and returning 2. **Restore.**
9. In `_line_start_positions`, drop the `pos == 0 or text[pos - 1] == "\n"` guard so every
   occurrence counts, mid-line included.
   Expected: FAIL on `test_a_prose_mention_updates_the_real_block_and_leaves_prose_untouched`
   and `test_a_prose_mention_with_no_real_block_gets_the_block_appended` — a marker mentioned
   in the user's own prose is treated as a duplicate again and refuses, instead of being
   ignored. **Restore.**
10. In `first_sentence`, drop the `next_word[:1].isupper()` check and unconditionally skip a
    single-letter token before a period.
    Expected: FAIL on `test_first_sentence_ends_at_a_single_letter_token_followed_by_a_capital`
    — "Reports a | b." no longer terminates at "b." and the fixture's second sentence runs
    on. **Restore.**
11. In `_write_target`, write directly via `open(target, "w", encoding="utf-8", newline="")`
    instead of the temp-file-and-`os.replace` sequence.
    Expected: FAIL on `test_a_failed_write_leaves_the_original_file_byte_identical` — the
    target is truncated the moment the write starts, so a failure partway through (here,
    patched into `os.replace`, which no longer exists in the write path to fail) leaves it
    empty instead of untouched. **Restore.**
12. In `init`, move `render_block` back inside the same `try/except OSError` that covers the
    target read and write.
    Expected: FAIL on `test_a_store_side_error_is_not_blamed_on_the_targets_agents_md` — a
    store-side `OSError` (a broken `SKILL.md`) is caught and reported as
    `freya init: <project>/AGENTS.md: ...` instead of propagating uncaught. **Restore.**

- [ ] **Step 6: Commit**

```bash
git add bin/agents_md.py bin/test_agents_md.py bin/freya_cli.py
git commit -F - <<'EOF'
feat(init): freya init writes a freya-devkit section into AGENTS.md

Marker-delimited and idempotent: a second run produces no diff, and no byte
outside the markers is ever rewritten, because the rest of that file is the
user's. Unpaired or reversed markers refuse rather than guess where a
half-written block ends.

The skill table is generated from each SKILL.md's description at write time, so
it cannot drift as skills are added or renamed — a static template would have
been a tenth place that list lives. Only the first sentence is used: a
description is written for skill selection and carries usage notes and a pile
of TRIGGER keywords behind it. Pipes are escaped, since one in a description
would silently split a table cell.

It is a command rather than part of the install because AGENTS.md is a per-repo
file by convention; writing into someone's repository unasked would be
intrusive.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

### Task 10: Documentation and closeout

**Files:**
- Modify: `README.md`, `docs/skill-reference.md`, `CONTRIBUTING.md`

**Interfaces:** none — prose only.

- [ ] **Step 1: Confirm where the command surface is documented**

```bash
grep -rn "freya doctor\|freya install" README.md docs/*.md CONTRIBUTING.md
```
Expected: `README.md` §Installation (around line 21) and `docs/skill-reference.md`
§Quick Decision Guide / §File Locations.

- [ ] **Step 2: README — a section after "Skills install as `freya-code-graph`…"**

Insert immediately before `### Claude Code, via the plugin marketplace`:

````markdown
### Keeping it current

```bash
freya update
```

Fast-forwards the checkout and re-links: a skill added upstream gets a link, one
removed loses its stale one, and a `--copy` install is re-copied. It refuses — without
fetching — if the store is not a git checkout, if the branch has no upstream, if you
have uncommitted changes in it, or if it has diverged from its upstream; each says
which. `--dry-run` reports what would happen and writes nothing.

Roughly once a day an ordinary `freya` command may print `an update is available` to
stderr. It is a notice and nothing else — nothing is ever downloaded or applied on its
own. Set `FREYA_NO_UPDATE_CHECK=1` to turn it off.

### Telling a project's agent about the toolkit

```bash
freya init            # or: freya init path/to/project
```

Writes a short freya-devkit section into that project's `AGENTS.md` — the file ~30
agents read — listing the installed skills and the `freya` command surface. The
section is delimited by HTML comment markers: re-running replaces it in place and
leaves every other byte of the file alone, so it is safe on an `AGENTS.md` you already
maintain by hand.
````

- [ ] **Step 3: `docs/skill-reference.md` — extend the Quick Decision Guide**

Add these rows to the table under `## Quick Decision Guide`:

```markdown
| Refresh the toolkit itself | `freya update` |
| Preview an update without applying it | `freya update --dry-run` |
| Introduce the toolkit in a project's AGENTS.md | `freya init` |
| Check the installation is healthy | `freya doctor` |
```

And add to the `## File Locations` table:

```markdown
| Update-check throttle | `~/.freya/update-check.json` |
| Project agent primer | `AGENTS.md` (managed block only) |
```

- [ ] **Step 4: Fix CONTRIBUTING's stale opening**

Its first paragraph still says the deep-audit Workflow lives in `workflows/`, a directory
deleted in `39dfbea`. The spec (§12) parked this as out of scope; it is a one-line factual
error in a file this task already edits, so it is fixed here, and this line records the
deviation deliberately rather than silently.

```bash
grep -n "workflows/" CONTRIBUTING.md
```
Replace the clause so it describes the current tree: skills in `skills/`, the launcher and
installer in `bin/`, design documentation in `docs/`.

- [ ] **Step 5: Verify the whole suite**

```bash
python3 bin/check_skill_conformance.py; echo "exit=$?"
```
Expected: `skill layer is conformant.`, exit 0.

```bash
for t in bin/test_*.py skills/*/scripts/test_*.py; do
  d=$(dirname "$t"); m=$(basename "$t" .py)
  ( cd "$d" && python3 -m unittest "$m" -q ) >/dev/null 2>&1 && echo "ok    $t" || echo "FAIL  $t"
done
```
Expected: `ok` for every suite — the 22 that existed at the end of phase 4b, plus
`test_updater` and `test_agents_md`.

```bash
./bin/freya doctor; echo "exit=$?"
```
Expected: exit 0, with `agents`, `orphaned entries` and `updates` lines all present.

```bash
./bin/freya update --dry-run
```
Expected: a report naming the tracking branch, changing nothing. On this branch, which is
ahead of its upstream and carries local work, expect a refusal — that is correct behaviour,
not a failure.

- [ ] **Step 6: Commit**

```bash
git add README.md docs/skill-reference.md CONTRIBUTING.md
git commit -F - <<'EOF'
docs(portability): document update, init and the notify check

Both new commands beside the existing install/doctor entries, each with its
refusals spelled out, so a user who hits one recognizes it as designed rather
than broken. The notify check is documented with its opt-out, because an
unexplained line about updates appearing during someone else's command is
exactly the kind of thing that gets reported as a bug.

Also corrects CONTRIBUTING's opening, which still described the deep-audit
Workflow as living in workflows/ — a directory deleted in 39dfbea. The spec
parked that fix as out of scope; it is a one-line factual error in a file this
task already edits, so it is corrected here rather than left to be rediscovered.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Definition of done

- `freya update` fast-forwards a clean checkout and re-links; each of the four refusals
  (no git, not a checkout, no upstream, dirty tree) and the diverged case prints its own
  message and exits 2 without fetching or merging.
- An unreachable remote exits 2 with `could not fetch` and leaves `HEAD` where it was — it
  never reports "already up to date" over a stale store.
- A relink that fails partway exits 1, reports which agent, and does not describe itself as
  a manifest problem.
- `freya update --dry-run` writes nothing into the repository — not even a ref.
- A stale store prints at most one notice a day, to stderr, and `FREYA_NO_UPDATE_CHECK=1`
  silences it. No notify path can change a command's exit code.
- `freya init` is idempotent, never rewrites prose outside its markers, and refuses a
  malformed block without touching the file.
- `freya doctor` reports the install mode per agent, names an orphaned entry with the path
  it points at, and reports update status unthrottled.
- A blocked multi-agent install leaves every agent untouched.
- `python3 bin/check_skill_conformance.py` exits 0.
- All 24 test suites pass, and **no test makes a network call**.
- **Nothing pushed.**

## Carried forward to phase 6

- **The hang paths remain untested** — a fetch or an `ls-remote` that stalls until its
  timeout. Injecting a return value cannot reproduce a hang, and a sleeping fixture buys a
  slow suite and no information. Validation should pull the network on a real machine and
  confirm the command stays silent and fast. (An unreachable remote *is* covered — see
  `test_an_unreachable_remote_refuses_without_touching_the_store`.)
- **`install.ps1` and `--copy` on Windows** still have never run. `relink` refreshes copies
  one skill at a time, so an interruption costs one skill rather than the suite, but the
  Windows path as a whole is the least exercised in the project.
- **`uninstall` is absent from `BUILTIN_COMMANDS`** in the conformance checker while `install`
  is present. Harmless today because nothing under `skills/` mentions it; a trap the first
  time something does.
- **Concurrent installs still race** between classify and link, unlocked and non-destructive.
- **`mitigated` remains an unreachable disposition** in the security skill's table.
