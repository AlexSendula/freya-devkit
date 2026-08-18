#!/usr/bin/env python3
"""Unit tests for the store updater and the notify check."""

import contextlib
import io
import os
import shutil
import subprocess
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import installer
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


@unittest.skipUnless(HAS_GIT, "git is not installed")
class UpdateTest(unittest.TestCase):
    def _run(self, store, **kw):
        lines = []
        # update() now calls relink(), which iterates installer.AGENT_TARGETS
        # — the real ~/.claude/skills and ~/.agents/skills — unless patched
        # away. Every fixture in this class uses a throwaway store, but
        # without this the fast-forward tests would audit the developer's
        # actual home directory on every run.
        #
        # A successful (non-dry-run) update also stamps the throttle cache;
        # left at its default, that write lands on the real
        # ~/.freya/update-check.json. state= keeps it inside this fixture's
        # own temp directory instead, unless the caller already supplied one.
        kw.setdefault("state", Path(store).parent / "throttle-state.json")
        with unittest.mock.patch.dict(installer.AGENT_TARGETS, {}, clear=True):
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

    def test_a_relink_failure_fails_an_otherwise_successful_update(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            advance(work)
            with unittest.mock.patch.object(updater, "relink",
                                            return_value=updater.RelinkResult(1, 1)):
                code, _ = self._run(store)
            self.assertEqual(code, 1)

    def test_a_clean_relink_leaves_the_fast_forward_successful(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            advance(work)
            with unittest.mock.patch.object(updater, "relink",
                                            return_value=updater.RelinkResult(1, 0)):
                code, _ = self._run(store)
            self.assertEqual(code, 0)

    def test_a_dry_run_relink_failure_fails_the_preview_too(self):
        # update()'s dry-run branch used to call relink(dry_run=True) and
        # discard the RelinkResult, so an agent that could not be audited
        # during a preview still yielded exit 0 — while the identical
        # condition on the real path (the test above's sibling) yields 1.
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            advance(work)
            with unittest.mock.patch.object(updater, "relink",
                                            return_value=updater.RelinkResult(1, 1)):
                code, _ = self._run(store, dry_run=True)
            self.assertEqual(code, 1)

    def test_a_clean_dry_run_relink_exits_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            advance(work)
            with unittest.mock.patch.object(updater, "relink",
                                            return_value=updater.RelinkResult(1, 0)):
                code, _ = self._run(store, dry_run=True)
            self.assertEqual(code, 0)

    def test_an_unchanged_remote_is_already_up_to_date(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            code, output = self._run(store)
            self.assertEqual(code, 0)
            self.assertIn("already up to date", output)

    def test_a_real_update_says_how_to_pick_it_up(self):
        """Agents cache their skill list per session, so a mid-task update is
        invisible until the session reloads. Observed live in phase 7: with a
        skill's file removed, Copilot still offered the name from its start-up
        snapshot and then failed on it with a raw ENOENT. An update that says
        only `updated abc -> def` is how a working update looks broken."""
        with tempfile.TemporaryDirectory() as tmp:
            _, work, store = make_origin(Path(tmp).resolve())
            advance(work)
            code, output = self._run(store)
            self.assertEqual(code, 0)
            self.assertIn("reload", output.lower())
            self.assertIn("/reload-skills", output)   # Claude Code
            self.assertIn("/skills", output)          # Copilot

    def test_an_unchanged_store_does_not_nag_about_reloading(self):
        """Nothing moved, so there is nothing to reload. The hint has to be
        rare enough to be read when it does appear."""
        with tempfile.TemporaryDirectory() as tmp:
            _, _, store = make_origin(Path(tmp).resolve())
            _, output = self._run(store)
            self.assertNotIn("reload", output.lower())

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

    def test_dry_run_previews_the_relink_without_writing_anything(self):
        # update(dry_run=True) used to return before ever calling relink, so
        # the "would fast-forward and re-link" message was a preview of
        # something never actually previewed. This proves relink now runs
        # under dry_run and that its dry-run guarantee (writes nothing) holds
        # through update()'s own dry-run path, not just relink() called
        # directly.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, _, store = make_origin(root)
            (store / "skills" / "freya-status").mkdir(parents=True)
            (store / "skills" / "freya-status" / "SKILL.md").write_text(
                "---\nname: freya-status\ndescription: d\n---\n", encoding="utf-8")
            git(["add", "-A"], store)
            git(["commit", "-m", "add a skill"], store)

            agent = root / "agent"
            agent.mkdir()
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent),
                                     copy=True)
            before = (agent / "freya-status" / "SKILL.md").read_bytes()

            (store / "skills" / "freya-status" / "SKILL.md").write_text(
                "---\nname: freya-status\ndescription: changed\n---\n", encoding="utf-8")
            git(["commit", "-am", "change description"], store)

            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                code = updater.update(store, out=lines.append, dry_run=True)
            self.assertEqual(code, 0)
            self.assertIn("would re-copy", "\n".join(lines))
            self.assertEqual((agent / "freya-status" / "SKILL.md").read_bytes(), before)

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


class RelinkTest(unittest.TestCase):
    """Deliberately unguarded by any "can this machine make a symlink?" skip.

    Eight of these failed on the first Windows CI run and it looked like the
    symlink fixtures were silently not being created. They were: in
    test_a_foreign_entry_is_reported_and_untouched the `assertTrue(...
    is_symlink())` immediately before the failing line passed, so the runner
    does hold the privilege. The real cause was `os.readlink` returning the
    `\\\\?\\` extended-length form, which made `installer.audit_agent` report
    every link as `stale-store`; relink skips an agent with zero `ok` entries,
    so all eight assertions saw empty output. Fixed in installer.path_key.

    A skip here would therefore hide the very cluster that caught it. If a
    guard is ever genuinely needed — an unelevated Windows dev box without
    Developer Mode — `installer.symlinks_available(dir)` already exists and is
    what the installer itself probes with; use that rather than a new helper.
    """

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
            # os.path.lexists, not Path.exists(follow_symlinks=False): that
            # keyword is 3.12+, and CI runs this suite on the 3.9 floor.
            self.assertFalse(os.path.lexists(str(agent / "freya-status")))
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
                # `dst` is the hidden staging directory the copy is written to
                # before being renamed into place, so the skill this call is
                # for is the *source*'s name.
                calls.append(Path(src).name)
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

    def test_an_occupied_target_does_not_crash_relink(self):
        # The CRITICAL reproduction: freya-code-graph correctly linked, plus a
        # real directory occupying freya-status's target name (a name that
        # exists in the store). apply_plan raises RuntimeError for an
        # "occupied" plan; relink must report and count that, never let it
        # escape as an uncaught traceback after orphan removals already ran.
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

    def test_an_occupied_entry_shadowing_a_current_skill_says_so(self):
        # freya-status still exists in the store, but its target name is
        # occupied by a real directory that is not ours. Leaving it alone is
        # correct — we never remove something we did not create — but the
        # user gets no signal that freya-status is therefore simply not
        # installed for this agent unless the line says so explicitly.
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
                updater.relink(store, out=lines.append)
            joined = "\n".join(lines)
            self.assertIn("freya-status", joined)
            self.assertIn("not installed", joined)

    def test_a_foreign_entry_naming_no_current_skill_gets_the_plain_line(self):
        # freya-other names nothing in the store at all, so it cannot be
        # "shadowing" a skill — it must not get the "therefore not
        # installed" wording, which would misleadingly imply a skill named
        # freya-other exists and is being blocked.
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
            joined = "\n".join(lines)
            self.assertIn("freya-other", joined)
            self.assertNotIn("not installed", joined)

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

            def exploding_removal(*_a, **_k):
                raise OSError("disk went away")

            lines = []
            # Patch `remove_link`, not `Path.unlink`: unlink is merely how
            # removal is spelled today, and on Windows remove_link's rmdir
            # fallback then SUCCEEDS, so the injected failure never reaches
            # the code under test and a failed removal counts as a good one.
            # The seam this test is about is "removal raised", whatever the call.
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                with unittest.mock.patch.object(installer, "remove_link",
                                                exploding_removal):
                    result = updater.relink(store, out=lines.append)
            self.assertEqual(result.failed, 1)
            # "removed" is printed only after the removal succeeds; a failed
            # one must never be reported as done.
            self.assertNotIn("removed freya-status", "\n".join(lines))

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

    def test_dry_run_reports_a_new_link_in_the_conditional_not_the_past_tense(self):
        # _relink_agent's final apply_plan loop printed the bare verb
        # ("claude: linked freya-new") even under dry_run, while the
        # sibling branches in the same function correctly said "would
        # remove" / "would re-copy". A preview must speak in one voice, and
        # it must write nothing regardless of what it says.
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
            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                updater.relink(store, dry_run=True, out=lines.append)
            joined = "\n".join(lines)
            self.assertIn("would", joined)
            self.assertNotIn("claude: linked freya-new", joined)
            self.assertFalse((agent / "freya-new").exists())

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

    def test_an_all_orphan_skill_agent_has_nothing_removed(self):
        # The guard this proves: `if not any(e.status == "ok" for e in
        # entries): continue`. If the store's skills/ directory itself goes
        # missing or unreadable, every entry in an agent audits as
        # orphan-skill (each symlink's target no longer exists) — without
        # the guard, the removal branch below would prune every single one
        # of them, a catastrophic response to a broken store rather than a
        # deliberate uninstall.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = self._store(root)  # freya-code-graph, freya-status
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent))
            shutil.rmtree(store / "skills")  # every entry now audits orphan-skill
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                result = updater.relink(store, out=lambda _: None)
            self.assertEqual(result, (0, 0))
            self.assertTrue((agent / "freya-code-graph").is_symlink())
            self.assertTrue((agent / "freya-status").is_symlink())

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


