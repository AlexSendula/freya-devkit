#!/usr/bin/env python3
"""Proof suite for search_specs.py — corpus discovery, filtering and output.

Builds throwaway fixture projects on disk and asserts what the loader finds and
what the filters keep. Covers SPEC-017 / BEH-082..086.

This module is the read side every other spec-manager script imports
(`verify_intent`, `verify_links`, `drift`, `contradictions` all call
`load_specs`/`load_all_specs`/`find_specs_dir`), so a silently shortened corpus
here is a silently shortened corpus for all of them — which is why the cases
about what happens to an unreadable file are the load-bearing ones in this
file, not the filter cases.

Run:  python test_search_specs.py
"""

import contextlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_specs import (  # noqa: E402
    SpecCorpusError,
    find_specs_dir,
    format_json,
    format_paths,
    format_table,
    load_all_specs,
    load_specs,
    main,
    parse_spec_file,
    search_specs,
)


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _spec(spec_id, title="Some Title", category="general", tags=("general",),
          status="draft", certainty=50, body="Ordinary body text.", decisions=()):
    """Render a spec file. Column-0 frontmatter, no dedent."""
    text = (
        "---\n"
        f"id: {spec_id}\n"
        f"title: {title}\n"
        f"category: {category}\n"
        f"tags: [{', '.join(tags)}]\n"
        f"status: {status}\n"
        f"certainty: {certainty}\n"
        "created: 2026-08-21\n"
        "updated: 2026-08-21\n"
    )
    if decisions:
        text += "intentional_decisions:\n"
        for d in decisions:
            text += f"  - {d}\n"
    return text + "---\n\n" + body + "\n"


def _ids(specs):
    return sorted(s.id for s in specs)


class _SpecFixture(unittest.TestCase):
    """Shared temp-project plumbing for every case below."""

    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _specs_dir(self, root):
        return str(root / "knowledge-base" / "specs")

    def _corpus(self, root, files):
        """`files` is {filename: rendered spec text}; returns the loaded specs,
        ordered by id so a sort assertion has a known starting order."""
        for name, text in files.items():
            _write(root / "knowledge-base" / "specs" / name, text)
        specs = load_all_specs(self._specs_dir(root))
        specs.sort(key=lambda s: s.id)
        return specs

    def _run_main(self, *args):
        """Drive main() with argv and return everything it printed to stdout."""
        return self._run_cli(*args)[0]

    def _run_cli(self, *args):
        """(stdout, stderr, exit code) from main(). Exit 0 is falling off the end."""
        out, err = io.StringIO(), io.StringIO()
        code = 0
        with mock.patch.object(sys, "argv", ["search_specs.py", *args]):
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                try:
                    main()
                except SystemExit as exc:
                    code = exc.code or 0
        return out.getvalue(), err.getvalue(), code


# A body whose distinctive terms straddle the preview window. `filler ` * 100 is
# 700 characters, so BEYONDPREVIEW sits well past 500 in the collapsed body.
STRADDLING_BODY = (
    "# Heading\n"
    "\n"
    "PREVIEWTOKEN sits near the top.\n"
    "\n"
    + ("filler " * 100)
    + "\n\nBEYONDPREVIEW sits past the window.\n"
)


