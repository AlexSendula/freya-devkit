#!/usr/bin/env python3
"""Proof suite for collect_status.py — the status aggregator."""
import json
import os
import subprocess
import sys
import tempfile
import unittest
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import collect_status  # noqa: E402

SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "collect_status.py")

# CommonMark §2.4: the escapable set is the ASCII punctuation characters.
_ASCII_PUNCTUATION = set("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~")


def gfm_cells(row, columns):
    r"""The cells a GFM renderer shows for one table row, by GFM's rule.

    This oracle exists because the first one did not. It used to be
    `re.split(r"(?<!\\)\|", row)` — "a pipe not preceded by a backslash" — which
    is `_cell`'s own escaping rule read backwards, not a renderer's. An oracle
    built from the product's rule agrees with the product by construction, and
    this one duly passed on a `_cell` that escaped the pipe without escaping the
    backslash first, i.e. on code that still shipped the injection SEC-012 is
    about. So the rule below is transcribed from the specifications instead, and
    a renderer cannot be imported to settle it: stdlib only.

    Three rules, three citations:

    1. GFM spec §4.10 (Tables, extension) — a pipe is put in cell content by
       escaping it, `\|`. The row scanner therefore consumes a backslash
       *together with the character following it*, and only an unconsumed `|`
       delimits.
    2. CommonMark §2.4 (Backslash escapes) — any ASCII punctuation character may
       be backslash-escaped, and a backslash before anything else is a literal
       backslash. So `\\` is an escaped backslash and shields nothing: combined
       with (1), a `|` delimits exactly when an EVEN number of backslashes
       precedes it. This is the clause the old oracle got wrong, and the clause
       the bypass rode in on.
    3. GFM spec §4.10 again — a row wider than the header has its excess cells
       ignored, and a narrower one is padded with empty cells. `columns` is that
       header width, and it is why smuggling one extra delimiter into the Title
       cell does not merely shift the File column, it deletes it.

    Cross-checked 2026-08-23 against a real GFM renderer (`marked`) on fifteen
    rows spanning zero to four consecutive backslashes before a pipe, absent and
    present leading/trailing pipes, and short and long rows: the cell boundaries
    agreed on all fifteen. `marked` is not a dependency of this suite and is not
    imported by it — the check was run once, by hand, to validate the
    transcription above.
    """
    row = row.strip()
    cuts, i = [], 0
    while i < len(row):
        if row[i] == "\\":
            i += 2                      # rule 1: the backslash takes the next char with it
        elif row[i] == "|":
            cuts.append(i); i += 1
        else:
            i += 1
    pieces, prev = [], 0
    for cut in cuts:
        pieces.append(row[prev:cut]); prev = cut + 1
    pieces.append(row[prev:])
    if cuts and cuts[0] == 0:           # the optional leading delimiter
        pieces.pop(0)
    if cuts and cuts[-1] == len(row) - 1:   # the optional trailing delimiter
        pieces.pop()
    cells = [_gfm_unescape(p.strip()) for p in pieces]
    return (cells + [""] * columns)[:columns]   # rule 3: pad short, ignore excess


def _gfm_unescape(text):
    r"""CommonMark §2.4 applied to one cell: `\` + ASCII punctuation is that
    punctuation; `\` before anything else stays a literal backslash."""
    out, i = [], 0
    while i < len(text):
        if text[i] == "\\" and i + 1 < len(text) and text[i + 1] in _ASCII_PUNCTUATION:
            out.append(text[i + 1]); i += 2
        else:
            out.append(text[i]); i += 1
    return "".join(out)


SPEC = """---
id: SPEC-001
title: Fixture
category: features
status: implemented
certainty: 60
behaviors:
  - behavior_id: BEH-001
    title: Proposed one
    state: proposed
  - behavior_id: BEH-002
    title: Confirmed one
    state: confirmed
    entry: app/x.ts
  - behavior_id: BEH-003
    title: Accepted one
    state: accepted
    adapter: vitest
    locator: x.test.ts::t
---
# body
"""


class CensusTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.specs = os.path.join(self.tmp.name, "auth")
        os.makedirs(self.specs)
        with open(os.path.join(self.specs, "s.md"), "w") as f:
            f.write(SPEC)

    def test_counts_by_state(self):
        counts, intent, owed = collect_status.behavior_census(self.tmp.name)
        self.assertEqual(counts["proposed"], 1)
        self.assertEqual(counts["confirmed"], 1)
        self.assertEqual(counts["accepted"], 1)

    def test_intent_worklist_is_proposed_with_certainty(self):
        _c, intent, _o = collect_status.behavior_census(self.tmp.name)
        self.assertEqual([r["behavior_id"] for r in intent], ["BEH-001"])
        self.assertEqual(intent[0]["certainty"], 60)  # inherited from parent spec

    def test_test_owed_worklist_is_confirmed(self):
        _c, _i, owed = collect_status.behavior_census(self.tmp.name)
        self.assertEqual([r["behavior_id"] for r in owed], ["BEH-002"])

    def test_missing_specs_dir_is_empty(self):
        counts, intent, owed = collect_status.behavior_census("/no/such/dir")
        self.assertEqual(sum(counts.values()), 0)
        self.assertEqual(intent, [])

    def test_an_unreadable_spec_does_not_stop_the_walk(self):
        """One spec carrying a stray byte once raised UnicodeDecodeError out of the
        whole census: it is not an OSError, so the handler meant to skip the file did
        not catch it (collect_status.py:59) and the report came back empty. Both
        flavours of unreadable are planted here beside a good spec, so narrowing that
        handler back down to either one goes red rather than merely quiet."""
        with open(os.path.join(self.specs, "aa-malformed.md"), "w") as f:
            f.write("---\nid: SPEC-002\n\ttitle: tab indented\n---\n# body\n")
        with open(os.path.join(self.specs, "ab-undecodable.md"), "wb") as f:
            f.write(b"---\nid: SPEC-003\ntitle: stray \xff byte\nbehaviors:\n"
                    b"  - behavior_id: BEH-999\n    state: proposed\n---\n# body\n")
        counts, intent, owed = collect_status.behavior_census(self.tmp.name)
        self.assertEqual([r["behavior_id"] for r in intent], ["BEH-001"])
        self.assertEqual([r["behavior_id"] for r in owed], ["BEH-002"])
        self.assertEqual(counts["proposed"], 1)   # BEH-999 was never readable
        self.assertEqual(counts["accepted"], 1)


class SecurityBucketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.d = os.path.join(self.tmp.name, "knowledge-base", "security", "codebase-security")
        os.makedirs(self.d)

    def _write(self, obj):
        with open(os.path.join(self.d, "findings.json"), "w") as f:
            json.dump(obj, f)

    def test_a_findings_file_that_is_not_utf8_is_noted_not_raised(self):
        """One stray byte used to take the whole census down with a traceback.

        `json.JSONDecodeError` is a `ValueError`, so `except (json.JSONDecodeError,
        OSError)` reads as though it covers every way a read can fail — and does not
        cover the `UnicodeDecodeError` that `open(..., encoding="utf-8")` raises
        first, before any parsing happens. SEC-008 was this same mistake pointing the
        other way: `except OSError` over a decode, which turned a swallowed error into
        an uncaught traceback.

        This bucket's whole contract is that it never answers zero without saying why,
        and a traceback is not a note.
        """
        with open(os.path.join(self.d, "findings.json"), "wb") as f:
            f.write(b'{"findings": [{"id": "SEC-\xff", "status": "open"}]}')
        findings, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual(findings, [])
        self.assertIn("unreadable", note)

    def test_open_findings_only(self):
        self._write({"version": 1, "findings": [
            {"id": "SEC-001", "title": "a", "severity": "high", "status": "open", "file": "x.ts"},
            {"id": "SEC-002", "title": "b", "severity": "low", "status": "resolved", "file": "y.ts"},
            {"id": "SEC-003", "title": "c", "severity": "medium", "status": "intentional", "file": "z.ts"},
        ]})
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertIsNone(note)
        self.assertEqual([f["id"] for f in out], ["SEC-001"])

    def test_missing_findings_is_note(self):
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual(out, [])
        self.assertIsNotNone(note)

    def test_an_unrecognised_status_is_counted_as_open_and_named(self):
        """A status outside the schema's three values used to be dropped on the floor:
        these same three findings — `Open`, `unresolved`, and no status key at all —
        returned ([], None), which is zero findings and nothing to say about them. A
        silently-zero security bucket reads as CLEAN, not as NEVER DISPOSITIONED, and
        both ends of findings.json are hand-written (an agent composing JSON against a
        prose schema, an adopting project committing it), so a vocabulary miss is the
        expected failure. The direction to fail in is the alarm: counted as open, and
        each one named so a reader can see it is a producer/consumer disagreement
        rather than a suppressed finding (ADR-005, SPEC-027)."""
        self._write({"version": 1, "findings": [
            {"id": "SEC-001", "title": "a", "severity": "high", "status": "Open", "file": "a.ts"},
            {"id": "SEC-002", "title": "b", "severity": "high", "status": "unresolved", "file": "b.ts"},
            {"id": "SEC-003", "title": "c", "severity": "high", "file": "c.ts"},
        ]})
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual([f["id"] for f in out], ["SEC-001", "SEC-002", "SEC-003"])
        self.assertIsNotNone(note)
        self.assertIn("SEC-001: 'Open'", note)
        self.assertIn("SEC-002: 'unresolved'", note)
        self.assertIn("SEC-003: missing", note)
        self.assertIn("counted as open", note)

    def test_a_findings_key_that_is_not_a_list_is_a_note(self):
        """`data.get("findings", [])` gave the same empty bucket to a file whose shape
        it could not read as to a scan that genuinely found nothing. A bare top-level
        array is the likely hand-written mistake, and it produced silence."""
        self._write([{"id": "SEC-001", "status": "open"}])
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual(out, [])
        self.assertIsNotNone(note)
        self._write({"version": 1, "findings": "SEC-001"})
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual(out, [])
        self.assertIsNotNone(note)
        # …and the control: an empty list is a real clean answer, not a degradation.
        self._write({"version": 1, "findings": []})
        self.assertEqual(collect_status.security_bucket(self.tmp.name), ([], None))

    def test_a_finding_this_report_cannot_read_is_named_rather_than_dropped(self):
        """Two shapes JSON permits and the schema does not. A list-valued `status`
        tested against a frozenset raises TypeError out of the whole census — the one
        thing every bucket here promises never to do (SPEC-028) — and an entry that is
        not an object cannot become a row, so the note is the only place it can be
        reported at all."""
        self._write({"version": 1, "findings": [
            {"id": "SEC-001", "title": "a", "severity": "high", "status": ["open"], "file": "a.ts"},
            "SEC-002 was written as a string",
        ]})
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual([f["id"] for f in out], ["SEC-001"])
        self.assertIn("SEC-001: ['open']", note)
        self.assertIn("entry 1: not an object", note)

    def test_the_note_names_a_bounded_sample_and_the_whole_count(self):
        """The note reaches the git-tracked BACKLOG.md, so it is capped the way the
        gap sample is (SPEC-029): the count is whole, the list is not. Fourteen bad
        rows must not put fourteen ids on one line of a committed file."""
        self._write({"version": 1, "findings": [
            {"id": "SEC-%03d" % i, "status": "Open"} for i in range(14)]})
        out, note = collect_status.security_bucket(self.tmp.name)
        self.assertEqual(len(out), 14)
        self.assertIn("14 finding(s)", note)
        self.assertIn("and 4 more", note)
        self.assertIn("SEC-009", note)
        self.assertNotIn("SEC-010", note)


class StaleBucketTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gdir = os.path.join(self.tmp.name, "knowledge-base", ".graph")
        os.makedirs(self.gdir)

    def _write(self, behaviors):
        with open(os.path.join(self.gdir, "behavior.json"), "w") as f:
            json.dump({"version": 1, "behaviors": behaviors}, f)

    def test_stale_when_freshness_differs_from_head(self):
        self._write({"BEH-002": {"exercises": [{"path": "a.ts", "freshness": "oldcommit"}]}})
        with mock.patch.object(collect_status, "_git_head", return_value="newcommit"):
            stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, ["BEH-002"])

    def test_fresh_when_matches_head(self):
        self._write({"BEH-002": {"exercises": [{"path": "a.ts", "freshness": "head1"}]}})
        with mock.patch.object(collect_status, "_git_head", return_value="head1"):
            stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, [])

    def test_missing_behavior_json_is_note(self):
        import shutil
        shutil.rmtree(self.gdir)
        stale, note = collect_status.stale_bucket(self.tmp.name)
        self.assertEqual(stale, [])
        self.assertIsNotNone(note)


class CollectAndRenderTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        os.makedirs(os.path.join(self.tmp.name, "knowledge-base", "specs", "auth"))
        with open(os.path.join(self.tmp.name, "knowledge-base", "specs", "auth", "s.md"), "w") as f:
            f.write(SPEC)

    def _collect(self):
        # mock the subprocess-backed buckets to keep this hermetic
        with mock.patch.object(collect_status, "gaps_bucket",
                               return_value=({"total": 2, "sample": ["a.ts", "b.ts"]}, None)), \
             mock.patch.object(collect_status, "verify_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "stale_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "security_bucket",
                               return_value=([{"id": "SEC-001", "title": "a", "severity": "high", "file": "x.ts"}], None)):
            return collect_status.collect(self.tmp.name)

    def test_collect_assembles_all_buckets(self):
        s = self._collect()
        self.assertEqual(s["behavior_counts"]["proposed"], 1)
        self.assertEqual(len(s["intent_worklist"]), 1)
        self.assertEqual(len(s["test_owed_worklist"]), 1)
        self.assertEqual(s["gaps"]["total"], 2)
        self.assertEqual(len(s["open_security_findings"]), 1)

    def test_render_backlog_has_sections_and_generated_header(self):
        md = collect_status.render_backlog(self._collect())
        self.assertIn("do not edit", md.lower())
        self.assertIn("Behaviors to confirm", md)
        self.assertIn("Tests owed", md)
        self.assertIn("Coverage gaps", md)
        self.assertIn("Open security findings", md)
        self.assertIn("BEH-001", md)   # the proposed behavior listed

    def test_write_backlog_writes_file(self):
        s = self._collect()
        path = collect_status.write_backlog(self.tmp.name, s)
        self.assertTrue(path.endswith(os.path.join("knowledge-base", "BACKLOG.md")))
        self.assertTrue(os.path.exists(path))

    def test_a_refresh_replaces_hand_written_content(self):
        """`write_backlog` opens the path "w" (collect_status.py:332) — the only
        full-overwrite path in the tree, and it came within a rename of destroying
        ~600 lines of hand-written backlog on this repo. Nothing is merged, nothing
        is set aside and nothing is said about it. That destruction is the specified
        behaviour, and this pins it so nobody softens it into a silent merge later."""
        path = os.path.join(self.tmp.name, "knowledge-base", "BACKLOG.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write("# Backlog\n\n- MINE-1: an item a human typed and no generator knows\n")
        status = self._collect()
        returned = collect_status.write_backlog(self.tmp.name, status)
        self.assertEqual(returned, path)
        # encoding, explicitly: `write_backlog` writes UTF-8 and the rendered header carries
        # an em dash, but a bare `open()` decodes with the locale codepage — cp1252 on the
        # Windows runners — and the comparison failed on a mojibake byte, not on content.
        with open(path, encoding="utf-8") as f:
            after = f.read()
        self.assertNotIn("MINE-1", after)
        self.assertEqual(after, collect_status.render_backlog(status))
        # …and nothing was preserved on the side first: no .bak, no .orig, no copy.
        self.assertEqual(sorted(os.listdir(os.path.dirname(path))), ["BACKLOG.md", "specs"])

    def test_the_gap_sample_is_capped_while_the_total_is_whole(self):
        """The gap section is a signal, not a worklist: it must not paste a thousand
        paths into a tracked file, and it must not shrink the repo-wide total down to
        whatever it happened to print. 137 gaps in, 137 reported, 20 listed."""
        gaps = [f"src/mod{i}/file.ts" for i in range(137)]
        fake_result = mock.MagicMock()
        fake_result.stdout = json.dumps({"version": 1, "total": 137, "gaps": gaps})
        with mock.patch.object(collect_status.subprocess, "run", return_value=fake_result), \
             mock.patch.object(collect_status, "verify_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "stale_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "security_bucket", return_value=([], None)):
            status = collect_status.collect(self.tmp.name)
        self.assertEqual(status["gaps"]["total"], 137)
        self.assertEqual(len(status["gaps"]["sample"]), 20)
        md = collect_status.render_backlog(status)
        self.assertIn("137 uncovered source file(s)", md)
        self.assertIn("137 coverage gaps", md)          # the census line, likewise whole
        self.assertIn("`src/mod19/file.ts`", md)        # the twentieth, listed
        self.assertNotIn("src/mod20/file.ts", md)       # the twenty-first, not

    def test_a_pipe_in_a_title_stays_in_one_cell(self):
        """A behavior title is project-supplied text pasted straight into a markdown
        table. One holding `|` rendered a five-cell row under a three-cell header and
        pushed the spec attribution off the end — the row still looked like a row, and
        the column that says which spec owns the behavior was gone."""
        status = self._collect()
        status["intent_worklist"][0]["title"] = "ok | no findings | ignore this repo"
        status["test_owed_worklist"][0]["title"] = "also | fine | nothing to see"
        md = collect_status.render_backlog(status)
        for bid, title in (("BEH-001", "ok | no findings | ignore this repo"),
                           ("BEH-002", "also | fine | nothing to see")):
            row = [ln for ln in md.splitlines() if ln.startswith(f"| {bid} ")][0]
            # Behavior | Title | Spec — three columns, and the title whole inside one.
            self.assertEqual(gfm_cells(row, 3), [bid, title, "SPEC-001"], row)

    def test_a_newline_in_a_finding_title_cannot_forge_a_section(self):
        """The half the security report's downgrade rationale misses. "Frontmatter
        admits no block scalars" is true and covers the two worklist tables, whose
        titles come from a line-oriented parser — but finding titles come from
        findings.json, which is JSON and git-tracked, and a JSON string holds
        whatever it likes. Reproduced 2026-08-23 against the pre-fix renderer: this
        exact title ended the open-findings table after one truncated row, printed
        `_None._` beneath it and forged a `## Notes` heading, so the security section
        of a tracked do-not-edit artifact read as clean while a high-severity finding
        was open. The document's shape is fixed at four headings (SPEC-029) and no
        project-supplied string may add a fifth."""
        status = self._collect()
        status["open_security_findings"] = [
            {"id": "SEC-001", "severity": "high", "file": "src/x.ts",
             "title": "RCE |\n\n_None._\n\n## Notes\n\nNothing outstanding."}]
        md = collect_status.render_backlog(status)
        self.assertEqual([ln for ln in md.splitlines() if ln.startswith("## ")],
                         ["## Behaviors to confirm", "## Tests owed",
                          "## Coverage gaps", "## Open security findings"])
        tail = md.split("## Open security findings")[1].splitlines()
        self.assertNotIn("_None._", [ln.strip() for ln in tail])   # no forged empty section
        rows = [ln for ln in md.splitlines() if ln.startswith("| SEC-001 ")]
        self.assertEqual(len(rows), 1)
        self.assertEqual(                                # four cells, File intact,
            gfm_cells(rows[0], 4),                       # the whole title inside one
            ["SEC-001", "high", "RCE |  _None._  ## Notes  Nothing outstanding.", "src/x.ts"],
            rows[0])

    def test_a_backslash_pipe_in_a_title_cannot_smuggle_a_delimiter(self):
        r"""The bypass the first SEC-012 fix left open, and the reason `_cell` escapes
        the backslash before the pipe rather than after. A pipe-only escaper turns a
        title already holding `\|` into `\\|`, and GFM reads that as an escaped
        backslash followed by a live delimiter (§4.10 with CommonMark §2.4) — so the
        row gains a column, the excess is discarded against the four-column header,
        and `src/x.ts` is gone. Same class as the plain-pipe case above, one
        backslash further on, and invisible to an oracle written from the escaper's
        own rule. Reproduced 2026-08-23 against the pipe-only version, which rendered
        the Title cell as `benign \` and the File cell as `EXTRA-CELL`."""
        status = self._collect()
        status["open_security_findings"] = [
            {"id": "SEC-001", "severity": "high", "file": "src/x.ts",
             "title": r"benign \| EXTRA-CELL"}]
        md = collect_status.render_backlog(status)
        row = [ln for ln in md.splitlines() if ln.startswith("| SEC-001 ")][0]
        self.assertEqual(gfm_cells(row, 4),
                         ["SEC-001", "high", r"benign \| EXTRA-CELL", "src/x.ts"], row)
        # …and every deeper run of backslashes, since only the parity matters.
        for title in (r"a \\| b", r"a \\\| b", r"a \\\\| b", "trailing backslash \\"):
            status["open_security_findings"][0]["title"] = title
            row = [ln for ln in collect_status.render_backlog(status).splitlines()
                   if ln.startswith("| SEC-001 ")][0]
            self.assertEqual(gfm_cells(row, 4),
                             ["SEC-001", "high", title, "src/x.ts"], row)

    def test_the_sec_012_forgery_does_not_render_however_it_is_armoured(self):
        r"""The acceptance test for SEC-012, as opposed to a unit test of the escaper.
        The finding is not "a pipe leaks a cell", it is "a findings.json title can make
        the security section of a tracked do-not-edit artifact read as clean". So mount
        the original forgery — the title that forged a `## Notes` heading and printed
        `_None._` under a section holding an open high — and mount it again with the
        pipe backslash-armoured, which is the form that walked through the first fix.
        Neither may add a fifth heading, print a false `_None._`, or lose the File
        column, and the whole payload must stay inside its own cell where a reader can
        see it. SPEC-029 fixes the document at four headings; nothing project-supplied
        adds one."""
        forgery = "RCE |\n\n_None._\n\n## Notes\n\nNothing outstanding."
        armoured = "RCE \\|\n\n_None._\n\n## Notes\n\nNothing outstanding."
        for title in (forgery, armoured):
            status = self._collect()
            status["open_security_findings"] = [
                {"id": "SEC-001", "severity": "high", "file": "src/x.ts", "title": title}]
            md = collect_status.render_backlog(status)
            self.assertEqual([ln for ln in md.splitlines() if ln.startswith("## ")],
                             ["## Behaviors to confirm", "## Tests owed",
                              "## Coverage gaps", "## Open security findings"], title)
            tail = md.split("## Open security findings")[1]
            self.assertNotIn("_None._", [ln.strip() for ln in tail.splitlines()], title)
            rows = [ln for ln in md.splitlines() if ln.startswith("| SEC-001 ")]
            self.assertEqual(len(rows), 1, title)
            cells = gfm_cells(rows[0], 4)
            self.assertEqual(cells[3], "src/x.ts", rows[0])   # the File column survives
            # the payload, newlines collapsed, whole and inside the Title cell
            self.assertEqual(cells[2], title.replace("\n", " "), rows[0])

    def test_a_newline_in_a_gap_path_stays_on_one_line(self):
        """The gap sample is the other project-supplied text in this document, and a
        path is not frontmatter — POSIX permits a newline in a filename — so the same
        forged heading is reachable through a list item rather than a table row. The
        escaping is deliberately weaker here than in a cell: only the newline is
        collapsed, because a `|` is ordinary text outside a table and a path the reader
        is meant to select and copy should not be rewritten further than the rendering
        requires."""
        status = self._collect()
        status["gaps"] = {"total": 1,
                          "sample": ["src/x.ts\n\n## Notes\n\nNothing outstanding."]}
        md = collect_status.render_backlog(status)
        self.assertEqual([ln for ln in md.splitlines() if ln.startswith("## ")],
                         ["## Behaviors to confirm", "## Tests owed",
                          "## Coverage gaps", "## Open security findings"])
        entries = [ln for ln in md.splitlines() if ln.startswith("- `")]
        self.assertEqual(len(entries), 1)
        self.assertTrue(entries[0].endswith("`"))
        # …and the pipe is left alone, which is what makes this not a table cell.
        status["gaps"] = {"total": 1, "sample": ["src/a|b.ts"]}
        self.assertIn("- `src/a|b.ts`", collect_status.render_backlog(status))

    def test_the_backlog_carries_the_census_notes(self):
        """SPEC-028 makes the note the thing that separates "0 open findings" from
        "no scan has ever run" — the same number and opposite facts — and says it "is
        why each source returns (value, note)". This renderer read the value and never
        `status["notes"]`, so the one rendering that is committed and read in a PR diff
        was the only place the caveat was lost: a project with no findings.json wrote
        "0 open findings" and `_None._` under Open security findings, with nothing
        anywhere in the file saying the source was missing. That is ADR-005's
        confidently-empty answer, in a tracked artifact."""
        with mock.patch.object(collect_status, "gaps_bucket",
                               return_value=({"total": 0, "sample": []},
                                             "could not compute gaps (behavior-graph --gaps)")), \
             mock.patch.object(collect_status, "verify_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "stale_bucket", return_value=([], None)), \
             mock.patch.object(collect_status, "security_bucket",
                               return_value=([], "no findings.json — run codebase-security-scan")):
            degraded = collect_status.collect(self.tmp.name)
        md = collect_status.render_backlog(degraded)
        self.assertIn("no findings.json — run codebase-security-scan", md)
        self.assertIn("could not compute gaps", md)
        # above the sections it qualifies, not stranded under them
        self.assertLess(md.index("no findings.json"), md.index("## Open security findings"))
        # …and the control: a run that read everything manufactures no caveat.
        self.assertNotIn("could not read every source",
                         collect_status.render_backlog(self._collect()))


class VerifyBucketTest(unittest.TestCase):
    """Prove that verify_bucket preserves the errors list even on non-zero exit."""

    def test_returns_errors_even_when_subprocess_exits_nonzero(self):
        """Critical: verify_links exits non-zero on findings; errors must not be lost."""
        stdout = '[{"kind": "missing-locator", "spec_id": "SPEC-001", "behavior_id": "BEH-001", "message": "x"}]'
        fake_result = mock.MagicMock()
        fake_result.returncode = 1
        fake_result.stdout = stdout
        with mock.patch.object(collect_status.subprocess, "run", return_value=fake_result):
            errors, note = collect_status.verify_bucket("/any/project/dir")
        self.assertIsNone(note)
        self.assertEqual(len(errors), 1)
        self.assertEqual(errors[0]["kind"], "missing-locator")

    def test_empty_stdout_is_clean(self):
        """Zero exit + empty stdout returns ([], None) — no spurious note."""
        fake_result = mock.MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = ""
        with mock.patch.object(collect_status.subprocess, "run", return_value=fake_result):
            errors, note = collect_status.verify_bucket("/any/project/dir")
        self.assertEqual(errors, [])
        self.assertIsNone(note)

    def test_bad_json_degrades_to_note(self):
        """Malformed stdout should not crash — degrade to ([], <note>)."""
        fake_result = mock.MagicMock()
        fake_result.stdout = "not json"
        with mock.patch.object(collect_status.subprocess, "run", return_value=fake_result):
            errors, note = collect_status.verify_bucket("/any/project/dir")
        self.assertEqual(errors, [])
        self.assertIsNotNone(note)


class MainTest(unittest.TestCase):
    """Drives the script as a process, which is the only way to see its real exit code."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        specs = os.path.join(self.tmp.name, "knowledge-base", "specs", "auth")
        os.makedirs(specs)
        with open(os.path.join(specs, "s.md"), "w") as f:
            f.write(SPEC)
        sec = os.path.join(self.tmp.name, "knowledge-base", "security", "codebase-security")
        os.makedirs(sec)
        with open(os.path.join(sec, "findings.json"), "w") as f:
            json.dump({"version": 1, "findings": [
                {"id": "SEC-001", "title": "a", "severity": "high",
                 "status": "open", "file": "x.ts"}]}, f)

    def test_status_exits_zero_with_work_outstanding(self):
        """status is the read-only check-counterpart of wrap-up: it reports, it never
        blocks, so its exit code carries no verdict about what it found. A non-zero
        exit here would make every caller that chains on `&&` — and CI — treat an
        ordinary backlog as a failure. The fixture carries outstanding work in three
        worklists at once, so a zero exit over an empty report cannot pass for this."""
        proc = subprocess.run(
            [sys.executable, SCRIPT, "--project", self.tmp.name, "--format", "json"],
            capture_output=True, text=True)
        report = json.loads(proc.stdout)
        self.assertEqual([r["behavior_id"] for r in report["intent_worklist"]], ["BEH-001"])
        self.assertEqual([r["behavior_id"] for r in report["test_owed_worklist"]], ["BEH-002"])
        self.assertEqual([f["id"] for f in report["open_security_findings"]], ["SEC-001"])
        self.assertEqual(proc.returncode, 0, proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