@unittest.skipUnless(HAS_GIT, "git is not installed")
class RemoteHeadTest(unittest.TestCase):
    """`ls-remote <remote> <branch>` is a *pattern*: git matches it against the
    tail of every advertised ref on a path-component boundary and sorts the
    output by ref name. A sibling ref ending in the same component therefore
    answered first, and the answer was the wrong SHA."""

    def test_a_sibling_ref_ending_in_the_same_component_is_not_mistaken_for_the_branch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            origin, work, store = make_origin(root)
            # refs/heads/dev/main sorts before refs/heads/main, so an
            # unqualified query returns it first.
            git(["branch", "dev/main"], work)
            (work / "README.md").write_text("decoy\n", encoding="utf-8")
            git(["commit", "-am", "decoy"], work)
            git(["push", "origin", "HEAD:refs/heads/dev/main"], work)

            self.assertEqual(updater.remote_head(store, "origin/main"), updater.head(store))

    def test_a_branch_that_exists_only_as_a_nested_sibling_reports_none(self):
        """`refs/heads/dev/topic` is not `refs/heads/topic`. Answering with the
        sibling's SHA is how a branch that was never pushed reported itself as
        permanently out of date."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, work, store = make_origin(root)
            git(["push", "origin", "HEAD:refs/heads/dev/topic"], work)

            self.assertIsNone(updater.remote_head(store, "origin/topic"))


@unittest.skipUnless(HAS_GIT, "git is not installed")
class BehindTest(unittest.TestCase):
    """A store that is *ahead* is not a store that needs updating."""

    def test_a_store_with_a_local_commit_is_not_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, _, store = make_origin(root)
            remote = updater.head(store)
            (store / "local.txt").write_text("local\n", encoding="utf-8")
            git(["add", "-A"], store)
            git(["commit", "-m", "local"], store)

            self.assertFalse(updater.is_behind(store, remote, updater.head(store)))

    def test_a_store_with_a_local_commit_gets_no_update_notice(self):
        # The notice fired on any SHA inequality, so every contributor was
        # told daily to run an update that then exits 2 with "your store has
        # diverged" — and the notice could never clear.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, _, store = make_origin(root)
            (store / "local.txt").write_text("local\n", encoding="utf-8")
            git(["add", "-A"], store)
            git(["commit", "-m", "local"], store)

            message = updater.update_message(store, now=1000.0, path=root / "state.json",
                                             env={})

            self.assertIsNone(message)

    def test_an_advanced_upstream_is_still_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, work, store = make_origin(root)
            advance(work)

            message = updater.update_message(store, now=1000.0, path=root / "state.json",
                                             env={})

            self.assertEqual(message, updater.MESSAGE)

    def test_an_unfetched_remote_sha_counts_as_behind(self):
        """The remote object is not in this repository at all — `--is-ancestor`
        fails, and the honest reading of that is "the remote has moved"."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, _, store = make_origin(root)
            self.assertTrue(updater.is_behind(store, "0" * 40, updater.head(store)))