class SearchCase(_SpecFixture):
    def test_query_matches_title_tags_and_preview(self):
        """BEH-082. The four searchable fields are title, category, tags and the
        body *preview* — not the body. Measured on this fixture: the collapsed
        body is 779 characters, the preview keeps 499 of them, and BEYONDPREVIEW
        starts at index 743 — so it is in the file, in the corpus, and invisible
        to `--query`. SPEC-017 records that as intentional; a scan that reads an
        empty `--query` result as "undocumented" is over-reading the tool.
        """
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-001.md": _spec("SPEC-001", title="Passkey Login",
                                 category="authentication",
                                 tags=("webauthn", "hardware-key"),
                                 body=STRADDLING_BODY),
            "SPEC-002.md": _spec("SPEC-002", title="Invoice Export",
                                 category="billing", tags=("reporting",)),
        })
        self.assertEqual(_ids(specs), ["SPEC-001", "SPEC-002"])

        # One term per field, each unique to the field it lives in.
        self.assertEqual(_ids(search_specs(specs, query="passkey")), ["SPEC-001"])
        self.assertEqual(_ids(search_specs(specs, query="authentication")), ["SPEC-001"])
        self.assertEqual(_ids(search_specs(specs, query="hardware-key")), ["SPEC-001"])
        self.assertEqual(_ids(search_specs(specs, query="PREVIEWTOKEN")), ["SPEC-001"])

        # Case-insensitive in both directions.
        self.assertEqual(_ids(search_specs(specs, query="PASSKEY")), ["SPEC-001"])
        self.assertEqual(_ids(search_specs(specs, query="previewtoken")), ["SPEC-001"])

        # Past the window: present in the file, absent from the search.
        self.assertIn("BEYONDPREVIEW", (root / "knowledge-base/specs/SPEC-001.md").read_text())
        self.assertEqual(search_specs(specs, query="BEYONDPREVIEW"), [])

        # A term in neither spec matches neither.
        self.assertEqual(search_specs(specs, query="kubernetes"), [])

    def test_the_preview_is_capped_at_five_hundred_characters(self):
        """The cap is the mechanism BEH-082's blind spot rests on, so pin the
        number rather than only its consequence. 500 characters of the
        whitespace-collapsed body, then stripped — a body opening with a blank
        line yields 499, because the collapsed leading newline costs one slot.
        """
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-001.md": _spec("SPEC-001", body="z" * 4000),
        })
        self.assertLessEqual(len(specs[0].content_preview), 500)
        self.assertEqual(len(specs[0].content_preview), 499)
        self.assertEqual(specs[0].content_preview, "z" * 499)

    def test_the_preview_collapses_whitespace_so_a_phrase_can_span_a_line_break(self):
        """`re.sub(r'\\s+', ' ', body)` before the slice, which is the only reason
        a multi-word `--query` works at all: spec bodies are hard-wrapped
        markdown, so almost every phrase worth searching for has a newline
        somewhere inside it. Added after a mutation run: dropping the collapse
        and keeping `body[:500]` left every other test in this file green.
        """
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-001.md": _spec("SPEC-001", body=(
                "The per-IP rate\nlimit is deliberate and   documented here.\n")),
        })
        self.assertEqual(specs[0].content_preview,
                         "The per-IP rate limit is deliberate and documented here.")
        self.assertEqual(_ids(search_specs(specs, query="rate limit is deliberate")),
                         ["SPEC-001"])

    def test_the_query_is_a_substring_match_not_a_word_match(self):
        """`--query auth` is documented as a substring match, so it finds
        `authentication` and `WebAuthn` alike. Anything asserting word
        boundaries here would be asserting a tool this is not."""
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-001.md": _spec("SPEC-001", title="Passkey Login",
                                 category="authentication", tags=("webauthn",)),
        })
        self.assertEqual(_ids(search_specs(specs, query="auth")), ["SPEC-001"])
        self.assertEqual(_ids(search_specs(specs, query="asskey")), ["SPEC-001"])

    def test_filters_are_case_insensitive_and_compose(self):
        """BEH-083. Four independent `continue`s in one loop: each filter is an
        exact, case-folded equality, and every filter given must match. The two
        halves are separable defects — a `startswith` would pass an
        exactness-free test, and an `or` would pass a one-filter-at-a-time test —
        so both are asserted here.
        """
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-201.md": _spec("SPEC-201", category="Auth", tags=("Security",),
                                 status="Implemented"),
            "SPEC-202.md": _spec("SPEC-202", category="Auth", tags=("Security",),
                                 status="draft"),
            "SPEC-203.md": _spec("SPEC-203", category="Data", tags=("Privacy",),
                                 status="Implemented"),
        })
        self.assertEqual(_ids(specs), ["SPEC-201", "SPEC-202", "SPEC-203"])

        # Case-insensitive, one filter at a time.
        self.assertEqual(_ids(search_specs(specs, tag="SECURITY")), ["SPEC-201", "SPEC-202"])
        self.assertEqual(_ids(search_specs(specs, category="auth")), ["SPEC-201", "SPEC-202"])
        self.assertEqual(_ids(search_specs(specs, status="IMPLEMENTED")), ["SPEC-201", "SPEC-203"])
        self.assertEqual(_ids(search_specs(specs, spec_id="spec-202")), ["SPEC-202"])

        # Exact, not prefix or substring.
        self.assertEqual(search_specs(specs, tag="sec"), [])
        self.assertEqual(search_specs(specs, category="au"), [])
        self.assertEqual(search_specs(specs, status="implement"), [])
        self.assertEqual(search_specs(specs, spec_id="SPEC-20"), [])

        # AND, not OR: adding a filter can only narrow.
        self.assertEqual(_ids(search_specs(specs, category="AUTH", status="DRAFT")), ["SPEC-202"])
        self.assertEqual(
            _ids(search_specs(specs, category="auth", tag="security", status="implemented")),
            ["SPEC-201"])
        # Each half of this pair matches something; the conjunction matches nothing.
        self.assertEqual(_ids(search_specs(specs, category="data")), ["SPEC-203"])
        self.assertEqual(search_specs(specs, category="data", tag="security"), [])
        self.assertEqual(search_specs(specs, spec_id="SPEC-201", status="draft"), [])

    def test_no_filters_at_all_returns_the_whole_corpus(self):
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-201.md": _spec("SPEC-201"),
            "SPEC-202.md": _spec("SPEC-202"),
        })
        self.assertEqual(_ids(search_specs(specs)), ["SPEC-201", "SPEC-202"])

    def test_intentional_only_keeps_specs_that_declare_decisions(self):
        """`--intentional` is what the security scan uses to ask "was this on
        purpose?", so an empty `intentional_decisions` must not read as one."""
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-201.md": _spec("SPEC-201", decisions=("Rate limit is per-IP by design",)),
            "SPEC-202.md": _spec("SPEC-202"),
        })
        self.assertEqual(_ids(search_specs(specs, intentional_only=True)), ["SPEC-201"])

    def test_sort_certainty_orders_the_least_trustworthy_record_first(self):
        """The review worklist reads top-down, so lowest-first is the whole
        point of the flag. The fixture's id order is the reverse of its
        certainty order, so an unsorted return cannot pass this."""
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-201.md": _spec("SPEC-201", certainty=90),
            "SPEC-202.md": _spec("SPEC-202", certainty=30),
            "SPEC-203.md": _spec("SPEC-203", certainty=60),
        })
        self.assertEqual([s.certainty for s in specs], [90, 30, 60])
        ordered = search_specs(specs, sort_by_certainty=True)
        self.assertEqual([s.certainty for s in ordered], [30, 60, 90])
        self.assertEqual([s.id for s in ordered], ["SPEC-202", "SPEC-203", "SPEC-201"])


