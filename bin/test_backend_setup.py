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

    def offer(self, answers=("1",), interactive=True):
        """Run the question with a scripted set of answers."""
        queue = list(answers)
        return backend_setup.offer(
            STORE, stream=self.out,
            reader=lambda: queue.pop(0) if queue else "",
            interactive=interactive)


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
    def setUp(self):
        super().setUp()
        original = backend_setup._choices
        backend_setup._choices = lambda store, mod: ["homegrown"]
        self.addCleanup(setattr, backend_setup, "_choices", original)

    def test_it_does_not_ask_when_there_is_nothing_to_choose(self):
        """Asking a question with one answer trains people to skip questions."""
        asked = []
        self.assertIsNone(backend_setup.offer(
            STORE, stream=self.out, reader=lambda: asked.append(1) or "1",
            interactive=True))
        self.assertEqual(asked, [])
        self.assertIsNone(self.saved())

    def test_it_still_closes_the_discovery_gap(self):
        """Nothing else in the toolkit tells you another backend exists before you have
        already installed it, so this line is the whole discovery path."""
        backend_setup.offer(STORE, stream=self.out, reader=lambda: "", interactive=True)
        shown = self.out.getvalue()
        self.assertIn("graphify", shown)
        self.assertIn("--use graphify --global", shown)


class TestItSharesOneDefinitionOfTheMachineHome(unittest.TestCase):
    def test_the_machine_level_home_has_one_definition(self):
        """`~/.freya` holds both the update throttle and the settings file. Two independent
        computations of that path would let `FREYA_HOME` relocate one and not the other — so
        a test run would isolate its configuration and still write into the real home."""
        sys.path.insert(0, str(STORE / "skills" / "freya-code-graph" / "scripts"))
        import settings as settings_mod
        import updater

        self.assertEqual(Path(settings_mod.global_home()).resolve(),
                         updater.state_dir().resolve())

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


if __name__ == "__main__":
    unittest.main()
