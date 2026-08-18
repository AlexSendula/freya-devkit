#!/usr/bin/env python3
"""Unit tests for the suite installer."""

import contextlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
from pathlib import Path

import installer
import updater


def make_store(tmp, skills=("freya-code-graph", "freya-status")):
    """Materialize a store with the given skill directories."""
    store = Path(tmp) / "store"
    for name in skills:
        d = store / "skills" / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: d\n---\n", encoding="utf-8")
    (store / "bin").mkdir(parents=True, exist_ok=True)
    return store


def run_main(argv):
    """Call installer.main with output captured, so the suite stays quiet."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = installer.main(argv)
    return code, out.getvalue(), err.getvalue()


class PathKeyTest(unittest.TestCase):
    """The single ownership comparison, driven directly.

    Every one of these runs on every platform: `installer.windows()` is the
    one seam the Windows branch reads, so patching it is what lets a Mac or a
    Linux runner prove both halves. What cannot be faked from here is
    `os.path.normcase` — it is bound to the real platform — so the
    case-folding rule is asserted per platform, in its own test.
    """

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    @contextlib.contextmanager
    def as_windows(self):
        with unittest.mock.patch.object(installer, "windows", lambda: True):
            yield

    def test_every_ownership_decision_routes_through_the_helper(self):
        r"""The gap that let cmd_shim_plan ship broken behind a green build.

        The other tests in this class drive `same_path` directly, so they pass
        whether or not a call site uses it. This one drives the call site.
        `cmd_shim_plan` is Windows-EXCLUSIVE — no POSIX run reaches it — so the
        first Windows CI run could not have caught that it was still on
        `owner == str(source)`; only asserting the site itself can.

        The operands must be drive-shaped: `strip_extended_prefix` only strips
        a prefix whose remainder it could also spell normally, so a POSIX temp
        path behind `\\?\` is deliberately left alone. Only the .cmd itself
        needs to be a real file.
        """
        source = Path(r"C:\Users\runneradmin\store\bin\freya")
        target = Path(self.tmp) / "freya"
        cmd = target.with_name(target.name + ".cmd")

        # The tag line a Windows install writes when its store resolved prefixed.
        cmd.write_text("@rem " + installer.SHIM_TAG + r"\\?\C:\Users\runneradmin\store\bin\freya" + "\n",
                       encoding="utf-8")
        with self.as_windows():
            self.assertEqual(installer.cmd_shim_plan(target, source)[1], "ok")

        # A shim naming a genuinely different store is still foreign.
        cmd.write_text("@rem " + installer.SHIM_TAG + r"C:\Users\runneradmin\elsewhere\bin\freya" + "\n",
                       encoding="utf-8")
        with self.as_windows():
            self.assertEqual(installer.cmd_shim_plan(target, source)[1], "foreign")

    def test_is_git_store_compares_paths_not_strings(self):
        """updater.is_git_store is the same family: two `.resolve()`s compared
        with `==` is not path equality on Windows, because realpath preserves a
        prefix its input already carried — so a store reached by an
        extended-length path reports as "not a git work tree"."""
        store = Path(r"C:\Users\runneradmin\store")
        with self.as_windows():
            self.assertTrue(updater.is_git_store(
                store, run=lambda *a, **k: (0, r"\\?\C:\Users\runneradmin\store")))
            self.assertFalse(updater.is_git_store(
                store, run=lambda *a, **k: (0, r"C:\Users\runneradmin\store\nested")))

    def test_an_extended_length_target_is_the_same_path_as_its_plain_form(self):
        """The first Windows CI run's headline failure, in one assertion:
        `os.readlink` returns `\\\\?\\C:\\...` while the source it must be
        compared against is spelled `C:\\...`, so every link the installer had
        just created classified as `foreign`."""
        with self.as_windows():
            self.assertTrue(installer.same_path(
                r"\\?\C:\Users\x\store\skills\freya-status",
                r"C:\Users\x\store\skills\freya-status"))

    def test_an_extended_length_unc_target_is_the_same_path_too(self):
        with self.as_windows():
            self.assertTrue(installer.same_path(
                r"\\?\UNC\server\share\store\skills\freya-status",
                r"\\server\share\store\skills\freya-status"))

    def test_a_volume_guid_path_is_left_alone(self):
        """A `\\\\?\\Volume{...}` path has no unprefixed spelling, so stripping
        the prefix would invent a path that names nothing. Left as it came:
        the entry then reads `foreign`, which is the safe verdict."""
        with self.as_windows():
            guid = r"\\?\Volume{12345678-0000-0000-0000-000000000000}\skills\x"
            self.assertEqual(installer.strip_extended_prefix(guid), guid)

    def test_a_posix_name_that_looks_like_a_prefix_is_never_stripped(self):
        """`\\\\?\\C:\\x` is a legal POSIX filename. Off Windows the prefix
        carries no meaning and stripping it would compare against a file that
        is not the one on disk."""
        with unittest.mock.patch.object(installer, "windows", lambda: False):
            self.assertEqual(installer.strip_extended_prefix(r"\\?\C:\x"), r"\\?\C:\x")

    def test_a_plain_path_is_untouched_on_windows(self):
        with self.as_windows():
            self.assertEqual(installer.strip_extended_prefix(r"C:\a\b"), r"C:\a\b")

    def test_two_spellings_of_one_path_are_one_path(self):
        base = os.path.join(os.sep, "a", "b")
        self.assertTrue(installer.same_path(base, os.path.join(base, "c", "..")))

    def test_case_folds_only_where_the_platform_folds_it(self):
        """normcase is the identity on POSIX and lowercases on Windows, which
        is exactly each platform's truth about its own filesystem: /a/B and
        /a/b are two files on Linux and one on Windows."""
        if installer.windows():
            self.assertTrue(installer.same_path(r"C:\a\B", r"C:\a\b"))
        else:
            self.assertFalse(installer.same_path("/a/B", "/a/b"))


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

    def test_directory_with_matching_marker_is_ok(self):
        """A --copy install proves itself via MARKER, the same way a symlink
        proves itself via readlink."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            target = Path(tmp) / "dst"; target.mkdir()
            (target / installer.MARKER).write_text(str(source), encoding="utf-8")
            self.assertEqual(installer.classify(target, source), "ok")

    def test_directory_whose_marker_names_a_different_store_is_foreign_not_ok(self):
        """The critical safety boundary: a marker is only proof of *this*
        source. A directory that happens to contain a MARKER naming some
        other path must never be treated as ours to silently skip — or,
        worse, replace — without --force."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            target = Path(tmp) / "dst"; target.mkdir()
            other_source = Path(tmp) / "somewhere-else" / "skills" / "freya-code-graph"
            (target / installer.MARKER).write_text(str(other_source), encoding="utf-8")
            self.assertEqual(installer.classify(target, source), "foreign")

    def test_directory_with_undecodable_marker_is_foreign_not_a_crash(self):
        """A marker that can't even be decoded is no more ours than one that
        can't be read — classify must report it, not raise."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            target = Path(tmp) / "dst"; target.mkdir()
            (target / installer.MARKER).write_bytes(b"\xff\xfe not utf-8")
            self.assertEqual(installer.classify(target, source), "foreign")

    def test_directory_without_marker_is_occupied_even_if_named_the_same(self):
        """A plain directory a user created (no marker at all) is never
        anything but occupied — it always blocks, marker or not."""
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "src"; source.mkdir()
            target = Path(tmp) / "dst"; target.mkdir()
            (target / "unrelated.txt").write_text("mine", encoding="utf-8")
            self.assertEqual(installer.classify(target, source), "occupied")


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


    def test_copy_mode_reports_replaced_for_a_foreign_link(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"; target_dir.mkdir()
            elsewhere = Path(tmp) / "elsewhere"; elsewhere.mkdir()
            (target_dir / "freya-code-graph").symlink_to(elsewhere)
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            results = installer.apply_plan(plans, copy=True, force=True)
            self.assertIn("replaced", [a for _, a in results])
            self.assertFalse((target_dir / "freya-code-graph").is_symlink())

    def test_dry_run_previews_a_replacement_accurately(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"; target_dir.mkdir()
            elsewhere = Path(tmp) / "elsewhere"; elsewhere.mkdir()
            (target_dir / "freya-code-graph").symlink_to(elsewhere)
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            results = installer.apply_plan(plans, force=True, dry_run=True)
            self.assertIn("replaced", [a for _, a in results])
            self.assertEqual((target_dir / "freya-code-graph").resolve(), elsewhere.resolve())

    def test_copy_install_is_idempotent(self):
        """The phase's binding constraint: running the installer twice must
        be a no-op the second time. A copied skill is a real directory, so
        without the marker this would classify as `occupied` and block."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            first = installer.apply_plan(installer.plan_agent(store, "claude", target_dir=target_dir),
                                         copy=True)
            self.assertEqual([a for _, a in first], ["copied", "copied"])

            again_plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            self.assertTrue(all(p.status == "ok" for p in again_plans))
            again = installer.apply_plan(again_plans, copy=True)
            self.assertEqual([a for _, a in again], ["skipped", "skipped"])

    def test_copy_install_writes_a_marker_naming_its_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=target_dir), copy=True)
            marker = target_dir / "freya-code-graph" / installer.MARKER
            self.assertTrue(marker.is_file())
            self.assertEqual(marker.read_text(encoding="utf-8"),
                             str(store / "skills" / "freya-code-graph"))

    def test_real_directory_without_marker_still_occupied_even_with_copy_and_force(self):
        """The most important invariant: with or without --force, a real
        directory that does not carry our marker is never removable."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            occupied = target_dir / "freya-code-graph"
            occupied.mkdir(parents=True)
            (occupied / "precious.txt").write_text("do not delete", encoding="utf-8")
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            self.assertEqual(
                [p.status for p in plans if p.target.name == "freya-code-graph"][0],
                "occupied",
            )
            with self.assertRaises(RuntimeError):
                installer.apply_plan(plans, copy=True, force=True)
            self.assertEqual((occupied / "precious.txt").read_text(encoding="utf-8"),
                             "do not delete")

    def test_force_replaces_a_marked_directory_from_a_different_store(self):
        """A --copy install from a *different* freya-devkit checkout is
        `foreign`, not `occupied` — --force may replace it, and only the
        directory carrying our marker shape is ever rmtree'd."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"; target_dir.mkdir()
            stale = target_dir / "freya-code-graph"
            stale.mkdir()
            (stale / "stale.txt").write_text("from another store", encoding="utf-8")
            (stale / installer.MARKER).write_text(
                str(Path(tmp) / "other-store" / "skills" / "freya-code-graph"), encoding="utf-8"
            )
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            results = installer.apply_plan(plans, copy=True, force=True)
            self.assertIn("replaced", [a for _, a in results])
            self.assertTrue((target_dir / "freya-code-graph" / "SKILL.md").is_file())
            self.assertFalse((target_dir / "freya-code-graph" / "stale.txt").exists())
            self.assertEqual(
                (target_dir / "freya-code-graph" / installer.MARKER).read_text(encoding="utf-8"),
                str(store / "skills" / "freya-code-graph"),
            )

    def test_copy_mode_preserves_an_internal_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            skill = store / "skills" / "freya-code-graph"
            (skill / "assets").mkdir()
            (skill / "assets" / "real.txt").write_text("x", encoding="utf-8")
            (skill / "assets" / "link.txt").symlink_to(skill / "assets" / "real.txt")
            target_dir = Path(tmp) / "agentdir"
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            installer.apply_plan(plans, copy=True)
            self.assertTrue((target_dir / "freya-code-graph" / "assets" / "link.txt").is_symlink())


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

    def test_dry_run_leaves_every_link_in_place(self):
        """FIX 1: --dry-run on uninstall must report the plan and remove
        nothing — the README sells it as a safe preview."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=target_dir))

            removed = installer.uninstall_agent(store, "claude", target_dir=target_dir, dry_run=True)

            self.assertEqual(sorted(p.name for p in removed),
                             ["freya-code-graph", "freya-status"])
            self.assertTrue((target_dir / "freya-code-graph").is_symlink())
            self.assertTrue((target_dir / "freya-status").is_symlink())
            self.assertEqual((target_dir / "freya-code-graph").resolve(),
                             (store / "skills" / "freya-code-graph").resolve())

    def test_uninstall_removes_a_copy_install_via_its_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=target_dir), copy=True)

            removed = installer.uninstall_agent(store, "claude", target_dir=target_dir)

            self.assertEqual(sorted(p.name for p in removed),
                             ["freya-code-graph", "freya-status"])
            self.assertFalse((target_dir / "freya-code-graph").exists())
            self.assertFalse((target_dir / "freya-status").exists())

    def test_dry_run_leaves_a_copy_install_in_place(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            installer.apply_plan(installer.plan_agent(store, "claude", target_dir=target_dir), copy=True)

            removed = installer.uninstall_agent(store, "claude", target_dir=target_dir, dry_run=True)

            self.assertEqual(sorted(p.name for p in removed),
                             ["freya-code-graph", "freya-status"])
            self.assertTrue((target_dir / "freya-code-graph" / "SKILL.md").is_file())
            self.assertTrue((target_dir / "freya-code-graph" / installer.MARKER).is_file())

    def test_uninstall_ignores_a_marked_directory_from_a_different_store(self):
        """Mirrors the symlink case (someone-else's link is left alone):
        uninstall must not rmtree a --copy directory whose marker names a
        different store, even though it carries our marker shape."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"; target_dir.mkdir()
            foreign = target_dir / "freya-code-graph"; foreign.mkdir()
            (foreign / installer.MARKER).write_text(
                str(Path(tmp) / "other-store" / "skills" / "freya-code-graph"), encoding="utf-8"
            )

            removed = installer.uninstall_agent(store, "claude", target_dir=target_dir)

            self.assertEqual(removed, [])
            self.assertTrue(foreign.is_dir())
            self.assertTrue((foreign / installer.MARKER).is_file())


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
            bin_dir = Path(tmp) / "localbin"
            common = ["--agent", "claude", "--store", str(store),
                      "--target-dir", str(target_dir), "--bin-dir", str(bin_dir)]
            self.assertEqual(run_main(common)[0], 0)
            self.assertTrue((target_dir / "freya-code-graph").is_symlink())
            self.assertEqual(
                installer.launcher_classify(bin_dir / "freya", store / "bin" / "freya"), "ok")

            self.assertEqual(run_main(common + ["--uninstall"])[0], 0)

            # FIX 2: a full round trip must leave both the agent directory
            # empty AND the launcher removed — a dangling `freya` symlink on
            # PATH after the checkout is deleted is exactly the defect.
            self.assertFalse((target_dir / "freya-code-graph").exists())
            self.assertFalse((target_dir / "freya-status").exists())
            self.assertFalse((bin_dir / "freya").exists())

    def test_uninstall_dry_run_leaves_everything_in_place(self):
        """FIX 1, end to end: `--uninstall --dry-run` must report the plan
        and change nothing — links and launcher both survive."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            bin_dir = Path(tmp) / "localbin"
            common = ["--agent", "claude", "--store", str(store),
                      "--target-dir", str(target_dir), "--bin-dir", str(bin_dir)]
            self.assertEqual(run_main(common)[0], 0)

            code, out, _ = run_main(common + ["--uninstall", "--dry-run"])

            self.assertEqual(code, 0)
            self.assertIn("freya-code-graph", out)
            self.assertTrue((target_dir / "freya-code-graph").is_symlink())
            self.assertTrue((target_dir / "freya-status").is_symlink())
            self.assertEqual(
                installer.launcher_classify(bin_dir / "freya", store / "bin" / "freya"), "ok")
            self.assertEqual((target_dir / "freya-code-graph").resolve(),
                             (store / "skills" / "freya-code-graph").resolve())
            # The launcher line must not claim "removed" during a preview —
            # that word means it actually happened everywhere else it's used.
            self.assertNotRegex(out, r"launcher:\s+removed")
            self.assertIn("would remove", out)

    def test_copy_install_round_trips_through_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            bin_dir = Path(tmp) / "localbin"
            common = ["--agent", "claude", "--store", str(store),
                      "--target-dir", str(target_dir), "--bin-dir", str(bin_dir)]

            self.assertEqual(run_main(common + ["--copy"])[0], 0)
            self.assertFalse((target_dir / "freya-code-graph").is_symlink())
            self.assertTrue((target_dir / "freya-code-graph" / "SKILL.md").is_file())

            # Running it again must be a no-op that exits 0 — the phase's
            # binding constraint, which a copy install broke before FIX 3.
            code, out, _ = run_main(common + ["--copy"])
            self.assertEqual(code, 0)
            self.assertIn("skipped", out)

            self.assertEqual(run_main(common + ["--uninstall"])[0], 0)
            self.assertFalse((target_dir / "freya-code-graph").exists())
            self.assertFalse((bin_dir / "freya").exists())

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


class LauncherTest(unittest.TestCase):
    def test_links_freya_into_the_bin_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            action = installer.link_launcher(store, bin_dir=bindir)
            # Windows gets a written shim rather than a link — see
            # link_launcher — so ownership, not link-ness, is the invariant
            # both modes share.
            self.assertEqual(action, "copied" if installer.windows() else "linked")
            self.assertEqual(
                installer.launcher_classify(bindir / "freya", store / "bin" / "freya"), "ok")
            if not installer.windows():
                self.assertEqual((bindir / "freya").resolve(),
                                 (store / "bin" / "freya").resolve())

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

    def test_dry_run_over_a_foreign_launcher_reports_replaced(self):
        """FIX 7: apply_plan already computes its label before the dry-run
        branch; link_launcher must do the same, or a preview claims `linked`
        for what a real --force run would report as `replaced`."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"; bindir.mkdir()
            elsewhere = Path(tmp) / "elsewhere.sh"; elsewhere.write_text("x")
            (bindir / "freya").symlink_to(elsewhere)

            action = installer.link_launcher(store, bin_dir=bindir, force=True, dry_run=True)

            self.assertEqual(action, "replaced")
            self.assertEqual((bindir / "freya").resolve(), elsewhere.resolve())


class UnlinkLauncherTest(unittest.TestCase):
    def test_removes_our_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            installer.link_launcher(store, bin_dir=bindir)

            result = installer.unlink_launcher(store, bin_dir=bindir)

            self.assertEqual(result, "removed")
            self.assertFalse((bindir / "freya").exists())

    def test_leaves_a_foreign_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"; bindir.mkdir()
            elsewhere = Path(tmp) / "elsewhere.sh"; elsewhere.write_text("x")
            (bindir / "freya").symlink_to(elsewhere)

            result = installer.unlink_launcher(store, bin_dir=bindir)

            self.assertEqual(result, "skipped")
            self.assertTrue((bindir / "freya").is_symlink())
            self.assertEqual((bindir / "freya").resolve(), elsewhere.resolve())

    def test_leaves_a_real_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"; bindir.mkdir()
            (bindir / "freya").write_text("do not delete", encoding="utf-8")

            result = installer.unlink_launcher(store, bin_dir=bindir)

            self.assertEqual(result, "skipped")
            self.assertEqual((bindir / "freya").read_text(encoding="utf-8"), "do not delete")

    def test_honours_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            installer.link_launcher(store, bin_dir=bindir)

            result = installer.unlink_launcher(store, bin_dir=bindir, dry_run=True)

            self.assertEqual(result, "removed")
            self.assertEqual(
                installer.launcher_classify(bindir / "freya", store / "bin" / "freya"), "ok")

    def test_skipped_when_nothing_there(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            self.assertEqual(installer.unlink_launcher(store, bin_dir=bindir), "skipped")


class DefaultAgentsTest(unittest.TestCase):
    def test_detects_claude_via_dot_claude(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            self.assertEqual(installer.default_agents(home=home), ["claude"])

    def test_detects_copilot_via_dot_copilot_without_dot_agents(self):
        """FIX 9: Copilot creates ~/.copilot, not ~/.agents — a Copilot-only
        user must still be detected."""
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".copilot").mkdir()
            self.assertEqual(installer.default_agents(home=home), ["copilot"])

    def test_detects_copilot_via_dot_agents_too(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".agents").mkdir()
            self.assertEqual(installer.default_agents(home=home), ["copilot"])

    def test_detects_both_agents(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            (home / ".claude").mkdir()
            (home / ".copilot").mkdir()
            self.assertEqual(installer.default_agents(home=home), ["claude", "copilot"])

    def test_detects_neither(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(installer.default_agents(home=Path(tmp)), [])


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

    def test_a_marker_that_is_not_valid_utf8_is_foreign_not_a_crash(self):
        """freya doctor must survive a corrupt marker, not blow up on it."""
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            corrupt = agent / "freya-status"
            corrupt.mkdir(parents=True)
            (corrupt / installer.MARKER).write_bytes(b"\xff\xfe not utf-8")
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual([e.status for e in entries], ["foreign"])

    def test_a_link_pointing_somewhere_unrelated_is_foreign(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            agent.mkdir()
            (agent / "freya-status").symlink_to(Path(tmp).resolve() / "random")
            entries = installer.audit_agent(store, "claude", target_dir=agent)
            self.assertEqual([e.status for e in entries], ["foreign"])

    def test_a_link_into_another_store_under_a_different_name_is_foreign(self):
        with tempfile.TemporaryDirectory() as tmp:
            store, agent = self._fixture(tmp)
            agent.mkdir()
            other_store_skill = Path(tmp).resolve() / "elsewhere" / "skills" / "freya-other"
            (agent / "freya-status").symlink_to(other_store_skill)
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

    def test_duplicate_agent_flag_installs_once(self):
        """`--agent claude --agent claude` must behave like a single
        `--agent claude` — not plan the same install twice against one
        pre-mutation snapshot and blow up applying the second copy."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            code, out, err = run_main([
                "--agent", "claude", "--agent", "claude",
                "--store", str(store), "--target-dir", str(target_dir),
                "--bin-dir", str(Path(tmp) / "localbin"),
            ])
            self.assertEqual(code, 0)
            self.assertNotIn("File exists", err)
            self.assertEqual(len(list(target_dir.iterdir())),
                             len(installer.discover_skills(store)))

    def test_a_blocked_launcher_leaves_every_agent_untouched(self):
        """The launcher's own blocker check used to run only inside
        link_launcher, after every agent had already been applied — a real
        file at the launcher target let both agents install in full and only
        then exited 2, mutating exactly what this all-or-nothing barrier
        exists to prevent."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = make_store(root)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            first, second = root / "first", root / "second"
            first.mkdir()
            second.mkdir()
            bin_dir = root / "localbin"
            bin_dir.mkdir()
            # A real file the installer may never remove.
            (bin_dir / "freya").write_text("not ours", encoding="utf-8")
            targets = {"claude": first, "copilot": second}
            with unittest.mock.patch.dict(installer.AGENT_TARGETS, targets, clear=True):
                code, _, err = run_main([
                    "--agent", "claude", "--agent", "copilot",
                    "--store", str(store), "--bin-dir", str(bin_dir),
                ])
            self.assertEqual(code, 2)
            self.assertIn("launcher", err)
            self.assertEqual(sorted(p.name for p in first.iterdir()), [])
            self.assertEqual(sorted(p.name for p in second.iterdir()), [])

    def test_two_agents_sharing_a_target_dir_install_once(self):
        """Two distinct agent names pointed at the same physical directory
        (the hidden --target-dir escape hatch) describe one install, not
        two: both are planned against the same pre-install disk state, so
        both plans say `status="create"` for the same path. The second
        must be skipped, not re-applied against a path the first agent
        already created."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "shared"
            code, out, err = run_main([
                "--agent", "claude", "--agent", "copilot",
                "--store", str(store), "--target-dir", str(target_dir),
                "--bin-dir", str(Path(tmp) / "localbin"),
            ])
            self.assertEqual(code, 0)
            self.assertNotIn("File exists", err)
            self.assertEqual(len(list(target_dir.iterdir())),
                             len(installer.discover_skills(store)))


class CrashSafeCopyTest(unittest.TestCase):
    """A --copy install must never leave its own half-written output behind.

    The marker is written last on purpose, so a partial copy cannot pass for a
    finished one — but that makes the leftover `occupied`, which blocks
    install, blocks --force, is skipped by uninstall and is left alone by
    `freya update`. The installer's own debris wedged every command that could
    have cleared it.
    """

    def _exploding_copytree(self, fail_for):
        real = shutil.copytree

        def copytree(src, dst, *a, **kw):
            if Path(src).name == fail_for:
                # The shape real copytree leaves: the destination exists with
                # part of the tree in it before the failure.
                Path(dst).mkdir(parents=True, exist_ok=True)
                (Path(dst) / "partial.txt").write_text("half", encoding="utf-8")
                raise OSError(28, "No space left on device")
            return real(src, dst, *a, **kw)

        return copytree

    def test_an_interrupted_copy_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            plans = installer.plan_agent(store, "claude", target_dir=target_dir)
            with unittest.mock.patch.object(
                    shutil, "copytree", self._exploding_copytree("freya-status")):
                with self.assertRaises(OSError):
                    installer.apply_plan(plans, copy=True)
            self.assertFalse((target_dir / "freya-status").exists(),
                             "the failed copy left a partial directory behind")

    def test_a_retry_after_an_interrupted_copy_succeeds(self):
        """The whole point: the state left behind must not be one that only a
        manual `rm -rf` can clear."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            with unittest.mock.patch.object(
                    shutil, "copytree", self._exploding_copytree("freya-status")):
                with self.assertRaises(OSError):
                    installer.apply_plan(
                        installer.plan_agent(store, "claude", target_dir=target_dir), copy=True)

            results = installer.apply_plan(
                installer.plan_agent(store, "claude", target_dir=target_dir), copy=True)

            self.assertIn("copied", [a for _, a in results])
            self.assertTrue((target_dir / "freya-status" / "SKILL.md").is_file())
            self.assertTrue((target_dir / "freya-status" / installer.MARKER).is_file())

    def test_a_refresh_that_fails_leaves_the_previous_copy_intact(self):
        """updater._relink_agent re-copies over a live install. Staging is what
        keeps a failure there from destroying a working skill."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            installer.apply_plan(
                installer.plan_agent(store, "claude", target_dir=target_dir), copy=True)
            source = store / "skills" / "freya-status"

            with unittest.mock.patch.object(
                    shutil, "copytree", self._exploding_copytree("freya-status")):
                with self.assertRaises(OSError):
                    installer.copy_into_place(source, target_dir / "freya-status")

            self.assertTrue((target_dir / "freya-status" / "SKILL.md").is_file())
            self.assertEqual(
                installer.classify(target_dir / "freya-status", source), "ok")

    def test_staging_debris_is_invisible_to_discovery_and_audit(self):
        """Even when the cleanup itself cannot run, the leftover must not be a
        `freya-*` name — audit_agent and discover_skills both key on that."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target_dir = Path(tmp) / "agentdir"
            seen = []
            real = shutil.copytree

            def copytree(src, dst, *a, **kw):
                seen.append(Path(dst).name)
                return real(src, dst, *a, **kw)

            with unittest.mock.patch.object(shutil, "copytree", copytree):
                installer.apply_plan(
                    installer.plan_agent(store, "claude", target_dir=target_dir), copy=True)
            self.assertTrue(all(name.startswith(".") for name in seen), seen)

    def test_copy_into_place_refuses_a_target_it_cannot_prove_is_ours(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            target = Path(tmp) / "agentdir" / "freya-status"
            target.mkdir(parents=True)
            (target / "precious.txt").write_text("mine", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                installer.copy_into_place(store / "skills" / "freya-status", target)
            self.assertEqual((target / "precious.txt").read_text(encoding="utf-8"), "mine")


class UninstallRobustnessTest(unittest.TestCase):
    def test_an_undecodable_marker_does_not_abort_the_uninstall(self):
        """classify (:92) and audit_agent (:172) were both widened for a marker
        that is not valid UTF-8; this third reader was missed. Because entries
        are visited in sorted order, the crash removed everything before the
        bad marker, left everything after it, and never reached the launcher."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp, skills=("freya-a", "freya-b", "freya-c"))
            target_dir = Path(tmp) / "agentdir"
            installer.apply_plan(
                installer.plan_agent(store, "claude", target_dir=target_dir), copy=True)
            (target_dir / "freya-b" / installer.MARKER).write_bytes(b"\xff\xfe not utf-8")

            removed = installer.uninstall_agent(store, "claude", target_dir=target_dir)

            self.assertEqual(sorted(p.name for p in removed), ["freya-a", "freya-c"])
            self.assertTrue((target_dir / "freya-b").is_dir())

    def test_uninstall_via_main_survives_a_corrupt_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp, skills=("freya-a", "freya-b"))
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            bin_dir = Path(tmp) / "localbin"
            common = ["--agent", "claude", "--store", str(store),
                      "--target-dir", str(target_dir), "--bin-dir", str(bin_dir)]
            self.assertEqual(run_main(common + ["--copy"])[0], 0)
            (target_dir / "freya-a" / installer.MARKER).write_bytes(b"\xff\xfe")

            code, out, err = run_main(common + ["--uninstall"])

            self.assertEqual(code, 0, err)
            self.assertNotIn("codec", err)
            self.assertFalse((target_dir / "freya-b").exists())
            # The launcher is removed after the loop, so a crash inside it used
            # to leave a `freya` on PATH pointing into a store the user
            # believes they uninstalled.
            self.assertFalse((bin_dir / "freya").exists())

    def test_an_entry_that_cannot_be_removed_is_reported_not_swallowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp, skills=("freya-a", "freya-b"))
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            bin_dir = Path(tmp) / "localbin"
            common = ["--agent", "claude", "--store", str(store),
                      "--target-dir", str(target_dir), "--bin-dir", str(bin_dir)]
            self.assertEqual(run_main(common + ["--copy"])[0], 0)

            real_rmtree = shutil.rmtree

            def rmtree(path, *a, **kw):
                if Path(path).name == "freya-a":
                    raise OSError(13, "Permission denied")
                return real_rmtree(path, *a, **kw)

            with unittest.mock.patch.object(shutil, "rmtree", rmtree):
                code, out, err = run_main(common + ["--uninstall"])

            self.assertEqual(code, 2)
            self.assertIn("could not remove", err)
            # Everything else still went, launcher included — one bad entry
            # must not truncate the uninstall.
            self.assertFalse((target_dir / "freya-b").exists())
            self.assertFalse((bin_dir / "freya").exists())


class RemoveLinkTest(unittest.TestCase):
    def test_a_directory_symlink_is_removed_without_touching_its_target(self):
        """Every skill we install is a directory symlink, and on Windows
        `os.unlink` (DeleteFileW) refuses one — uninstall would fail with
        WinError 5 on precisely the entries it owns. This is the assertion
        `windows-latest` makes for real; on POSIX it is the plain path."""
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "real"
            target.mkdir()
            (target / "keep.txt").write_text("keep", encoding="utf-8")
            link = Path(tmp) / "link"
            link.symlink_to(target, target_is_directory=True)

            installer.remove_link(link)

            self.assertFalse(os.path.lexists(str(link)))
            self.assertTrue((target / "keep.txt").is_file())


class AliasedTargetTest(unittest.TestCase):
    def test_two_agents_whose_target_dirs_are_aliases_install_once(self):
        """`--target-dir` is not the only way two agents land in one directory:
        `~/.claude/skills -> ~/.agents/skills` is a real way to share an
        install, and a literal Path comparison cannot see it — both plans said
        `create`, claude applied, copilot died with EEXIST."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = make_store(root)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            shared = root / "shared_skills"
            shared.mkdir()
            alias = root / "aliasdir"
            alias.symlink_to(shared, target_is_directory=True)
            targets = {"claude": shared, "copilot": alias}
            with unittest.mock.patch.dict(installer.AGENT_TARGETS, targets, clear=True):
                code, out, err = run_main([
                    "--agent", "claude", "--agent", "copilot",
                    "--store", str(store), "--bin-dir", str(root / "localbin"),
                ])
            self.assertEqual(code, 0, err)
            self.assertNotIn("File exists", err)
            self.assertEqual(sorted(p.name for p in shared.iterdir()),
                             ["freya-code-graph", "freya-status"])


class CrossWiredEntryTest(unittest.TestCase):
    def test_a_link_into_this_store_under_another_skills_name_is_foreign(self):
        """audit_agent called this `ok` (ours by location) while classify called
        it `foreign` (wrong target), so doctor reported the agent as correctly
        installed, install refused to touch it without --force, and update
        skipped it silently."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve()
            store = make_store(root)
            agent = root / "agent"
            agent.mkdir()
            (agent / "freya-status").symlink_to(store / "skills" / "freya-code-graph")

            entries = installer.audit_agent(store, "claude", target_dir=agent)

            self.assertEqual([(e.path.name, e.status) for e in entries],
                             [("freya-status", "foreign")])
            plans = installer.plan_agent(store, "claude", target_dir=agent)
            self.assertEqual(
                [p.status for p in plans if p.target.name == "freya-status"], ["foreign"])


class LauncherCopyTest(unittest.TestCase):
    """The launcher used to be symlinked unconditionally — including under
    `--copy`, the documented escape hatch for Windows without Developer Mode,
    and at the very end of the run, after every skill had already been applied.
    """

    def test_copy_writes_a_shim_instead_of_a_symlink(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"

            action = installer.link_launcher(store, bin_dir=bindir, copy=True)

            self.assertEqual(action, "copied")
            self.assertFalse((bindir / "freya").is_symlink())
            self.assertEqual(installer.shim_owner(bindir / "freya"),
                             str(store / "bin" / "freya"))

    def test_a_copied_launcher_actually_runs(self):
        """A verbatim copy of bin/freya would import nothing: it finds
        freya_cli next to its own realpath. Only running it proves the shim is
        a stand-in for the symlink rather than a broken duplicate of it."""
        with tempfile.TemporaryDirectory() as tmp:
            bindir = Path(tmp) / "localbin"
            installer.link_launcher(installer.store_root(), bin_dir=bindir, copy=True)
            proc = subprocess.run([sys.executable, str(bindir / "freya"), "help"],
                                  capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn("Usage: freya", proc.stdout)

    def test_a_copied_launcher_install_is_idempotent(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            installer.link_launcher(store, bin_dir=bindir, copy=True)
            self.assertEqual(installer.link_launcher(store, bin_dir=bindir, copy=True),
                             "skipped")

    def test_uninstall_removes_a_copied_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            installer.link_launcher(store, bin_dir=bindir, copy=True)

            self.assertEqual(installer.unlink_launcher(store, bin_dir=bindir), "removed")
            self.assertFalse((bindir / "freya").exists())

    def test_a_shim_belonging_to_another_checkout_is_foreign_not_ours(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            bindir.mkdir()
            other = Path(tmp) / "other-store" / "bin" / "freya"
            (bindir / "freya").write_text(installer.shim_text(other), encoding="utf-8")

            self.assertEqual(installer.unlink_launcher(store, bin_dir=bindir), "skipped")
            with self.assertRaises(RuntimeError):
                installer.link_launcher(store, bin_dir=bindir, copy=True)
            self.assertEqual(
                installer.link_launcher(store, bin_dir=bindir, copy=True, force=True),
                "replaced")

    def test_a_stranger_at_the_launcher_target_still_blocks(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            bindir.mkdir()
            (bindir / "freya").write_text("not ours", encoding="utf-8")
            with self.assertRaises(RuntimeError):
                installer.link_launcher(store, bin_dir=bindir, copy=True, force=True)
            self.assertEqual((bindir / "freya").read_text(encoding="utf-8"), "not ours")

    def test_a_refused_symlink_falls_back_to_a_shim_instead_of_failing(self):
        """WinError 1314 without Developer Mode, reproduced: the whole install
        used to succeed and then exit 2 on this one file."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            bindir = Path(tmp) / "localbin"

            def refuse(*_a, **_k):
                raise OSError(1314, "A required privilege is not held by the client")

            with unittest.mock.patch.object(Path, "symlink_to", refuse):
                code, out, err = run_main([
                    "--agent", "claude", "--copy", "--store", str(store),
                    "--target-dir", str(target_dir), "--bin-dir", str(bindir),
                ])

            self.assertEqual(code, 0, err)
            self.assertTrue((bindir / "freya").is_file())
            self.assertTrue((target_dir / "freya-code-graph" / "SKILL.md").is_file())


class WindowsLauncherTest(unittest.TestCase):
    """`freya` is extensionless, and neither cmd.exe nor PowerShell will run a
    name that is not in PATHEXT — so on Windows even a perfectly placed
    launcher left every `freya <command>` in every SKILL.md dead. These drive
    the nt branch from any host; `windows-latest` exercises it for real.
    """

    @contextlib.contextmanager
    def _on_windows(self):
        with unittest.mock.patch.object(installer, "windows", lambda: True):
            yield

    def test_a_cmd_shim_is_written_beside_the_launcher(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            with self._on_windows():
                installer.link_launcher(store, bin_dir=bindir)
            shim = (bindir / "freya.cmd").read_text(encoding="utf-8")
            self.assertIn('"%~dp0freya"', shim)
            self.assertIn("%*", shim)
            self.assertIn(sys.executable, shim)
            self.assertEqual(installer.shim_owner(bindir / "freya.cmd"),
                             str(store / "bin" / "freya"))

    def test_the_launcher_is_written_not_symlinked_even_without_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            with self._on_windows():
                self.assertEqual(installer.link_launcher(store, bin_dir=bindir), "copied")
            self.assertFalse((bindir / "freya").is_symlink())

    def test_the_cmd_shim_is_removed_by_uninstall(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            with self._on_windows():
                installer.link_launcher(store, bin_dir=bindir)
                self.assertEqual(installer.unlink_launcher(store, bin_dir=bindir), "removed")
            self.assertFalse((bindir / "freya.cmd").exists())
            self.assertFalse((bindir / "freya").exists())

    def test_a_missing_cmd_shim_is_written_on_a_second_run(self):
        """The launcher alone is `ok`, but on Windows an install without the
        .cmd is an install that cannot be invoked."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            bindir = Path(tmp) / "localbin"
            with self._on_windows():
                installer.link_launcher(store, bin_dir=bindir)
                (bindir / "freya.cmd").unlink()
                installer.link_launcher(store, bin_dir=bindir)
            self.assertTrue((bindir / "freya.cmd").is_file())

    def test_a_foreign_cmd_shim_blocks_before_any_skill_is_installed(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            bindir = Path(tmp) / "localbin"
            bindir.mkdir()
            (bindir / "freya.cmd").write_text("@echo somebody else\n", encoding="utf-8")
            with self._on_windows():
                code, out, err = run_main([
                    "--agent", "claude", "--store", str(store),
                    "--target-dir", str(target_dir), "--bin-dir", str(bindir),
                ])
            self.assertEqual(code, 2)
            self.assertIn("freya.cmd", err)
            self.assertFalse(target_dir.exists())
            self.assertEqual((bindir / "freya.cmd").read_text(encoding="utf-8"),
                             "@echo somebody else\n")

    def test_the_path_note_is_not_posix_shell_syntax(self):
        with self._on_windows():
            hint = installer.path_hint(Path("C:/Users/x/.local/bin"))
        self.assertNotIn("export PATH", hint)
        self.assertIn("$env:PATH", hint)

    def test_the_path_note_is_posix_shell_syntax_elsewhere(self):
        with unittest.mock.patch.object(installer, "windows", lambda: False):
            self.assertIn("export PATH", installer.path_hint(Path("/home/x/.local/bin")))

    def test_a_refused_symlink_probe_selects_copy_for_the_user(self):
        """01-design.md:85 promised "copy fallback, auto on Windows without
        symlink privilege". Without the probe the refusal only shows up
        mid-apply, which no pre-flight can catch."""
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            (store / "bin" / "freya").write_text("#!/usr/bin/env python3\n", encoding="utf-8")
            target_dir = Path(tmp) / "agentdir"
            bindir = Path(tmp) / "localbin"

            def refuse(*_a, **_k):
                raise OSError(1314, "A required privilege is not held by the client")

            with self._on_windows():
                with unittest.mock.patch.object(Path, "symlink_to", refuse):
                    code, out, err = run_main([
                        "--agent", "claude", "--store", str(store),
                        "--target-dir", str(target_dir), "--bin-dir", str(bindir),
                    ])
            self.assertEqual(code, 0, err)
            self.assertIn("installing with --copy", out)
            self.assertTrue((target_dir / "freya-code-graph" / installer.MARKER).is_file())
            self.assertTrue((bindir / "freya.cmd").is_file())

    def test_symlinks_available_says_yes_when_they_work(self):
        with tempfile.TemporaryDirectory() as tmp:
            probe_dir = Path(tmp) / "somewhere"
            self.assertTrue(installer.symlinks_available(probe_dir))
            self.assertEqual(list(probe_dir.iterdir()), [], "the probe left debris")


if __name__ == "__main__":
    unittest.main()
