"""Test-session isolation for anything that reads machine-level state.

`freya` gained a machine-level default on 2026-08-20 — `~/.freya/settings.json`, holding the
backend the engineer chose once at install time. That file is read by `settings.load()`, which
is read by backend selection, which is read by every build in the suite.

Which means that without this, the answer to "does a project with no settings resolve to the
floor?" depends on **whose laptop the tests are running on**. Green here and red in CI, or the
reverse, for a reason nothing in the repository records. A suite whose result depends on
unversioned state outside the checkout is not a regression gate.

So the whole session runs against an empty throwaway home.

**This is a safety net, not the mechanism.** It is only collected when pytest's rootdir is the
repository, so `cd skills && pytest .` routes around it entirely — measured: ten tests failed
against a real `~/.freya/settings.json` that way. The tests that actually depend on the
machine-level default isolate themselves (`MachineHome` in `test_substrate.py`, and the two
classes that shell out to code-graph), which is both invocation-independent and better
documentation: a test asserting what happens "with nothing configured" should say that where
it is read.
"""
import os
import tempfile

# Claimed before collection, so a module that reads settings at import time is covered too.
_SANDBOX = tempfile.mkdtemp(prefix="freya-test-home-")
os.environ["FREYA_HOME"] = _SANDBOX