class CertaintyCase(_SpecFixture):
    def _band(self, root):
        return self._corpus(root, {
            "SPEC-301.md": _spec("SPEC-301", certainty=69),
            "SPEC-302.md": _spec("SPEC-302", certainty=70),
            "SPEC-303.md": _spec("SPEC-303", certainty=71),
        })

    def test_below_excludes_threshold_min_includes_it(self):
        """BEH-084. The asymmetry is deliberate and is one line each:
        `certainty >= max` drops, `certainty < min` drops. `freya spec
        --sort-certainty --below 100` is the documented review query and is only
        correct while 100 is excluded — SPEC-017 flags "make the bounds
        consistent" as the change that would silently empty the worklist. So the
        boundary value itself is asserted on both sides, not just the interior.
        """
        root = self._root()
        specs = self._band(root)

        # --below / --max-certainty: exclusive at the threshold.
        self.assertEqual(_ids(search_specs(specs, max_certainty=70)), ["SPEC-301"])
        # --min-certainty: inclusive at the same threshold.
        self.assertEqual(_ids(search_specs(specs, min_certainty=70)), ["SPEC-302", "SPEC-303"])
        # The two are exact complements over the corpus — no spec is in both,
        # none is in neither.
        self.assertEqual(search_specs(specs, max_certainty=70, min_certainty=70), [])

        # Same thing through the flags the behavior actually names.
        dir_ = self._specs_dir(root)
        below = self._run_main("--dir", dir_, "--below", "70", "--format", "paths")
        self.assertIn("SPEC-301.md", below)
        self.assertNotIn("SPEC-302.md", below)
        at_least = self._run_main("--dir", dir_, "--min-certainty", "70", "--format", "paths")
        self.assertIn("SPEC-302.md", at_least)
        self.assertNotIn("SPEC-301.md", at_least)

    def test_the_documented_review_query_keeps_everything_short_of_full_certainty(self):
        """`--sort-certainty --below 100` is the query the skill tells reviewers
        to run; a spec at 100 must not come back in it."""
        root = self._root()
        self._corpus(root, {
            "SPEC-301.md": _spec("SPEC-301", certainty=100),
            "SPEC-302.md": _spec("SPEC-302", certainty=99),
        })
        out = self._run_main("--dir", self._specs_dir(root),
                             "--sort-certainty", "--below", "100", "--format", "paths")
        self.assertIn("SPEC-302.md", out)
        self.assertNotIn("SPEC-301.md", out)

    def test_below_overrides_max_certainty_when_both_are_given(self):
        """`--below` is documented as a shorthand for `--max-certainty`, and it
        wins outright rather than combining — the last two lines before the
        search assign, they do not `min()`."""
        root = self._root()
        self._band(root)
        out = self._run_main("--dir", self._specs_dir(root),
                             "--max-certainty", "70", "--below", "71", "--format", "paths")
        self.assertIn("SPEC-301.md", out)
        self.assertIn("SPEC-302.md", out)   # kept by --below 71, dropped by --max 70
        self.assertNotIn("SPEC-303.md", out)

    def test_min_and_max_compose_into_a_half_open_band(self):
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-301.md": _spec("SPEC-301", certainty=40),
            "SPEC-302.md": _spec("SPEC-302", certainty=50),
            "SPEC-303.md": _spec("SPEC-303", certainty=60),
            "SPEC-304.md": _spec("SPEC-304", certainty=70),
        })
        self.assertEqual(_ids(search_specs(specs, min_certainty=50, max_certainty=70)),
                         ["SPEC-302", "SPEC-303"])

    def test_a_certainty_of_zero_is_a_bound_not_an_absent_filter(self):
        """`if min_certainty is not None` rather than `if min_certainty` — 0 is
        a real bound, and `--below 0` must return nothing rather than
        everything."""
        root = self._root()
        specs = self._corpus(root, {
            "SPEC-301.md": _spec("SPEC-301", certainty=0),
            "SPEC-302.md": _spec("SPEC-302", certainty=50),
        })
        self.assertEqual(search_specs(specs, max_certainty=0), [])
        self.assertEqual(_ids(search_specs(specs, min_certainty=0)), ["SPEC-301", "SPEC-302"])


