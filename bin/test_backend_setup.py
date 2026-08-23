#!/usr/bin/env python3
"""The install-time backend question.

Asked here because `freya install` and `freya update` are the only moments a human is
demonstrably at a keyboard. Everything else — agent-driven runs, wrap-up, CI — has no TTY,
so a prompt there would never fire; and an instruction in the skill layer would be read on
every invocation to say nothing on almost all of them.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import backend_setup  # noqa: E402

STORE = Path(__file__).resolve().parents[1]


class Base(unittest.TestCase):
    def setUp(self):
        self.home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.home, ignore_errors=True)
        self.previous = os.environ.get("FREYA_HOME")
        os.environ["FREYA_HOME"] = self.home
        self.addCleanup(self._restore)
        self.out = io.StringIO()

    def _restore(self):
        if self.previous is None:
            os.environ.pop("FREYA_HOME", None)
        else:
            os.environ["FREYA_HOME"] = self.previous

    def saved(self):
        path = Path(self.home) / "settings.json"
        return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None

    #: Injected rather than read off PATH. Written against the real registry, five of these
    #: tests passed here and failed on every CI runner, which installs nothing but pytest and
    #: therefore has exactly one backend to choose between.
    OPTIONS = ["homegrown", "graphify"]

    def offer(self, answers=("1",), interactive=True, options=None):
        """Run the question with a scripted set of answers."""
        queue = list(answers)
        return backend_setup.offer(
            STORE, stream=self.out,
            reader=lambda: queue.pop(0) if queue else "",
            interactive=interactive,
            options=self.OPTIONS if options is None else options)


class TestItAsksOnce(Base):
    def test_a_choice_is_saved_as_the_machine_default(self):
        name = self.offer(["2"])
        self.assertIsNotNone(name)
        self.assertEqual(self.saved()["substrate"]["backend"], name)

    def test_it_never_asks_again(self):
        self.offer(["1"])
        again = io.StringIO()
        self.assertIsNone(backend_setup.offer(STORE, stream=again,
                                              reader=lambda: "2", interactive=True))
        self.assertEqual(again.getvalue(), "",
                         "a machine that has answered must never be asked again")

    def test_the_options_are_numbered_and_described(self):
        """A menu, not free text. The person choosing has no reason to know the names."""
        self.offer(["1"])
        shown = self.out.getvalue()
        self.assertIn("[1]", shown)
        self.assertIn("homegrown", shown)

    def test_it_says_the_answer_can_be_overridden_per_project(self):
        self.offer(["1"])
        self.assertIn("--use", self.out.getvalue())


class TestItNeverBlocksAndNeverGuesses(Base):
    def test_a_non_interactive_install_writes_nothing(self):
        """A scripted or piped install must not block — and must not answer on the user's
        behalf either. Unanswered is a state the build handles; a recorded default nobody
        chose is not."""
        self.assertIsNone(self.offer(interactive=False))
        self.assertIsNone(self.saved())
        self.assertEqual(self.out.getvalue(), "")

    def test_pressing_enter_skips_without_saving(self):
        self.assertIsNone(self.offer([""]))
        self.assertIsNone(self.saved())
        self.assertIn("when you decide", self.out.getvalue())

    def test_nonsense_is_re_asked_and_then_given_up_on(self):
        """A prompt that will not let you leave is worse than an unanswered question."""
        self.assertIsNone(self.offer(["x", "9", "nope"]))
        self.assertIsNone(self.saved())

    def test_a_digit_that_is_not_a_number_is_re_asked_not_raised(self):
        """`"²".isdigit()` is True and `int("²")` raises, so the guard let exactly
        the input it was meant to catch through — and turned a typo into a traceback out of
        an install."""
        self.assertIsNone(self.offer(["²", "", ""]))
        self.assertIsNone(self.saved())

    def test_it_does_not_depend_on_what_is_installed_on_this_machine(self):
        """The regression that matters most here: written against the real registry, this
        suite passed locally and failed on every CI runner."""
        self.assertEqual(self.offer(["2"], options=["homegrown", "graphify"]), "graphify")

    def test_an_interrupted_prompt_is_a_skip_not_a_crash(self):
        def interrupt():
            raise KeyboardInterrupt

        self.assertIsNone(backend_setup.offer(STORE, stream=self.out, reader=interrupt,
                                              interactive=True))
        self.assertIsNone(self.saved())

    def test_offer_quietly_swallows_everything(self):
        """An install that worked must never be reported as failed because a preference
        could not be saved."""
        self.assertIsNone(backend_setup.offer_quietly("/definitely/not/a/store"))


class TestOneOptionIsNotAQuestion(Base):
    ONLY_FLOOR = ["homegrown"]

    def test_it_does_not_ask_when_there_is_nothing_to_choose(self):
        """Asking a question with one answer trains people to skip questions."""
        asked = []
        self.assertIsNone(backend_setup.offer(
            STORE, stream=self.out, reader=lambda: asked.append(1) or "1",
            interactive=True, options=self.ONLY_FLOOR))
        self.assertEqual(asked, [])
        self.assertIsNone(self.saved())

    def test_it_still_closes_the_discovery_gap(self):
        """Nothing else in the toolkit tells you another backend exists before you have
        already installed it, so this line is the whole discovery path."""
        backend_setup.offer(STORE, stream=self.out, reader=lambda: "", interactive=True,
                            options=self.ONLY_FLOOR)
        shown = self.out.getvalue()
        self.assertIn("graphify", shown)
        self.assertIn("--use graphify --global", shown)

    def test_a_scripted_install_is_silent_even_with_nothing_to_offer(self):
        """The upsell used to be written before the interactive check, so it landed in the
        log of every CI install and every `freya update`, forever — advice nobody running
        those was in a position to act on."""
        self.assertIsNone(backend_setup.offer(
            STORE, stream=self.out, reader=lambda: "", interactive=False,
            options=self.ONLY_FLOOR))
        self.assertEqual(self.out.getvalue(), "")


class TestItSharesOneDefinitionOfTheMachineHome(unittest.TestCase):
    def test_the_machine_level_home_has_one_definition(self):
        """`~/.freya` holds both the update throttle and the settings file. Two independent
        computations of that path would let `FREYA_HOME` relocate one and not the other — so
        a test run would isolate its configuration and still write into the real home.

        Compared with the variable **unset**, because that is the only state where the two
        fallbacks are exercised. With it set — which the session-wide conftest does — both
        sides trivially return the sandbox and the test proves nothing, which is what it did
        when it was first written.
        """
        sys.path.insert(0, str(STORE / "skills" / "freya-code-graph" / "scripts"))
        import settings as settings_mod
        import updater

        previous = os.environ.pop("FREYA_HOME", None)
        try:
            self.assertEqual(Path(settings_mod.global_home()).resolve(),
                             updater.state_dir().resolve())
            self.assertEqual(Path(settings_mod.global_home()).name, ".freya")
        finally:
            if previous is not None:
                os.environ["FREYA_HOME"] = previous

    def test_the_override_moves_both(self):
        sys.path.insert(0, str(STORE / "skills" / "freya-code-graph" / "scripts"))
        import settings as settings_mod
        import updater

        previous = os.environ.get("FREYA_HOME")
        scratch = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, scratch, ignore_errors=True)
        os.environ["FREYA_HOME"] = scratch
        try:
            self.assertEqual(Path(settings_mod.global_home()), Path(scratch))
            self.assertEqual(updater.state_dir(), Path(scratch))
        finally:
            if previous is None:
                os.environ.pop("FREYA_HOME", None)
            else:
                os.environ["FREYA_HOME"] = previous


class TestTheInstallInstructionIsPinnedAndUnambiguous(Base):
    """The install instruction in the prompt — the only one of the toolkit's three under a gate.

    Nothing here declares `graphifyy`. INV-1 makes the standard library the whole runtime,
    so there is no requirements.txt, pyproject or lockfile for a dependency bot to read and
    nothing to pin in the usual sense — the install is prose in a prompt, which makes the
    pin prose as well. Prose with no gate under it drifts, and this one already had: the
    unpinned command resolved to 0.9.48 within two days of the reference recording 0.9.47
    as the release actually measured here. This class is the gate the manifest would have
    been.

    **It gates one copy of the command, and the drift it exists to catch is live in another.**
    Measured 2026-08-23: `ENVIRONMENT.md` § "The optional backend binary" still prints
    `uv tool install "graphifyy[sql,terraform]"`, unpinned, directly under a sentence calling
    itself the install-time prompt's own output — the SEC-018 remediation names that file
    alongside `backend_setup.py` and only `backend_setup.py` was changed. `CHANGELOG.md`
    prints the unpinned form a third time. Nothing below reads either: a test that did would
    be red until a page outside this file's ownership is edited, so the second and third
    copies are named here rather than gated. Whoever pins them can widen `shown()`.

    The name split is the other half and it is not cosmetic. The distribution is
    `graphifyy`, two y's; the console script it installs is `graphify`, one. A `graphify`
    project exists on PyPI and is not this one, so the single-y typo installs a stranger's
    package — SEC-018 is the record, and it is the whole finding, not a hypothetical. (This
    docstring first said that project holds "zero files" and so "fails today". Nothing in the
    tree corroborates either, and an unattributed fact about a live index is the kind that is
    true until it is not; dropped rather than dated.) The prompt is the moment a
    person is about to type the name, so the prompt is where it has to be said — saying it
    only in the reference is saying it to whoever already knew.
    """

    ONLY_FLOOR = ["homegrown"]

    #: The only spec a person should ever be told to type. Extras-bearing because without them
    #: graphify still *declares* .sql, .tf and .tfvars and parses none of them; pinned because
    #: graphifyy is 0.x and the unpinned command moved to 0.9.48 two days after the reference
    #: recorded 0.9.47.
    SPEC = "graphifyy[sql,terraform]==0.9.47"

    #: Matched on the install **verb**, never on the package name. The first version of this
    #: test counted the substring `graphifyy[`, so an extras-free line — `pip install
    #: graphifyy` — was not an install as far as the count was concerned and slipped through
    #: green carrying neither extras nor pin: measured, the pip and uv spellings both passed.
    #: The `spec` group takes one shell token, quoted or bare, after any flags.
    INSTALL = (r"\b(?:uv\s+tool\s+|uv\s+pip\s+|pipx\s+|python3?\s+-m\s+pip\s+|pip3?\s+)"
               r"install\s+(?:-\S+\s+)*(?P<spec>\"[^\"]*\"|'[^']*'|\S+)")

    def shown(self):
        """The upsell as a person on the floor actually sees it."""
        backend_setup.offer(STORE, stream=self.out, reader=lambda: "", interactive=True,
                            options=self.ONLY_FLOOR)
        return self.out.getvalue()

    def installs(self, shown):
        """Every install command `INSTALL` can see, as the spec each one would install.

        Enumerated rather than searched for, because the failure to expect is not somebody
        deleting the pin — it is a second install line added beside it, and any `assertIn` or
        name-keyed count sails straight past that.
        """
        # Imported here, not at the top: `bin/test_backend_setup.py:26` and `:161` are cited
        # by line from TESTING.md and ENVIRONMENT.md, and a line added to the import block
        # moves both without breaking either loudly enough for a gate to notice.
        import re

        return [m.group("spec").strip("\"'") for m in re.finditer(self.INSTALL, shown)]

    def test_every_install_it_prints_names_an_exact_version(self):
        """Every install `INSTALL` can see — an unpinned or extras-free second line fails here
        spelled `pip`, `pip3`, `pipx`, `python -m pip`, `uv pip` or `uv tool`, quoted or bare,
        with or without flags. Not "however spelled", which is what this said first: measured
        2026-08-23, `uv add`, `poetry add`, `conda install` and `easy_install graphifyy` all
        pass green — manifest verbs and other packagers, none of which belongs in a prompt for
        a standalone tool. But "however spelled" is what sent me to measure, so the sentence
        now says what the regex does."""
        specs = self.installs(self.shown())
        self.assertTrue(specs, "the prompt no longer prints an install command at all")
        for spec in specs:
            self.assertEqual(spec, self.SPEC,
                             "the prompt prints an install that is not the pinned one")

    def test_it_says_which_spelling_is_the_package_and_which_is_the_command(self):
        shown = self.shown()
        self.assertIn("two y's", shown,
                      "the prompt must name the package spelling at the point of install")
        self.assertIn("one y", shown,
                      "the prompt must name the command spelling at the point of install")
        self.assertIn("--use graphify --global", shown)

    def test_it_warns_that_pip_needs_a_newer_python_than_this_toolkit_does(self):
        """Every graphifyy release, 0.9.47 included, declares `Requires-Python >=3.10`.
        The prompt offers pip as the alternative to `uv tool install`, and uv provisions its
        own interpreter while pip uses the one you are standing on — so on the floor this
        project supports, and the floor CI runs a leg of, the alternative simply fails.

        `MIN_PYTHON` is read rather than assumed: raise the floor to 3.10 and this caveat
        stops being true, and the test that tells you so should be this one.
        """
        import freya_cli

        self.assertLess(freya_cli.MIN_PYTHON, (3, 10),
                        "the floor moved — the pip caveat in _UPSELL is now noise")
        self.assertIn("3.10+", self.shown())


if __name__ == "__main__":
    unittest.main()
