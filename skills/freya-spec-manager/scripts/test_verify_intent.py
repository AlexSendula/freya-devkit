#!/usr/bin/env python3
"""Proof suite for verify_intent.py — the G1 declared-intent gate.

Builds throwaway git repos on disk and asserts which behaviors are unauthorized.

Run:  python test_verify_intent.py
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_intent import (verify_intent, advance_marker, advance_if_clear,  # noqa: E402
                           _git_relpath, _changed_status, _blocking)


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(root: Path, *args, check=True):
    r = subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {args} failed: {r.stderr}")
    return r.stdout.strip()


def _init_repo(root: Path):
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "t@t.t")
    _git(root, "config", "user.name", "T")


def _commit_all(root: Path, msg: str) -> str:
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", msg)
    return _git(root, "rev-parse", "HEAD")


def _set_marker(root: Path, commit: str):
    m = root / "knowledge-base/intents/.intent-last-verified"
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(f"# Intent gate last-verified\ncommit: {commit}\n", encoding="utf-8")


def _spec(spec_id, behaviors_block):
    return (
        "---\n"
        f"id: {spec_id}\n"
        f"title: {spec_id} Title\n"
        "category: auth\n"
        "status: implemented\n"
        "certainty: 90\n"
        "created: 2026-07-01\n"
        "updated: 2026-07-01\n"
        "behaviors:\n"
        f"{behaviors_block}"
        "---\n\n"
        f"# {spec_id}\n"
    )


def _beh_block(behavior_id, title, state, locator):
    return (
        f"  - behavior_id: {behavior_id}\n"
        f"    title: {title}\n"
        f"    state: {state}\n"
        f"    adapter: cucumber\n"
        f"    locator: {locator}\n"
    )


FEATURE = (
    "@SPEC-001\nFeature: Login\n\n"
    "  @BEH-001\n  Scenario: Successful login\n"
    "    Given a registered user\n    When they authenticate\n"
    "    Then they are logged in\n"
)


def _intent(intent_id, behaviors):
    beh = "".join(f"  - {b}\n" for b in behaviors)
    return (
        "---\n"
        f"id: {intent_id}\n"
        "behaviors:\n"
        f"{beh}"
        "approver: Alex\n"
        "date: 2026-07-01\n"
        "---\n"
        "## Rationale\nBecause.\n"
    )


class VerifyIntentCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _accepted_project(self, root, state="accepted"):
        """Committed baseline: one accepted BEH-001 linked to a feature file."""
        _init_repo(root)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", state,
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE)
        base = _commit_all(root, "baseline")
        _set_marker(root, base)
        return base

    # --- the core cases ---
    def test_edited_accepted_test_without_record_blocks(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        res = verify_intent(str(root))
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"])

    def test_edited_accepted_test_with_record_passes(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-001"]))
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])
        self.assertIn("BEH-001", res["authorized"])

    def test_added_accepted_test_needs_no_record(self):
        root = self._root()
        base = self._accepted_project(root)
        # A brand-new accepted behavior + committed new test file (status A).
        _write(root / "knowledge-base/specs/auth/SPEC-002-signup.md",
               _spec("SPEC-002",
                     _beh_block("BEH-002", "Signup", "accepted",
                                "features/auth/signup.feature#signup")))
        _write(root / "features/auth/signup.feature",
               "@SPEC-002\nFeature: Signup\n\n  @BEH-002\n  Scenario: Signup\n"
               "    Given a visitor\n    When they sign up\n    Then an account exists\n")
        _commit_all(root, "add signup")
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_deleted_accepted_test_without_record_blocks(self):
        root = self._root()
        self._accepted_project(root)
        (root / "features/auth/login.feature").unlink()
        res = verify_intent(str(root))
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"])

    def test_preexisting_record_does_not_authorize(self):
        root = self._root()
        _init_repo(root)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "accepted",
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE)
        # Record committed as part of the BASELINE => not new in the change-set.
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-001"]))
        base = _commit_all(root, "baseline with record")
        _set_marker(root, base)
        _write(root / "features/auth/login.feature", FEATURE + "    And a later edit\n")
        res = verify_intent(str(root))
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"])

    def test_record_path_reaches_git_slash_separated(self):
        """A record path is addressed to git in git's own spelling, on any host.

        `git cat-file -e <commit>:<path>` matches tree paths verbatim and git
        stores them '/'-separated, so os.sep must never reach it. Trivially true
        on POSIX; on Windows this is the assertion that keeps the gate from
        failing open — a backslash path is reported absent at the baseline, so
        every pre-existing record would look new and authorize the edit
        (first Windows CI run: test_preexisting_record_does_not_authorize).
        """
        root = self._root()
        rel = _git_relpath(root / "knowledge-base" / "intents" / "INTENT-001.md", str(root))
        self.assertEqual(rel, "knowledge-base/intents/INTENT-001.md")

    def test_edited_proposed_test_is_free(self):
        root = self._root()
        self._accepted_project(root, state="proposed")
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_deprecated_in_same_change_is_free(self):
        root = self._root()
        self._accepted_project(root)  # committed as accepted
        # Reclassify to deprecated on disk AND edit its test in the same change.
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "deprecated",
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_pure_rename_needs_no_record(self):
        root = self._root()
        self._accepted_project(root)
        # git mv the test file (staged rename, 100% similarity) and repoint locator.
        _git(root, "mv", "features/auth/login.feature", "features/auth/renamed.feature")
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "accepted",
                                "features/auth/renamed.feature#successful-login")))
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_no_baseline_skips(self):
        root = self._root()
        _init_repo(root)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "accepted",
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE)
        _commit_all(root, "baseline")
        # No marker written.
        res = verify_intent(str(root))
        self.assertTrue(res["skipped"])
        self.assertEqual(res["unauthorized"], [])

    def test_baseline_equals_head_no_false_block(self):
        root = self._root()
        base = self._accepted_project(root)  # marker == HEAD, no working-tree edits
        res = verify_intent(str(root))
        self.assertFalse(res["skipped"])
        self.assertEqual(res["unauthorized"], [])

    def test_untracked_record_counts(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        # Record left untracked (never git-added) — must still authorize.
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-001"]))
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])

    def test_malformed_record_is_error(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        _write(root / "knowledge-base/intents/INTENT-001.md",
               "---\nid: INTENT-001\napprover: Alex\ndate: 2026-07-01\n---\n## Rationale\nx\n")
        res = verify_intent(str(root))
        self.assertTrue(res["errors"], "malformed record must produce an error")

    def test_record_names_unknown_behavior_warns(self):
        root = self._root()
        base = self._accepted_project(root)
        # No edited accepted test; a new record names a non-existent behavior.
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-999"]))
        res = verify_intent(str(root))
        self.assertEqual(res["unauthorized"], [])
        self.assertTrue(any("BEH-999" in w for w in res["warnings"]))

    def test_advance_marker_writes_head(self):
        root = self._root()
        base = self._accepted_project(root)
        (root / "knowledge-base/intents/.intent-last-verified").unlink()
        got = advance_marker(str(root))
        self.assertEqual(got, base)
        self.assertIn(base, (root / "knowledge-base/intents/.intent-last-verified").read_text())

    def test_unparseable_record_is_error_not_traceback(self):
        """A genuinely malformed frontmatter fence must produce an error, not raise."""
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        # Unterminated --- fence: parse_frontmatter raises FrontmatterError on this.
        _write(root / "knowledge-base/intents/INTENT-001.md",
               "---\nid: INTENT-001\nbehaviors:\n  - BEH-001\n# missing closing fence\n")
        res = verify_intent(str(root))  # must not raise
        self.assertTrue(res["errors"], "unparseable INTENT record must produce an error entry")
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"],
                         "unparseable record must not cover any behavior")

    # --- the baseline marker is repo-controlled input (SEC-001) ---
    def test_a_marker_that_is_not_a_commit_hash_never_reaches_git_argv(self):
        """A committed marker is data, and a git revision slot executes data.

        `git diff <rev>` accepts `--output=<file>`: it truncates that file, writes
        the diff into it, and returns rc=0 with nothing on stdout — so the gate
        saw an empty change-set, matched no accepted test, and reported
        `skipped: false` with exit 0 while having read nothing. The marker is not
        git-ignored, so any scanned repository can ship one (SEC-001, reproduced
        end to end 2026-08-23). Both halves are asserted here: the victim file,
        and the answer the gate gives about itself.
        """
        root = self._root()
        self._accepted_project(root)
        victim = self._root() / "victim.txt"      # outside the scanned project
        victim.write_bytes(b"VICTIM DATA THAT MATTERS\n")
        _set_marker(root, f"--output={victim}")
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")

        res = verify_intent(str(root))

        self.assertEqual(victim.read_bytes(), b"VICTIM DATA THAT MATTERS\n",
                         "the marker reached git argv and truncated a file")
        self.assertTrue(res["skipped"], "a marker that is not a hash is not a baseline")
        self.assertTrue(any(".intent-last-verified" in w for w in res["warnings"]),
                        "an ignored marker must be said out loud, not swallowed")
        self.assertEqual(res["unauthorized"], [], "fail-open (ADR-009), not a false block")
        self.assertIn("unusable", res.get("note", ""))
        self.assertNotIn("no baseline marker", res.get("note", ""),
                         "the marker exists and is hostile — do not send the reader "
                         "looking for a file that is sitting right there")

    def test_the_diff_argv_refuses_an_option_in_the_revision_slot(self):
        """`--end-of-options` on its own, with `_read_baseline` out of the way.

        Defence in depth for the hash check above, and the only thing that keeps
        the token alive through a later cleanup. Needs git 2.24+; on older git the
        diff fails, which is the `ok=False` half of the same contract.
        """
        root = self._root()
        _init_repo(root)
        _write(root / "f.txt", "one\n")
        head = _commit_all(root, "one")
        _write(root / "f.txt", "two\n")
        victim = self._root() / "victim.txt"
        victim.write_bytes(b"SENTINEL\n")

        self.assertEqual(_changed_status(str(root), f"--output={victim}"), ({}, False))
        self.assertEqual(victim.read_bytes(), b"SENTINEL\n")
        # Positive control: the separator must not cost the real answer.
        self.assertEqual(_changed_status(str(root), head), ({"f.txt": "M"}, True))

    def test_a_hex_named_file_in_the_repo_is_not_a_baseline(self):
        """The third SEC-001 shape: hash-SHAPED, and git reads it as a PATHSPEC.

        `deadbeef` is eight hex characters, so `_COMMIT_RE` passes it, and it is
        not an option, so `--end-of-options` waves it through. Commit a file by
        that name and `git diff --name-status -M <it>` is a pathspec-filtered diff
        of the working tree: rc=0, no output, no error. Two fixes for SEC-001
        shipped before this one and neither closed it — the gate reported
        `skipped: false` over an edited accepted test it had never read, which is
        the finding's own failure sentence.

        The `--` after the baseline was the fix that closed this, and it is no
        longer the token doing the work: with `^{commit}` in the argv the value is
        `deadbeef^{commit}`, which git refuses with or without the separator, so
        removing `--` leaves this test green. `test_a_crafted_filename_cannot_
        switch_the_gate_off` is what pins the separator now. Dropping `^{commit}`
        does NOT bring this one down either — the `--` still catches this shape —
        which is why the tree tests below exist.
        """
        root = self._root()
        self._accepted_project(root)
        _write(root / "deadbeef", "a pathspec, not a revision\n")
        _commit_all(root, "attacker commits a hex-named file")
        _set_marker(root, "deadbeef")
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")

        self.assertEqual(_changed_status(str(root), "deadbeef"), ({}, False),
                         "a pathspec that resolves is not a baseline that resolved")

        res = verify_intent(str(root))
        self.assertTrue(res["skipped"], "the gate must not claim a run it did not make")
        self.assertIn("git could not diff", res.get("note", ""))
        self.assertEqual(res["unauthorized"], [], "fail-open (ADR-009), not a false block")

    def test_a_hex_named_file_cannot_make_a_past_record_authorize(self):
        """`_record_is_new`'s upstream condition, asserted from outside it.

        An unresolvable baseline makes `cat-file -e <baseline>:<path>` fail for a
        record that has been there all along, and "cannot resolve" lands on "new"
        — the permissive side. Measured on the unfixed code: `_record_is_new` came
        back True for a record committed AT the baseline, so a past record would
        have blessed today's edit. The guard is that `_changed_status` refuses
        first and `verify_intent` returns before any record is loaded.
        """
        root = self._root()
        _init_repo(root)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "accepted",
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE)
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-001"]))
        _write(root / "deadbeef", "a pathspec, not a revision\n")
        _commit_all(root, "baseline with record and a hex-named file")
        _set_marker(root, "deadbeef")
        _write(root / "features/auth/login.feature", FEATURE + "    And a later edit\n")

        res = verify_intent(str(root))

        self.assertTrue(res["skipped"])
        self.assertEqual(res["records_in_change"], [],
                         "no record may be read against a baseline that did not resolve")
        self.assertEqual(res["authorized"], [])

    def test_a_tree_hash_is_not_a_baseline(self):
        """The fourth SEC-001 shape: forty hex characters, and not a commit.

        `git rev-parse HEAD:<dir>` is a tree object id. It passes `_COMMIT_RE`, it
        is not an option, it is not a pathspec — so `--end-of-options` and `--`
        both wave it through, and `git diff --name-status -M <tree> --` diffs that
        tree against the working tree for rc=0. Everything outside the subtree then
        reports as 'A', which `_is_change` calls free, so the edited accepted test
        is waved through and the gate says `skipped: false` over a change-set that
        is an artefact of the wrong baseline. Measured on the three-token version:
        `unauthorized: []`, exit 0. `^{commit}` is what refuses it.
        """
        root = self._root()
        self._accepted_project(root)
        subtree = _git(root, "rev-parse", "HEAD:knowledge-base")
        self.assertEqual(len(subtree), 40)
        _set_marker(root, subtree)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")

        self.assertEqual(_changed_status(str(root), subtree), ({}, False),
                         "a tree that diffs is not a baseline that resolved")

        res = verify_intent(str(root))
        self.assertTrue(res["skipped"], "the gate must not claim a run it did not make")
        self.assertIn("git could not diff", res.get("note", ""))
        self.assertEqual(res["unauthorized"], [], "fail-open (ADR-009), not a false block")

    def test_a_tree_hash_cannot_make_a_past_record_authorize(self):
        """The tree shape's second half, and the reason it outranks a mislabel.

        `cat-file -e <subtree>:knowledge-base/intents/INTENT-001.md` cannot resolve
        — the record is not inside `features/` — so `_record_is_new` calls a record
        committed AT the baseline new, and it authorizes the very edit it predates.
        Measured on the three-token version: `authorized: ['BEH-001']`, exit 0, with
        the record and the edit both already in history.
        """
        root = self._root()
        _init_repo(root)
        _write(root / "knowledge-base/specs/auth/SPEC-001-login.md",
               _spec("SPEC-001",
                     _beh_block("BEH-001", "Successful login", "accepted",
                                "features/auth/login.feature#successful-login")))
        _write(root / "features/auth/login.feature", FEATURE)
        _write(root / "knowledge-base/intents/INTENT-001.md", _intent("INTENT-001", ["BEH-001"]))
        _commit_all(root, "baseline with record")
        subtree = _git(root, "rev-parse", "HEAD:features")
        _set_marker(root, subtree)
        _write(root / "features/auth/login.feature", FEATURE + "    And a later edit\n")

        res = verify_intent(str(root))

        self.assertTrue(res["skipped"])
        self.assertEqual(res["records_in_change"], [],
                         "no record may be read against a baseline that is not a commit")
        self.assertEqual(res["authorized"], [])

    def test_a_real_baseline_survives_every_separator(self):
        """The price of three tokens, pinned: an honest marker still answers.

        Full sha, abbreviated sha and an annotated tag object all resolve to the
        same commit, and all three must produce the real change-set — a peel that
        refused a legitimate baseline would turn the whole gate off and look like
        a security win while doing it.
        """
        root = self._root()
        _init_repo(root)
        _write(root / "f.txt", "one\n")
        head = _commit_all(root, "one")
        _git(root, "tag", "-a", "v1", "-m", "annotated")
        tag_obj = _git(root, "rev-parse", "v1")
        self.assertNotEqual(tag_obj, head, "an annotated tag is its own object")
        _write(root / "f.txt", "two\n")

        for label, value in (("full sha", head), ("abbrev sha", head[:8]),
                             ("annotated tag object", tag_obj)):
            with self.subTest(baseline=label):
                self.assertEqual(_changed_status(str(root), value), ({"f.txt": "M"}, True))

    def test_a_crafted_filename_cannot_switch_the_gate_off(self):
        """What the `--` separator still buys once `^{commit}` is in the argv.

        It is no longer a refusal — `deadbeef^{commit}` does not resolve with or
        without it — so the honest way to keep the token alive is to pin the failure
        it does prevent. The marker is readable by the repository it governs, so a
        repository can commit a file named exactly `<that sha>^{commit}`. Git then
        calls the argument ambiguous, rc=128, and the gate skips on every run and
        exits 0 forever: not a false clean, a gate switched off. Measured without
        the separator: `fatal: ambiguous argument`. With it: the real change-set,
        and the crafted file merely shows up as 'A'.
        """
        root = self._root()
        base = self._accepted_project(root)
        _write(root / f"{base}^{{commit}}", "deny the gate\n")
        _commit_all(root, "a file named after the revision slot")
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")

        status, ok = _changed_status(str(root), base)
        self.assertTrue(ok, "a crafted filename must not be able to stop the diff")
        self.assertEqual(status.get("features/auth/login.feature"), "M")

        res = verify_intent(str(root))
        self.assertFalse(res["skipped"])
        self.assertEqual([u["behavior_id"] for u in res["unauthorized"]], ["BEH-001"])

    def test_a_marker_with_no_usable_commit_value_is_not_a_fresh_repo(self):
        """A marker that exists is never the BEH-090 carve-out, however empty.

        `_read_baseline` used to return a bare None for three of these, which set
        `warnings` empty and `baseline` None — the exact fingerprint
        `_skipped_without_checking` reads as "fresh repository, go ahead". Measured
        on that version, each one made `--advance` exit 0 with an empty stderr, move
        the baseline to HEAD, and erase a committed unauthorized edit from every
        future run. A zero-byte file is the cheapest marker an attacker can author,
        and it was the one that worked best.
        """
        cases = [("empty commit: value", "# Intent gate last-verified\ncommit:\n"),
                 ("no commit: line", "# Intent gate last-verified\nbaseline: x\n"),
                 ("zero-byte file", "")]
        for label, body in cases:
            with self.subTest(marker=label):
                root = self._root()
                self._accepted_project(root)
                marker = root / "knowledge-base/intents/.intent-last-verified"
                marker.write_text(body, encoding="utf-8")
                _write(root / "features/auth/login.feature",
                       FEATURE + "    And an extra step\n")
                _commit_all(root, "unauthorized edit")

                res = verify_intent(str(root))
                self.assertTrue(res["skipped"])
                self.assertTrue(any(".intent-last-verified" in w for w in res["warnings"]),
                                "a marker that exists and is useless must be said out loud")
                self.assertNotIn("no baseline marker", res.get("note", ""))

                commit, refused = advance_if_clear(str(root))
                self.assertIsNone(commit, "a gate that checked nothing may not advance")
                self.assertIsNotNone(refused)
                self.assertEqual(marker.read_text(encoding="utf-8"), body,
                                 "the marker must be left exactly as found")

    def test_a_directory_at_the_marker_path_is_a_labelled_skip_not_a_traceback(self):
        """A scanned repository can put a directory where the marker goes, by
        committing any file underneath it. `read_text` then raised
        IsADirectoryError straight out of the Tier-1 gate.

        It failed closed, so it was never a bypass — but the module's own promise
        is "fail-open on git error, and a fail-open always says so", and a
        traceback is neither. It is the third thing this gate did that its
        docstring said it did not. Being a labelled skip also puts it under the
        `--advance` refusal, which a traceback never was.
        """
        root = self._root()
        self._accepted_project(root)
        marker = root / "knowledge-base/intents/.intent-last-verified"
        marker.unlink()
        marker.mkdir()
        (marker / "committed-underneath").write_text("x", encoding="utf-8")
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        _commit_all(root, "unauthorized edit")

        res = verify_intent(str(root))          # no traceback
        self.assertTrue(res["skipped"])
        self.assertTrue(any(".intent-last-verified" in w for w in res["warnings"]))
        self.assertNotIn("no baseline marker", res.get("note", ""))

        commit, refused = advance_if_clear(str(root))
        self.assertIsNone(commit, "a gate that checked nothing may not advance")
        self.assertIsNotNone(refused)
        self.assertTrue(marker.is_dir(), "the marker must be left exactly as found")

    def test_a_baseline_git_cannot_resolve_reports_itself_skipped(self):
        """Validating the marker does not close the bypass by itself.

        `'0' * 40` is valid hex, so it passes every hash check; `git diff` then
        fails rc=128 and the change-set comes back empty. Before this, that was
        `skipped: false` with exit 0 over an edited accepted test — the gate
        claiming a clean run it never performed.
        """
        root = self._root()
        self._accepted_project(root)
        _set_marker(root, "0" * 40)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")

        res = verify_intent(str(root))

        self.assertTrue(res["skipped"])
        self.assertIn("git could not diff", res.get("note", ""))
        self.assertEqual(res["unauthorized"], [])
        self.assertFalse(_blocking(res), "an infrastructure failure is never a block")

    # --- advancing the baseline is a governance write (SEC-011) ---
    def test_advance_over_a_blocking_gate_refuses_and_leaves_the_marker(self):
        """ADR-008's "advanced only after the gate passes", machine-checked.

        Advancing does not defer an unauthorized edit, it erases it: the gate
        diffs baseline..worktree, so a baseline at HEAD makes the finding
        invisible on every future run. The ordering used to live only in wrap-up's
        prose (SEC-011).
        """
        root = self._root()
        base = self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        _commit_all(root, "unauthorized edit")   # HEAD != base, so advancing would move it

        commit, refused = advance_if_clear(str(root))

        self.assertIsNone(commit)
        self.assertEqual([u["behavior_id"] for u in refused["unauthorized"]], ["BEH-001"])
        self.assertIn(base, (root / "knowledge-base/intents/.intent-last-verified").read_text(),
                      "the marker must still name the pre-advance baseline")

    def test_advance_force_writes_head_over_a_block(self):
        """The override exists, and it is a flag rather than a reordering."""
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        head = _commit_all(root, "unauthorized edit")

        commit, refused = advance_if_clear(str(root), force=True)

        self.assertIsNone(refused)
        self.assertEqual(commit, head)

    def test_advance_cli_exit_code_is_two_over_a_block(self):
        """Exit 2 is the whole point: wrap-up must be able to tell refusal apart
        from the exit 1 the check itself uses, and from the exit 1 of a git error.
        """
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        _commit_all(root, "unauthorized edit")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_intent.py")
        r = subprocess.run([sys.executable, script, "--project", str(root), "--advance"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 2)
        self.assertIn("BEH-001", r.stderr)

    def test_advance_over_a_gate_that_never_ran_refuses(self):
        """SEC-011's refusal has to compose with the SEC-001 attack, or it is theatre.

        A gate that did not run leaves `unauthorized` empty for the same reason a
        clean one does, so `_blocking` alone waves it through. Measured against
        that version: each hostile marker below made `--advance` exit 0, print
        `intent baseline advanced to <sha>` with an EMPTY stderr, and move the
        marker to HEAD — after which the unauthorized edit is behind the baseline
        and gone from every future run. One committed file bought a clean sheet.

        The three markers below are samples, not a census — the version of this
        docstring that called them "the three ways to make the gate skip" was
        already wrong when it shipped, because a marker with no usable `commit:`
        value skips too and advanced right past this refusal
        (`test_a_marker_with_no_usable_commit_value_is_not_a_fresh_repo`). What is
        actually being pinned is the discriminator, not the list: refuse whenever
        the gate reports `skipped` for any reason other than an absent marker.
        """
        victim = self._root() / "victim.txt"
        victim.write_bytes(b"SENTINEL\n")
        cases = [("not a hash", f"--output={victim}", False),
                 ("unresolvable hash", "0" * 40, False),
                 ("hex-named file", "deadbeef", True)]
        for label, marker, plant_file in cases:
            with self.subTest(marker=label):
                root = self._root()
                self._accepted_project(root)
                if plant_file:
                    _write(root / "deadbeef", "a pathspec, not a revision\n")
                    _commit_all(root, "attacker commits a hex-named file")
                _set_marker(root, marker)
                _write(root / "features/auth/login.feature",
                       FEATURE + "    And an extra step\n")
                _commit_all(root, "unauthorized edit")

                commit, refused = advance_if_clear(str(root))

                self.assertIsNone(commit, "a gate that checked nothing may not advance")
                self.assertTrue(refused["skipped"])
                left = root / "knowledge-base/intents/.intent-last-verified"
                self.assertIn(f"commit: {marker}", left.read_text(),
                              "the marker must be left exactly as found")
        self.assertEqual(victim.read_bytes(), b"SENTINEL\n")

    def test_advance_with_no_marker_at_all_still_writes_the_first_one(self):
        """The carve-out, pinned: "no marker" is the designed skip, not a failure.

        BEH-090's fresh repository has nothing to diff against and nothing wrong,
        and `--advance` is how it stops being fresh. Refusing every skip alike
        would make the first marker unwritable and strand wrap-up Phase 5 step 0
        on exit 2 forever.
        """
        root = self._root()
        head = self._accepted_project(root)
        (root / "knowledge-base/intents/.intent-last-verified").unlink()

        commit, refused = advance_if_clear(str(root))

        self.assertIsNone(refused)
        self.assertEqual(commit, head)

    def test_advance_force_writes_head_over_a_skip(self):
        """`--force` is the escape hatch for BOTH refusals, not just the block."""
        root = self._root()
        self._accepted_project(root)
        _set_marker(root, "0" * 40)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        head = _commit_all(root, "unauthorized edit")

        commit, refused = advance_if_clear(str(root), force=True)

        self.assertIsNone(refused)
        self.assertEqual(commit, head)

    def test_advance_cli_over_a_skip_exits_two_and_says_which_refusal(self):
        """The operator must not be sent looking for a finding the gate never made.

        Exit 2 is shared with the blocking refusal — wrap-up only has to tell
        refusal from the check's own exit 1 — so the stderr is what distinguishes
        them. The blocking wording ("declare the intent", "revert the edit") names
        remedies that do not exist here; the marker warning does, and on the
        unfixed code it was printed nowhere at all on this path.
        """
        root = self._root()
        self._accepted_project(root)
        _set_marker(root, "not-a-hash")
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        _commit_all(root, "unauthorized edit")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_intent.py")

        r = subprocess.run([sys.executable, script, "--project", str(root), "--advance"],
                           capture_output=True, text=True)

        self.assertEqual(r.returncode, 2)
        self.assertIn("did not run", r.stderr)
        self.assertIn(".intent-last-verified", r.stderr)
        self.assertNotIn("BEH-NNN", r.stderr,
                         "the blocking remedy is wrong advice for a gate that skipped")
        self.assertIn("commit: not-a-hash",
                      (root / "knowledge-base/intents/.intent-last-verified").read_text())

    def test_cli_exit_code_and_json_contract(self):
        root = self._root()
        self._accepted_project(root)
        _write(root / "features/auth/login.feature", FEATURE + "    And an extra step\n")
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "verify_intent.py")
        r = subprocess.run([sys.executable, script, "--project", str(root), "--format", "json"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 1)  # blocking
        data = json.loads(r.stdout)         # JSON still emitted on non-zero exit
        self.assertEqual([u["behavior_id"] for u in data["unauthorized"]], ["BEH-001"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