class DiscoveryCase(_SpecFixture):
    def test_legacy_docs_specs_fallback(self):
        """BEH-085. The knowledge-base layout arrived after projects were already
        carrying specs under `docs/`, and SPEC-017 calls the fallback a
        compatibility promise: migrating must never be the price of running a
        query. The fixture project is nested one level down so the parent-directory
        candidates (`../knowledge-base/specs`, tried *before* `docs/specs`) cannot
        be what answers.
        """
        outer = self._root()
        project = outer / "unmigrated-project"
        _write(project / "docs" / "specs" / "SPEC-401.md",
               _spec("SPEC-401", title="Legacy Record", category="legacy"))

        found = Path(find_specs_dir(str(project)))
        self.assertEqual(found.name, "specs")
        self.assertEqual(found.parent.name, "docs")
        self.assertEqual(found.parent.parent.name, "unmigrated-project")

        specs = load_all_specs(str(found))
        self.assertEqual(_ids(specs), ["SPEC-401"])
        self.assertEqual(_ids(search_specs(specs, category="legacy")), ["SPEC-401"])

    def test_the_knowledge_base_layout_wins_when_a_project_has_both(self):
        """The fallback is a fallback. A half-migrated project with a stale
        `docs/specs` beside a live `knowledge-base/specs` must read the live one."""
        outer = self._root()
        project = outer / "half-migrated"
        _write(project / "knowledge-base" / "specs" / "SPEC-402.md", _spec("SPEC-402"))
        _write(project / "docs" / "specs" / "SPEC-401.md", _spec("SPEC-401"))

        found = Path(find_specs_dir(str(project)))
        self.assertEqual(found.parent.name, "knowledge-base")
        self.assertEqual(_ids(load_all_specs(str(found))), ["SPEC-402"])

    def test_a_project_with_no_specs_anywhere_gets_a_path_that_need_not_exist(self):
        """`find_specs_dir` returns a default rather than raising, so every
        caller is free of a not-found branch; `load_all_specs` then returns []
        for a directory that is not there. SPEC-017 records the cost: exit 0
        from `freya spec` is not evidence that a corpus exists."""
        outer = self._root()
        project = outer / "empty-project"
        project.mkdir()

        found = Path(find_specs_dir(str(project)))
        self.assertEqual(found.name, "specs")
        self.assertEqual(found.parent.name, "knowledge-base")
        self.assertFalse(found.exists())
        self.assertEqual(load_all_specs(str(found)), [])

    def test_malformed_spec_warns_and_others_load(self):
        """BEH-086. This is the only thing standing between one broken spec file
        and a silently shortened corpus for every consumer of the loader —
        `verify_intent`, `verify_links`, `drift` and `contradictions` all read
        through it, and a spec that vanishes from the corpus is a spec whose
        gates stop firing. Three halves now, not two: the survivors still come
        back, the loss is announced on stderr, *and* the exit code disowns the
        answer. The warning alone was the whole defence until 2026-08-24, and it
        is written to a stream no skill-to-skill caller reads.
        """
        root = self._root()
        _write(root / "knowledge-base/specs/SPEC-501.md", _spec("SPEC-501"))
        _write(root / "knowledge-base/specs/SPEC-502.md", _spec("SPEC-502"))
        # Opened but never closed — FrontmatterError, raised before the id is read.
        _write(root / "knowledge-base/specs/SPEC-503-broken.md",
               "---\nid: SPEC-503\ntitle: Truncated Record\n")

        out, err, code = self._run_cli("--dir", self._specs_dir(root), "--format", "paths")

        self.assertIn("SPEC-501.md", out)
        self.assertIn("SPEC-502.md", out)
        self.assertIn("SPEC-503-broken.md", err)
        self.assertIn("could not be read", err)
        self.assertEqual(code, 1, "an answer known to be short may not exit 0")

    def test_a_tab_indented_spec_is_also_reported_rather_than_dropped(self):
        """A second, differently-shaped parse failure, so the alarm is not
        pinned to one error message. Tabs are rejected by the frontmatter
        grammar outright."""
        root = self._root()
        _write(root / "knowledge-base/specs/SPEC-501.md", _spec("SPEC-501"))
        _write(root / "knowledge-base/specs/SPEC-504-tabs.md",
               "---\nid: SPEC-504\ntitle: Tabbed\nrelated_code:\n\t- src/a.ts\n---\n\nbody\n")

        specs, unreadable = load_specs(self._specs_dir(root))

        self.assertEqual(_ids(specs), ["SPEC-501"])
        self.assertEqual([Path(u.file_path).name for u in unreadable],
                         ["SPEC-504-tabs.md"])
        self.assertIn("tab indentation", unreadable[0].reason)

    def test_a_record_that_lost_its_id_is_an_alarm_not_an_absence(self):
        """The quietest way into the failure, and the reason it outranks a
        forgery route: no attacker, one deleted line.

        `id:` is the only field a spec is addressed by, so a hand edit or a
        merge conflict that drops it used to remove the file from the corpus
        with nothing printed on any stream — quieter even than the
        FrontmatterError cases, which at least reached stderr. SPEC-017 raised
        this as an open question ("should a file with frontmatter but no `id`
        warn?") and the answer is that a record which lost its id is a record
        the corpus is missing.
        """
        root = self._root()
        _write(root / "knowledge-base/specs/SPEC-501.md", _spec("SPEC-501"))
        # Byte-for-byte SPEC-502 with the single line `id: SPEC-502` removed.
        _write(root / "knowledge-base/specs/SPEC-502.md",
               _spec("SPEC-502").replace("id: SPEC-502\n", "", 1))

        specs, unreadable = load_specs(self._specs_dir(root))

        self.assertEqual(_ids(specs), ["SPEC-501"])
        self.assertEqual([Path(u.file_path).name for u in unreadable], ["SPEC-502.md"])
        self.assertIn("no `id:`", unreadable[0].reason)

    def test_a_fence_that_does_not_start_at_line_one_is_a_broken_record(self):
        """The `id:` arm above closed one keystroke and left a quieter one open.

        `parse_frontmatter` returns `{}` unless line 1 is exactly `---`, so the
        `if not frontmatter: return None` discriminator answered "does this file
        OPEN with a fence", not "does it have one". A spec with a single blank
        line inserted at the top — or behind a UTF-8 BOM, which Windows editors
        write by default and which `str.strip()` does not remove — took the prose
        branch and left the corpus in silence. Both Tier-1 gates then printed
        their success sentence over a file they never read, and `--advance` moved
        the baseline across it.

        Measured on the version with only the `id:` arm: inserting one blank line
        is a whitespace-only diff, and quieter than deleting the `id:` line the
        arm above was written for.
        """
        shapes = {
            "SPEC-601.md": "\n" + _spec("SPEC-601"),            # one blank line
            "SPEC-602.md": "﻿" + _spec("SPEC-602"),        # UTF-8 BOM
            "SPEC-603.md": "﻿\n" + _spec("SPEC-603"),      # both
        }
        root = self._root()
        _write(root / "knowledge-base/specs/SPEC-600.md", _spec("SPEC-600"))
        for name, text in shapes.items():
            _write(root / "knowledge-base/specs" / name, text)

        specs, unreadable = load_specs(self._specs_dir(root))

        self.assertEqual(_ids(specs), ["SPEC-600"])
        self.assertEqual(sorted(Path(u.file_path).name for u in unreadable),
                         sorted(shapes))
        for u in unreadable:
            self.assertIn("does not start at line 1", u.reason)

    def test_a_file_with_no_frontmatter_at_all_is_quietly_not_a_spec(self):
        """The other side of the discriminator, and the reason it is the
        frontmatter block rather than the `id`.

        The specs tree legitimately holds non-records — the index README, a
        prose note, a template — and alarming on each of them on every query
        would train people to ignore the channel the case above depends on. So
        `parse_frontmatter` returning an empty mapping stays a silent skip.
        Asserting the silence is what stops it being 'hardened' into noise.
        """
        root = self._root()
        _write(root / "knowledge-base/specs/SPEC-501.md", _spec("SPEC-501"))
        _write(root / "knowledge-base/specs/notes.md", "Just prose, no frontmatter at all.\n")
        _write(root / "knowledge-base/specs/checklist.md", "# Checklist\n\n- one\n- two\n")

        err = io.StringIO()
        with contextlib.redirect_stderr(err):
            specs, unreadable = load_specs(self._specs_dir(root))

        self.assertEqual(_ids(specs), ["SPEC-501"])
        self.assertEqual(unreadable, [])
        self.assertEqual(err.getvalue(), "")
        self.assertEqual(_ids(load_all_specs(self._specs_dir(root))), ["SPEC-501"])

    def test_load_all_specs_raises_rather_than_answering_a_short_corpus(self):
        """The name a new consumer reaches for may not quietly answer a subset.

        `drift` and `contradictions` still call this one, so the exception is
        what stops them scoping a checkpoint to a corpus they could not read.
        The exception carries the files, not just the fact, so whoever catches
        it can name them.
        """
        root = self._root()
        _write(root / "knowledge-base/specs/SPEC-501.md", _spec("SPEC-501"))
        _write(root / "knowledge-base/specs/SPEC-502-broken.md",
               "---\nid: SPEC-502\ntitle: Truncated\n")

        with self.assertRaises(SpecCorpusError) as caught:
            load_all_specs(self._specs_dir(root))

        self.assertEqual([Path(u.file_path).name for u in caught.exception.unreadable],
                         ["SPEC-502-broken.md"])
        self.assertIn("SPEC-502-broken.md", str(caught.exception))
        # The control: a corpus with nothing wrong in it still answers.
        (root / "knowledge-base/specs/SPEC-502-broken.md").unlink()
        self.assertEqual(_ids(load_all_specs(self._specs_dir(root))), ["SPEC-501"])

    def test_a_certainty_that_is_not_a_number_is_an_alarm(self):
        """`certainty: high` reaches `int()` inside the constructor, and the
        broad `except` around it used to turn that into the same silent drop.
        A frontmatter field the grammar accepts and the schema does not is the
        most likely authoring mistake of the four."""
        root = self._root()
        _write(root / "knowledge-base/specs/SPEC-501.md", _spec("SPEC-501"))
        _write(root / "knowledge-base/specs/SPEC-505.md",
               _spec("SPEC-505").replace("certainty: 50", "certainty: high"))

        specs, unreadable = load_specs(self._specs_dir(root))

        self.assertEqual(_ids(specs), ["SPEC-501"])
        self.assertEqual([Path(u.file_path).name for u in unreadable], ["SPEC-505.md"])

    def test_readme_is_skipped_by_name_even_when_it_carries_an_id(self):
        """The index README is prose about the corpus, not a member of it."""
        root = self._root()
        _write(root / "knowledge-base/specs/SPEC-501.md", _spec("SPEC-501"))
        _write(root / "knowledge-base/specs/README.md", _spec("SPEC-000", title="Index"))
        _write(root / "knowledge-base/specs/features/readme.md", _spec("SPEC-999"))

        specs = load_all_specs(self._specs_dir(root))
        self.assertEqual(_ids(specs), ["SPEC-501"])

    def test_specs_are_loaded_recursively_from_subdirectories(self):
        """The corpus is organised into category folders, so a non-recursive
        walk would return an empty set on every real project."""
        root = self._root()
        _write(root / "knowledge-base/specs/features/SPEC-601.md", _spec("SPEC-601"))
        _write(root / "knowledge-base/specs/security/nested/SPEC-602.md", _spec("SPEC-602"))

        self.assertEqual(_ids(load_all_specs(self._specs_dir(root))),
                         ["SPEC-601", "SPEC-602"])

    def test_parse_spec_file_returns_none_for_a_file_that_is_not_a_spec(self):
        root = self._root()
        path = root / "notes.md"
        _write(path, "# Just a note\n")
        self.assertIsNone(parse_spec_file(str(path)))

    def test_parse_spec_file_raises_for_a_record_it_cannot_read(self):
        """None and an exception are the two answers, and which one a file gets
        is the whole decision. Asserted at the single-file level as well as
        through the loader, because `load_specs` is what turns one into the
        other and a fix applied only there would leave `parse_spec_file` still
        handing a caller a shortened truth."""
        root = self._root()
        no_id = root / "lost-its-id.md"
        _write(no_id, "---\ntitle: A Record\ncategory: general\nstatus: draft\n---\n\nbody\n")
        with self.assertRaises(SpecCorpusError):
            parse_spec_file(str(no_id))

        truncated = root / "truncated.md"
        _write(truncated, "---\nid: SPEC-900\ntitle: Truncated\n")
        with self.assertRaises(SpecCorpusError):
            parse_spec_file(str(truncated))