class NotifyStateTest(unittest.TestCase):
    def test_an_unwritable_state_path_still_returns_the_notice(self):
        """update() guards its throttle write with a comment about "an
        unwritable $HOME"; update_message did not, so the answer it had
        already paid a network call for was thrown away — permanently, since
        nothing is ever persisted and every command then re-checks."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            blocked = root / "state-dir"
            blocked.write_text("this is a file, not a directory", encoding="utf-8")

            def runner(args, cwd, timeout=None):
                if args[0] == "rev-parse" and args[1] == "--show-toplevel":
                    return 0, str(cwd)
                if args[0] == "rev-parse" and "@{u}" in args:
                    return 0, "origin/main"
                if args[0] == "rev-parse":
                    return 0, "aaaa"
                if args[0] == "ls-remote":
                    return 0, "bbbb\trefs/heads/main"
                if args[0] == "merge-base":
                    return 1, ""     # bbbb is not an ancestor of aaaa
                return 1, ""

            message = updater.update_message(root, now=1000.0,
                                             path=blocked / "update-check.json",
                                             run=runner, env={})

            self.assertEqual(message, updater.MESSAGE)


class RelinkCrashSafetyTest(unittest.TestCase):
    def test_a_failed_copy_refresh_leaves_the_installed_skill_intact(self):
        """The refresh used to rmtree the live copy and only then re-copy, so a
        failure in between deleted a working skill and left an unmarked
        directory — `occupied`, which relink leaves alone while reporting
        failed=0, install refuses to replace even with --force, and uninstall
        skips. Only a manual rm -rf recovered."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = RelinkTest()._store(root, skills=("freya-status",))
            agent = root / "agent"
            agent.mkdir()
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=agent),
                                 copy=True)
            (store / "skills" / "freya-status" / "SKILL.md").write_text(
                "---\nname: freya-status\ndescription: updated\n---\n", encoding="utf-8")

            real_copytree = shutil.copytree

            def exploding(src, dst, *a, **kw):
                Path(dst).mkdir(parents=True, exist_ok=True)
                raise OSError(28, "No space left on device")

            lines = []
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                with unittest.mock.patch.object(shutil, "copytree", exploding):
                    result = updater.relink(store, out=lines.append)

            self.assertEqual(result.failed, 1)
            self.assertTrue((agent / "freya-status" / "SKILL.md").is_file(),
                            "the failed refresh destroyed the installed skill")
            self.assertTrue((agent / "freya-status" / installer.MARKER).is_file())

            # And the remedy the failure message prints must actually work.
            with unittest.mock.patch.dict(installer.AGENT_TARGETS,
                                          {"claude": agent}, clear=True):
                with unittest.mock.patch.object(shutil, "copytree", real_copytree):
                    again = updater.relink(store, out=lines.append)
            self.assertEqual(again.failed, 0)
            self.assertIn("updated",
                          (agent / "freya-status" / "SKILL.md").read_text(encoding="utf-8"))


