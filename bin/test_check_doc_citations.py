#!/usr/bin/env python3
"""Unit tests for the prose-to-code citation gate.

Every fixture is a real git repository under tempfile.mkdtemp(), because the
checker's idea of "in the tree" is `git ls-files` and a fixture that faked that
would be testing a mock.

Run:  python -m pytest bin/test_check_doc_citations.py -q
"""

import contextlib
import io
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import check_doc_citations as cdc


def build_repo(tmp, files, untracked=None):
    """Materialize a git-tracked tree and return its root.

    `files` maps a repo-relative path to its content and is committed to the
    index; `untracked` is written afterwards and stays out of it.

    `git add -f`, forced on purpose: the machine running the suite may have a
    global core.excludesFile, and a fixture silently missing from the index
    would empty the scan and turn every assertion below green for the wrong
    reason.
    """
    root = Path(tmp)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=str(root), check=True, capture_output=True)
    subprocess.run(["git", "add", "-f", "-A"], cwd=str(root), check=True, capture_output=True)
    for rel, content in (untracked or {}).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    return root


def run_main(argv):
    """Call main() with its output captured, so the suite stays quiet.

    Returns (exit_code, stdout, stderr) — the captured streams let the tests
    assert on what the tool actually reports, not just how it exits.
    """
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        code = cdc.main(argv)
    return code, out.getvalue(), err.getvalue()