class FormatCase(_SpecFixture):
    def _two(self, root):
        return self._corpus(root, {
            "SPEC-701.md": _spec("SPEC-701", title="Passkey Login", category="auth",
                                 status="implemented", certainty=90,
                                 decisions=("First decision", "Second decision",
                                            "Third decision")),
            "SPEC-702.md": _spec("SPEC-702", title="Invoice Export", category="billing",
                                 status="draft", certainty=40),
        })

    def test_table_renders_a_row_per_spec_under_a_markdown_header(self):
        root = self._root()
        out = format_table(self._two(root))
        self.assertIn("| ID | Title | Category | Certainty | Status |", out)
        self.assertIn("| SPEC-701 | Passkey Login | auth | 90% | implemented |", out)
        self.assertIn("| SPEC-702 | Invoice Export | billing | 40% | draft |", out)
        self.assertIn("Found 2 specs matching criteria.", out)

    def test_the_table_footer_is_singular_for_one_result(self):
        """`'s' if len != 1` — the branch reads backwards easily enough to be
        worth a line."""
        root = self._root()
        one = [s for s in self._two(root) if s.id == "SPEC-701"]
        self.assertIn("Found 1 spec matching criteria.", format_table(one))
        self.assertNotIn("Found 1 specs", format_table(one))

    def test_an_empty_result_says_so_instead_of_printing_an_empty_table(self):
        self.assertEqual(format_table([]), "No specs found matching criteria.")

    def test_the_intentional_column_shows_two_decisions_and_counts_the_rest(self):
        root = self._root()
        out = format_table(self._two(root), show_intentional=True)
        self.assertIn("| Intentional Decisions |", out)
        self.assertIn("First decision; Second decision (+1 more)", out)
        self.assertNotIn("Third decision", out)

    def test_a_spec_with_no_decisions_gets_a_dash_not_an_empty_cell(self):
        root = self._root()
        out = format_table(self._two(root), show_intentional=True)
        self.assertIn("| SPEC-702 | Invoice Export | billing | 40% | draft | - |", out)

    def test_json_round_trips_through_json_loads(self):
        root = self._root()
        parsed = json.loads(format_json(self._two(root)))
        self.assertIsInstance(parsed, list)
        self.assertEqual([r["id"] for r in parsed], ["SPEC-701", "SPEC-702"])
        self.assertEqual(parsed[0]["title"], "Passkey Login")
        self.assertEqual(parsed[0]["certainty"], 90)
        self.assertEqual(parsed[0]["tags"], ["general"])
        self.assertEqual(parsed[0]["intentional_decisions"],
                         ["First decision", "Second decision", "Third decision"])
        self.assertTrue(parsed[0]["file_path"].endswith("SPEC-701.md"))

    def test_json_of_an_empty_result_is_an_empty_array(self):
        self.assertEqual(json.loads(format_json([])), [])

    def test_paths_emits_one_bare_file_path_per_line(self):
        """`--format paths` is the shell-pipeline format; anything but bare
        paths would break `freya spec ... --format paths | xargs`."""
        root = self._root()
        lines = format_paths(self._two(root)).split("\n")
        self.assertEqual(len(lines), 2)
        for line in lines:
            self.assertTrue(line.endswith(".md"), line)
            self.assertTrue(os.path.isabs(line), line)
        self.assertEqual(format_paths([]), "")