class PreconditionMessageTest(unittest.TestCase):
    def test_a_detached_head_is_named_rather_than_given_a_remedy_that_fails(self):
        # `--abbrev-ref HEAD` is the literal "HEAD" when detached, so the
        # generic message read "git branch --set-upstream-to origin/HEAD",
        # which always fails with "does not point to any branch".
        def runner(args, cwd, timeout=None):
            if args[0] == "rev-parse" and args[1] == "--show-toplevel":
                return 0, str(cwd)
            if args[0] == "rev-parse" and "@{u}" in args:
                return 1, ""
            if args[0] == "rev-parse":
                return 0, "HEAD"
            return 1, ""

        with tempfile.TemporaryDirectory() as tmp:
            reason = updater.preconditions(Path(tmp).resolve(), run=runner)[0]
        self.assertIn("detached HEAD", reason)
        self.assertNotIn("origin/HEAD", reason)

    def test_a_local_branch_upstream_is_refused_before_the_fetch(self):
        # `git branch --set-upstream-to main` makes @{u} a bare branch name.
        # Every precondition passed, then `git fetch main` failed and the user
        # was told to check their network.
        def runner(args, cwd, timeout=None):
            if args[0] == "rev-parse" and args[1] == "--show-toplevel":
                return 0, str(cwd)
            if args[0] == "rev-parse" and "@{u}" in args:
                return 0, "main"
            if args[0] == "status":
                return 0, ""
            return 1, ""

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            reason = updater.preconditions(root, run=runner)[0]
            lines = []
            code = updater.update(root, out=lines.append, run=runner)
        self.assertIn("local branch", reason)
        self.assertEqual(code, 2)
        self.assertNotIn("network", "\n".join(lines))


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

    def test_a_future_checked_at_checks_again_instead_of_going_silent_forever(self):
        # now - checked_at negative (clock skew, or a hand-edited file) is
        # always < CHECK_INTERVAL, so an unguarded comparison would read a
        # future timestamp as "just checked" and suppress the check forever.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "state.json"
            updater.write_state(state, {"checked_at": 1_000_000.0, "behind": False})
            calls = []
            updater.update_message(root, now=1000.0, path=state,
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

    def test_the_default_stream_is_resolved_at_call_time_not_import_time(self):
        # stream used to default to sys.stderr in the signature, bound once
        # at import time — contextlib.redirect_stderr around a later call
        # could never capture the notice because notify() was still writing
        # to the original stderr object.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            state = root / "state.json"
            captured = io.StringIO()
            with contextlib.redirect_stderr(captured):
                updater.notify(root, now=1000.0, path=state, run=self._runner([]), env={})
        self.assertEqual(captured.getvalue(), updater.MESSAGE + "\n")


@unittest.skipUnless(HAS_GIT, "git is not installed")
class UpdateStampsTheCheckTest(unittest.TestCase):
    def test_a_successful_update_clears_a_stale_behind_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, work, store = make_origin(root)
            state = root / "state.json"
            updater.write_state(state, {"checked_at": 1000.0, "behind": True})
            advance(work)
            with unittest.mock.patch.dict(installer.AGENT_TARGETS, {}, clear=True):
                updater.update(store, out=lambda _: None, state=state)
            self.assertFalse(updater.read_state(state)["behind"])

    def test_a_failing_write_state_does_not_change_updates_return_code(self):
        # The fast-forward and re-link have already succeeded by the time
        # write_state runs; an unwritable $HOME must not turn that success
        # into a reported failure.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            _, work, store = make_origin(root)
            advance(work)

            def exploding_write_state(*_a, **_k):
                raise OSError("read-only file system")

            with unittest.mock.patch.dict(installer.AGENT_TARGETS, {}, clear=True):
                with unittest.mock.patch.object(updater, "write_state", exploding_write_state):
                    code = updater.update(store, out=lambda _: None)
            self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