class RepoFixture(unittest.TestCase):
    """Base for the tests that need a tree on disk."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="freya-citations-")
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def report(self, files, untracked=None, **kwargs):
        return cdc.scan(build_repo(self.tmp, files, untracked), **kwargs)

    def rules(self, files, untracked=None):
        return [v[2] for v in self.report(files, untracked).violations]


class ExtractionTest(unittest.TestCase):
    def test_a_path_with_a_line_number_is_a_citation(self):
        self.assertEqual(list(cdc.citations(["as `lib/app.py:12` shows"])),
                         [(1, "lib/app.py", 12)])

    def test_a_bare_filename_with_a_line_number_is_a_citation(self):
        """The dominant shape in this repo: the ADRs write the full path once and
        the basename for every citation after it — 514 of the 1,053 tracked
        citations are bare, so an extractor that required a directory would miss
        the larger half of the corpus."""
        self.assertEqual(list(cdc.citations(["and again (`app.py:57`)"])),
                         [(1, "app.py", 57)])

    def test_two_citations_on_one_line_are_both_found(self):
        self.assertEqual(list(cdc.citations(["`a.py:1` and `b.py:2`"])),
                         [(1, "a.py", 1), (1, "b.py", 2)])

    def test_the_reported_line_is_where_the_citation_was_written(self):
        self.assertEqual(list(cdc.citations(["prose", "", "see `app.py:9`"])),
                         [(3, "app.py", 9)])

    def test_a_word_with_a_colon_and_a_number_is_not_a_citation(self):
        """`TRIGGER when: 5` and `ADR-009:2` have the punctuation but no file
        extension. Without the extension requirement the gate would spend its
        credibility on prose."""
        self.assertEqual(list(cdc.citations(["step:4 of ADR-009:2"])), [])

    def test_a_path_inside_a_url_is_not_a_citation(self):
        """The lookbehind: `https://example.com/lib/app.py:12` is a link, and
        matching its tail would report a file this repo does not own."""
        self.assertEqual(list(cdc.citations(["https://example.com/lib/app.py:12"])), [])

    def test_a_number_running_into_a_word_is_not_a_citation(self):
        self.assertEqual(list(cdc.citations(["app.py:12x"])), [])

    def test_a_dotfile_directory_does_not_break_the_path(self):
        """`.github/workflows/ci.yml:82` is cited from TESTING.md; the leading dot
        must be part of the path, not a boundary that truncates it."""
        self.assertEqual(list(cdc.citations(["(`.github/workflows/ci.yml:82`)"])),
                         [(1, ".github/workflows/ci.yml", 82)])


class ResolutionTest(RepoFixture):
    def test_a_bare_filename_resolves_to_the_one_tracked_file_with_that_name(self):
        self.assertEqual(
            self.rules({"notes/a.md": "see `app.py:2`\n", "lib/pkg/app.py": "x\n\n"}),
            ["C3"],
        )

    def test_a_partial_path_resolves_by_suffix(self):
        """`freya-wrap-up/SKILL.md:471` and `references/templates.md:1134` are
        written relative to skills/, and nine real citations use that shape."""
        self.assertEqual(
            self.rules({"notes/a.md": "see `pkg/app.py:2`\n", "lib/pkg/app.py": "x\n\n"}),
            ["C3"],
        )

    def test_an_exact_path_beats_a_longer_file_ending_the_same_way(self):
        """`app.py` and `lib/app.py` both end in `app.py`, so without exact-path
        precedence the citation would be ambiguous and go unchecked. The count is
        asserted, not just the silence: an unchecked citation also produces no
        violation."""
        report = self.report({
            "notes/a.md": "see `app.py:2`\n",
            "app.py": "one\ntwo\n",
            "lib/app.py": "x\n\n",
        })
        self.assertEqual([v[2] for v in report.violations], [])
        self.assertEqual(report.checked, 1)

    def test_a_basename_two_files_share_is_left_alone(self):
        """19 citations name a bare `SKILL.md`, which ten tracked files match.
        Guessing one of them would invent findings."""
        files = {
            "notes/a.md": "see `SKILL.md:2`\n",
            "one/SKILL.md": "x\n\n",
            "two/SKILL.md": "x\n\n",
        }
        report = self.report(files)
        self.assertEqual([v[2] for v in report.violations], [])
        self.assertEqual(report.unresolved, 1)

    def test_a_bare_name_no_tracked_file_matches_is_not_an_error(self):
        """ADR-023 cites `affected.py:12` and `resolution.py:671` inside the
        third-party graphify package, and eleven more bare names belong to the
        deleted design documents. A bare name is not a claim about this tree, so
        an unresolvable one is counted, not reported."""
        report = self.report({"notes/a.md": "graphify's `affected.py:12`\n"})
        self.assertEqual([v[2] for v in report.violations], [])
        self.assertEqual(report.unresolved, 1)

    def test_a_citation_into_an_untracked_file_does_not_resolve(self):
        """Resolution reads the index, not the filesystem: a generated artifact
        that git ignores is not something a document may cite as provenance."""
        self.assertEqual(
            self.rules({"notes/a.md": "see `out/report.py:1`\n"},
                       untracked={"out/report.py": "x\n"}),
            ["C1"],
        )


class RuleTest(RepoFixture):
    def test_a_citation_into_a_missing_path_is_an_error(self):
        self.assertEqual(self.rules({"notes/a.md": "see `lib/gone.py:3`\n"}), ["C1"])

    def test_a_line_past_the_end_of_the_file_is_an_error(self):
        self.assertEqual(
            self.rules({"notes/a.md": "see `lib/app.py:9`\n", "lib/app.py": "one\ntwo\n"}),
            ["C2"],
        )

    def test_line_zero_is_an_error(self):
        self.assertEqual(
            self.rules({"notes/a.md": "see `lib/app.py:0`\n", "lib/app.py": "one\n"}),
            ["C2"],
        )

    def test_the_last_line_of_a_file_is_in_range(self):
        """Off-by-one guard: a file of two lines is cited at :2 all over the
        knowledge base, and a gate that called that out of range would be
        deleted within the hour."""
        self.assertEqual(
            self.rules({"notes/a.md": "see `lib/app.py:2`\n", "lib/app.py": "one\ntwo\n"}),
            [],
        )

    def test_a_citation_landing_on_a_blank_line_is_an_error(self):
        """The high-signal case, and the reason this gate exists: 21 citations in
        the tracked markdown landed on whitespace at 296deda. Nobody cites a
        blank line on purpose, so every one of them is drift."""
        self.assertEqual(
            self.rules({"notes/a.md": "see `lib/app.py:2`\n", "lib/app.py": "one\n\nthree\n"}),
            ["C3"],
        )

    def test_a_line_of_only_whitespace_counts_as_blank(self):
        """An "empty" line in this repo's Python is often indentation left behind
        by an editor, and it is no more citable than a truly empty one."""
        self.assertEqual(
            self.rules({"notes/a.md": "see `lib/app.py:2`\n",
                        "lib/app.py": "one\n    \nthree\n"}),
            ["C3"],
        )

    def test_a_citation_landing_on_a_comment_line_is_not_an_error(self):
        """80 citations land on a `#` line and nearly all are correct: the
        constants in substrate.py are documented in `#:` blocks and an ADR citing
        the reasoning cites the comment. Flagging them would bury the 21 real
        ones."""
        self.assertEqual(
            self.rules({"notes/a.md": "see `lib/app.py:2`\n",
                        "lib/app.py": "one\n# why this constant is 6\nthree\n"}),
            [],
        )

    def test_a_citation_into_a_markdown_file_is_checked_too(self):
        """SPEC-029 cites `knowledge-base/roadmap.md:15`. Docs cite docs, and
        those line numbers rot the same way."""
        self.assertEqual(
            self.rules({"notes/a.md": "see `notes/b.md:2`\n", "notes/b.md": "one\n\nthree\n"}),
            ["C3"],
        )

    def test_the_violation_names_the_citation_and_the_file_it_resolved_to(self):
        """A bare `app.py:2` is unactionable on its own — the reader has to be
        told which of the tracked files it was checked against."""
        excerpt = self.report({"notes/a.md": "see `app.py:2`\n",
                               "lib/app.py": "one\n\n"}).violations[0][3]
        self.assertIn("app.py:2", excerpt)
        self.assertIn("lib/app.py", excerpt)

    def test_the_violation_names_the_citing_document_and_line(self):
        rel, lineno, _, _ = self.report(
            {"notes/a.md": "prose\nprose\nsee `lib/app.py:9`\n", "lib/app.py": "one\n"}
        ).violations[0]
        self.assertEqual((rel, lineno), ("notes/a.md", 3))


class ExemptionTest(RepoFixture):
    def test_a_citation_into_a_deleted_design_tree_is_exempt(self):
        """knowledge-base/decisions/README.md says these resolve against git
        history by design — `git show 04a9b8b:<path>` — and keeps the line
        numbers deliberately. 58 citations are in this class; flagging them
        would make the gate unkeepable."""
        for prefix in ("docs/design/", "docs/polyglot/", "docs/superpowers/"):
            with self.subTest(prefix=prefix):
                report = self.report({"notes/a.md": f"see `{prefix}01-design.md:216`\n"})
                self.assertEqual([v[2] for v in report.violations], [])
                self.assertEqual(report.exempt, 1)

    def test_an_example_path_from_a_skill_illustration_is_exempt(self):
        """`src/api/users.ts:45` is sample output in the resolver's impact
        analysis and `src/auth.js:5` is a phase-7 fixture path. This repo has no
        src/ tree; the citations illustrate the format, not this codebase."""
        report = self.report({"notes/a.md": "Location: src/api/users.ts:45\n"})
        self.assertEqual([v[2] for v in report.violations], [])
        self.assertEqual(report.exempt, 1)

    def test_a_docs_path_outside_the_exempt_trees_is_still_checked(self):
        """The exemption is three named trees, not `docs/` wholesale: the docs
        that moved to knowledge-base/ on 2026-08-21 left stale `docs/…` paths
        behind, and those are drift, not history."""
        self.assertEqual(self.rules({"notes/a.md": "see `docs/architecture.md:9`\n"}), ["C1"])


class ScopeTest(RepoFixture):
    def test_an_untracked_markdown_file_is_not_scanned(self):
        """A filesystem walk picks up graphify-out/GRAPH_REPORT.md and nine
        .pytest_cache/README.md files. Nobody maintains those."""
        self.assertEqual(
            self.rules({"notes/a.md": "clean\n", "lib/app.py": "one\n\n"},
                       untracked={"out/scratch.md": "see `lib/app.py:2`\n"}),
            [],
        )

    def test_a_citation_inside_a_python_file_is_not_scanned(self):
        """The gate reads documents. A `path:line` in a source comment is that
        file's own business, and check_skill_conformance.py owns skills/**/*.py."""
        self.assertEqual(
            self.rules({"lib/cites.py": "# see lib/app.py:2\n", "lib/app.py": "one\n\n"}),
            [],
        )

    def test_the_census_counts_every_citation_it_checked(self):
        """A gate that skips most of its input and never says so is the exact
        failure this suite keeps finding in itself."""
        report = self.report({
            "notes/a.md": "`lib/app.py:1` `lib/app.py:2` `docs/design/x.md:3` `nowhere.py:4`\n",
            "lib/app.py": "one\ntwo\n",
        })
        self.assertEqual((report.checked, report.exempt, report.unresolved), (2, 1, 1))