class MainCase(_SpecFixture):
    def _project(self):
        root = self._root()
        self._corpus(root, {
            "SPEC-801.md": _spec("SPEC-801", title="Passkey Login", category="auth",
                                 status="implemented", certainty=90,
                                 decisions=("Per-IP rate limit is deliberate",)),
            "SPEC-802.md": _spec("SPEC-802", title="Invoice Export", category="billing",
                                 status="draft", certainty=40),
        })
        return root

    def test_the_default_output_format_is_the_markdown_table(self):
        out = self._run_main("--dir", self._specs_dir(self._project()))
        self.assertIn("# Spec Search Results", out)
        self.assertIn("| SPEC-801 | Passkey Login | auth | 90% | implemented |", out)
        self.assertIn("Found 2 specs matching criteria.", out)

    def test_format_json_prints_parseable_json_on_stdout(self):
        """Sorted here because `main` reloads through `rglob`, whose order is the
        filesystem's — the CLI promises no order unless `--sort-certainty` asks
        for one."""
        out = self._run_main("--dir", self._specs_dir(self._project()), "--format", "json")
        self.assertEqual(sorted(r["id"] for r in json.loads(out)), ["SPEC-801", "SPEC-802"])

    def test_format_paths_prints_only_paths(self):
        out = self._run_main("--dir", self._specs_dir(self._project()),
                             "--format", "paths")
        lines = out.strip().split("\n")
        self.assertEqual(len(lines), 2)
        self.assertTrue(all(line.endswith(".md") for line in lines), out)

    def test_the_filter_flags_reach_the_search(self):
        root = self._project()
        out = self._run_main("--dir", self._specs_dir(root), "--category", "AUTH",
                             "--format", "paths")
        self.assertIn("SPEC-801.md", out)
        self.assertNotIn("SPEC-802.md", out)
        out = self._run_main("--dir", self._specs_dir(root), "--query", "invoice",
                             "--format", "paths")
        self.assertIn("SPEC-802.md", out)
        self.assertNotIn("SPEC-801.md", out)

    def test_the_intentional_flag_both_filters_and_adds_the_column(self):
        """One flag doing two jobs — `--intentional` is passed as
        `intentional_only` to the search *and* as `show_intentional` to the
        table. Dropping either half still prints a plausible table."""
        out = self._run_main("--dir", self._specs_dir(self._project()), "--intentional")
        self.assertIn("| Intentional Decisions |", out)
        self.assertIn("Per-IP rate limit is deliberate", out)
        self.assertIn("SPEC-801", out)
        self.assertNotIn("SPEC-802", out)
        self.assertIn("Found 1 spec matching criteria.", out)

    def test_a_missing_specs_directory_prints_the_empty_message_and_returns(self):
        """No corpus and no matches are indistinguishable at the CLI — SPEC-017
        flags that as an open question, and this pins the current answer so a
        change to it is a visible change."""
        root = self._root()
        out = self._run_main("--dir", str(root / "nowhere" / "specs"))
        self.assertEqual(out.strip(), "No specs found matching criteria.")


if __name__ == "__main__":
    unittest.main(verbosity=2)
