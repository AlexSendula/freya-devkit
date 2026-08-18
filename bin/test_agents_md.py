#!/usr/bin/env python3
"""Unit tests for the AGENTS.md writer."""

import os
import shutil
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import agents_md

#: Windows has no POSIX permission bits. `os.chmod` there can toggle exactly
#: one thing — the read-only attribute — so `os.chmod(f, 0o600)` leaves
#: st_mode reading 0o666, and a test that asserts a 0600 file comes back 0600
#: is asserting something the platform cannot do. (First Windows CI run
#: reported `438 != 384`, i.e. 0o666 against the 0o600 it asked for.) The
#: assertion itself is not weakened: it guards a real defect — `os.replace`
#: swaps in a temp file born with the umask's mode — everywhere the bits exist.
HAS_POSIX_MODES = os.name != "nt"

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

    def test_first_sentence_ends_at_a_question_or_exclamation_mark(self):
        # Only ". " used to count as a sentence end, so a summary ending in
        # "!" or "?" fell through to "return collapsed" and put the whole
        # description — TRIGGER keyword list and all — in one table cell.
        self.assertEqual(
            agents_md.first_sentence("Does the thing! TRIGGER when: noise, noise."),
            "Does the thing!",
        )
        self.assertEqual(
            agents_md.first_sentence("Where did it go? TRIGGER when: noise, noise."),
            "Where did it go?",
        )

    def test_a_summary_ending_in_a_bang_does_not_drag_triggers_into_the_row(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp, skills=(("freya-status", "Finds it fast!"),))
            row = [ln for ln in agents_md.render_block(store).splitlines()
                   if "freya-status" in ln][0]
            self.assertEqual(row, "| `freya-status` | Finds it fast! |")


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

    def test_a_fenced_example_of_the_markers_is_not_the_managed_block(self):
        # A team documenting the managed region in their own AGENTS.md puts
        # the markers at the start of a line *inside a code fence*. That is
        # an example, not the region: treating it as the real block deleted
        # the example's body and wrote the managed section inert inside the
        # fence — while reporting success.
        fenced = (
            "# House rules\n\nHow the block looks:\n\n"
            f"```markdown\n{agents_md.BEGIN}\nour example body\n{agents_md.END}\n```\n"
        )
        block = f"{agents_md.BEGIN}\nreal\n{agents_md.END}\n"
        merged = agents_md.merge(fenced, block)
        self.assertTrue(merged.startswith(fenced))
        self.assertIn("our example body", merged)
        self.assertTrue(merged.endswith(block))
        # And the appended block — not the fenced example — is what the
        # next run finds, so a second run is still a no-op.
        self.assertEqual(agents_md.merge(merged, block), merged)

    def test_a_fenced_example_alongside_a_real_block_updates_only_the_real_one(self):
        # Two line-start BEGIN markers, one of them fenced. Counting the
        # fenced one as a duplicate would refuse forever; treating it as the
        # real one would eat the example.
        fenced = (
            f"~~~\n{agents_md.BEGIN}\nour example body\n{agents_md.END}\n~~~\n\n"
        )
        old = f"{agents_md.BEGIN}\nold\n{agents_md.END}\n"
        new = f"{agents_md.BEGIN}\nnew\n{agents_md.END}\n"
        merged = agents_md.merge(fenced + old, new)
        self.assertTrue(merged.startswith(fenced))
        self.assertIn("our example body", merged)
        self.assertIn("new", merged)
        self.assertNotIn("\nold\n", merged)

    def test_an_indented_code_block_example_is_not_the_managed_block(self):
        # The other way to write a code block: four spaces. Those markers
        # are not at the start of a line, so they are already ignored — this
        # pins that guarantee rather than establishing it.
        indented = f"How the block looks:\n\n    {agents_md.BEGIN}\n    body\n    {agents_md.END}\n"
        block = f"{agents_md.BEGIN}\nreal\n{agents_md.END}\n"
        merged = agents_md.merge(indented, block)
        self.assertTrue(merged.startswith(indented))
        self.assertTrue(merged.endswith(block))

    def test_an_unclosed_fence_does_not_hide_a_real_block(self):
        # An unclosed fence is malformed markdown. Treating everything after
        # it as fenced would hide the real block from every future run, and
        # each run would then append *another* block — a file that grows
        # forever, which is worse than the defect being fixed. So an
        # unclosed run does not open a code block for marker detection.
        existing = f"# Mine\n\n```\nstray fence\n\n{agents_md.BEGIN}\nold\n{agents_md.END}\n"
        block = f"{agents_md.BEGIN}\nnew\n{agents_md.END}\n"
        merged = agents_md.merge(existing, block)
        self.assertIn("new", merged)
        self.assertNotIn("\nold\n", merged)
        self.assertEqual(merged.count(agents_md.BEGIN), 1)

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
            # The dry run probes the filesystem by writing a temp file; it
            # must take that file away again, or --dry-run litters the
            # user's repo with something .gitignore does not cover.
            self.assertEqual(list(project.iterdir()), [])

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

    @unittest.skipUnless(HAS_POSIX_MODES, "Windows has no POSIX mode bits")
    def test_a_preexisting_files_mode_survives_the_atomic_write(self):
        # `os.replace` swaps in a brand-new temp file born with the umask's
        # default mode, not the original's — without shutil.copystat, a
        # 0600 AGENTS.md silently comes back 0644 after every `freya init`.
        # The copystat call this guards is not skipped on Windows: it is also
        # what carries the read-only attribute and the timestamps across the
        # replace there. Only the 0600 assertion is unavailable.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            target = project / "AGENTS.md"
            target.write_text("# Mine\n", encoding="utf-8")
            os.chmod(target, 0o600)
            agents_md.init(store, project, out=lambda _: None)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)

    def test_a_symlinked_agents_md_is_written_through_not_replaced(self):
        # os.replace does not follow a symlink: replacing the raw,
        # unresolved path would unlink the symlink itself and put a plain
        # file where it used to be, breaking whatever the symlink pointed
        # at. Resolving to the real file first must make the write land on
        # the real file, leaving the symlink intact.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            root = Path(tmp).resolve()
            project = root / "project"
            project.mkdir()
            real = root / "real-AGENTS.md"
            real.write_text("# Mine\n", encoding="utf-8")
            link = project / "AGENTS.md"
            link.symlink_to(real)
            agents_md.init(store, project, out=lambda _: None)
            self.assertTrue(link.is_symlink())
            self.assertEqual(link.resolve(), real)
            self.assertIn(agents_md.BEGIN, real.read_text(encoding="utf-8"))

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
        # at fault — and, since init is the third place this phase found the
        # same "only ValueError is caught" defect, it must not escape as an
        # uncaught OSError either: it is reported and returns 2, naming the
        # store, not the project's AGENTS.md.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            lines = []
            with mock.patch.object(Path, "read_text", side_effect=OSError("boom")):
                code = agents_md.init(store, project, out=lines.append)
            self.assertEqual(code, 2)
            message = "\n".join(lines)
            self.assertIn("freya init:", message)
            self.assertIn(str(store), message)
            self.assertNotIn("command manifest", message)
            self.assertFalse((project / "AGENTS.md").exists())

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
            message = "\n".join(lines)
            self.assertIn("malformed", message)
            # The fault is the target's, so the message must name the target
            # — reporting it as "cannot read the skill store" was the
            # store-side misblame in the opposite direction.
            self.assertIn(str(project / "AGENTS.md"), message)
            self.assertNotIn(str(store), message)

    def test_a_non_utf8_agents_md_is_named_not_blamed_on_the_command_manifest(self):
        # UnicodeDecodeError is a ValueError, not an OSError, so it used to
        # escape init entirely and land in freya_cli.main's blanket handler,
        # which printed "cannot read the command manifest" and sent the user
        # to `freya doctor` — which then reports the install perfectly
        # healthy. The offending file is the user's own AGENTS.md.
        for label, raw in (
            ("latin-1", "# Café notes\n\nSome prose.\n".encode("latin-1")),
            # What Windows PowerShell 5.1 writes by default, and this
            # project ships an install.ps1.
            ("utf-16", "# Notes\n\nSome prose.\n".encode("utf-16")),
        ):
            with self.subTest(encoding=label), tempfile.TemporaryDirectory() as tmp:
                store = make_store(tmp)
                project = Path(tmp).resolve() / "project"
                project.mkdir()
                target = project / "AGENTS.md"
                target.write_bytes(raw)
                lines = []
                code = agents_md.init(store, project, out=lines.append)
                self.assertEqual(code, 2)
                message = "\n".join(lines)
                self.assertIn(str(target), message)
                self.assertIn("UTF-8", message)
                self.assertNotIn("command manifest", message)
                self.assertEqual(target.read_bytes(), raw)

    def test_a_store_with_no_skills_refuses_instead_of_emptying_the_table(self):
        # A store whose skills/ directory is missing renders a header-only
        # table: every skill row silently deleted from the user's AGENTS.md,
        # reported as "updated". `installer.main` and `freya doctor` both
        # treat that store state as an error; the one path that writes into
        # someone else's repo must not be the lenient one.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            agents_md.init(store, project, out=lambda _: None)
            before = (project / "AGENTS.md").read_bytes()
            shutil.rmtree(store / "skills")
            lines = []
            code = agents_md.init(store, project, out=lines.append)
            self.assertEqual(code, 2)
            self.assertIn("no skills found", "\n".join(lines))
            self.assertEqual((project / "AGENTS.md").read_bytes(), before)

    def test_dry_run_predicts_the_failure_a_real_run_would_hit(self):
        # --dry-run used to report "would create" and exit 0 for exactly the
        # projects where the real run exits 2, so the rehearsal disagreed
        # with the performance in the only cases anyone rehearses for.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            missing = Path(tmp).resolve() / "does-not-exist"
            occupied = Path(tmp).resolve() / "occupied"
            occupied.mkdir()
            (occupied / "AGENTS.md").mkdir()
            for label, project in (("missing dir", missing), ("dir in the way", occupied)):
                with self.subTest(case=label):
                    lines = []
                    code = agents_md.init(store, project, dry_run=True, out=lines.append)
                    self.assertEqual(code, 2)
                    self.assertNotIn("would", "\n".join(lines))
            self.assertFalse(missing.exists())
            self.assertEqual([p.name for p in occupied.iterdir()], ["AGENTS.md"])

    @unittest.skipUnless(os.name == "posix", "mode bits are meaningless on Windows")
    def test_the_replacement_is_never_world_readable_while_it_is_being_written(self):
        # The temp file used to be born with the umask's default mode and
        # only tightened *after* the content was written, so every byte of a
        # deliberately-private 0600 AGENTS.md was readable by any local user
        # for the duration of the write.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            target = project / "AGENTS.md"
            target.write_text("# Secret notes\n", encoding="utf-8")
            os.chmod(target, 0o600)
            seen = []
            real_copymode = shutil.copymode

            def spy(src, dst, *a, **kw):
                seen.append(stat.S_IMODE(os.stat(dst).st_mode))
                return real_copymode(src, dst, *a, **kw)

            with mock.patch.object(agents_md.shutil, "copymode", spy):
                agents_md.init(store, project, out=lambda _: None)
            self.assertEqual(len(seen), 1)
            self.assertEqual(seen[0] & 0o077, 0)

    def test_an_updated_file_gets_a_new_mtime(self):
        # shutil.copystat carried the original's mtime onto the replacement,
        # so an AGENTS.md whose contents had just changed still looked
        # untouched to editors, `find -newer`, make and rsync. Only the
        # permission bits were ever wanted across the swap.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            target = project / "AGENTS.md"
            target.write_text("# Mine\n", encoding="utf-8")
            os.utime(target, (1000000, 1000000))
            agents_md.init(store, project, out=lambda _: None)
            self.assertGreater(target.stat().st_mtime, 1000000)

    @unittest.skipUnless(hasattr(os, "chflags"), "BSD/macOS file flags only")
    def test_a_failed_write_removes_its_own_temp_file(self):
        # shutil.copystat copies st_flags too, so on macOS an immutable
        # (chflags uchg) AGENTS.md made the temp file immutable as well:
        # os.replace failed, and the cleanup path could not delete its own
        # temp, leaving an unremovable .freya-init-*.tmp in the user's repo
        # that no .gitignore covers.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            target = project / "AGENTS.md"
            target.write_text("# Mine\n", encoding="utf-8")
            os.chflags(target, stat.UF_IMMUTABLE)
            try:
                lines = []
                code = agents_md.init(store, project, out=lines.append)
                self.assertEqual(code, 2)
                leftovers = [p.name for p in project.iterdir() if p.name != "AGENTS.md"]
                self.assertEqual(leftovers, [])
            finally:
                os.chflags(target, 0)

    def test_the_block_adopts_the_prose_line_ending_even_when_it_outnumbers_it(self):
        # The newline vote counted the ~30 lines of the managed block — this
        # module's own output — against the user's prose. On Windows a block
        # first written into an empty file (LF, the new-file default) then
        # outvoted every shorter CRLF file forever, so the block could never
        # convert and the document stayed permanently mixed.
        with tempfile.TemporaryDirectory() as tmp:
            store = make_store(tmp)
            project = Path(tmp).resolve() / "project"
            project.mkdir()
            target = project / "AGENTS.md"
            agents_md.init(store, project, out=lambda _: None)
            target.write_bytes(b"# My project\r\n\r\nCRLF notes.\r\n\r\n"
                               + target.read_bytes())
            agents_md.init(store, project, out=lambda _: None)
            data = target.read_bytes()
            self.assertIn(agents_md.BEGIN.encode("utf-8") + b"\r\n", data)
            self.assertTrue(data.startswith(b"# My project\r\n"))
            # And it stays put: the converted block must not flip back.
            agents_md.init(store, project, out=lambda _: None)
            self.assertEqual(target.read_bytes(), data)