class MainTest(RepoFixture):
    def test_a_tree_whose_citations_resolve_exits_zero(self):
        root = build_repo(self.tmp, {"notes/a.md": "see `lib/app.py:1`\n", "lib/app.py": "one\n"})
        code, out, _ = run_main(["--root", str(root)])
        self.assertEqual(code, 0)
        self.assertIn("1 doc citation(s) resolve.", out)

    def test_a_broken_citation_exits_one_and_prints_it_on_stdout(self):
        root = build_repo(self.tmp, {"notes/a.md": "see `lib/app.py:2`\n",
                                     "lib/app.py": "one\n\n"})
        code, out, err = run_main(["--root", str(root)])
        self.assertEqual(code, 1)
        self.assertIn("notes/a.md:1: C3:", out)
        self.assertIn("1 citation(s) do not resolve.", err)

    def test_the_census_is_printed_even_when_nothing_is_wrong(self):
        root = build_repo(self.tmp, {"notes/a.md": "see `docs/design/x.md:3`\n",
                                     "lib/app.py": "one\n"})
        _, _, err = run_main(["--root", str(root)])
        self.assertIn("1 exempt", err)

    def test_rule_filters_the_report_to_one_rule(self):
        files = {
            "notes/a.md": "`lib/app.py:2` and `lib/gone.py:1`\n",
            "lib/app.py": "one\n\n",
        }
        root = build_repo(self.tmp, files)
        code, out, _ = run_main(["--root", str(root), "--rule", "C1"])
        self.assertEqual(code, 1)
        self.assertIn("C1", out)
        self.assertNotIn("C3", out)

    def test_a_root_that_is_not_a_git_tree_exits_two(self):
        """Not zero. A checkout the gate cannot read the file list for has not
        been proven clean, and saying so is the whole of ADR-029."""
        code, _, err = run_main(["--root", self.tmp])
        self.assertEqual(code, 2)
        self.assertIn("check-doc-citations:", err)
        self.assertIn("git ls-files failed", err)

    def test_a_repository_with_nothing_tracked_exits_two(self):
        subprocess.run(["git", "init", "-q"], cwd=self.tmp, check=True, capture_output=True)
        code, out, err = run_main(["--root", self.tmp])
        self.assertEqual(code, 2)
        self.assertIn("no tracked files", err)
        self.assertEqual(out, "")


class ThisRepositoryTest(unittest.TestCase):
    """Run against the checkout itself — the tree the gate is for.

    The blank-line count is deliberately *not* pinned here: it is a live defect
    list owned by whoever writes the documents, and 22 citations were failing at
    296deda. What is pinned is the part that must never regress.
    """

    def test_no_document_cites_a_path_that_is_not_in_this_tree(self):
        """C1 is at zero and has to stay there: every directory-qualified
        citation in the tracked markdown names a file git is tracking, or an
        exempt tree. A rename that forgets its citations lands here."""
        report = cdc.scan(Path(__file__).resolve().parents[1], rules={"C1"})
        detail = "\n".join(f"{rel}:{line}: {rule}: {excerpt}"
                           for rel, line, rule, excerpt in report.violations)
        self.assertEqual(report.violations, [], f"dangling citations:\n{detail}")

    def test_the_scan_reads_hundreds_of_citations_from_the_real_documents(self):
        """The vacuity guard. 953 citations were checked at 296deda; if this ever
        reads a handful, the extractor or the file list broke and every other
        assertion about this repo went green on an empty scan."""
        report = cdc.scan(Path(__file__).resolve().parents[1])
        self.assertGreater(report.checked, 500)


if __name__ == "__main__":
    unittest.main()
