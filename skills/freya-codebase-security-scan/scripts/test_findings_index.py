#!/usr/bin/env python3
"""The findings index under ADR-012: a downgraded finding is reclassified, never removed.

There is no `findings_index.py` module. `findings.json` is emitted by the scan agent
following `references/findings-schema.md`, so the rule this file pins is split across
two other skills' scripts: `behavior_graph.covering()` is the deterministic gate that
decides which behaviors may license a downgrade at all, and
`collect_status.security_bucket()` is the consumer that stops counting a downgraded
finding as outstanding. Both are imported here rather than re-implemented.
"""
import json
import os
import shutil
import sys
import tempfile
import unittest

_SKILLS = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_SKILLS, "freya-behavior-graph", "scripts"))
sys.path.insert(0, os.path.join(_SKILLS, "freya-status", "scripts"))
import behavior_graph  # noqa: E402
import collect_status  # noqa: E402


class DowngradeTest(unittest.TestCase):
    """ADR-012's downgrade rule, at the layer where the finding is written down."""

    SPEC = """---
id: SPEC-500
title: Anti-enumeration
category: features
status: implemented
behaviors:
  - behavior_id: BEH-500
    title: Unknown email does not reveal whether a user exists
    state: accepted
    level: unit
    adapter: vitest
    locator: lib/anti-enumeration.test.ts::does not reveal
  - behavior_id: BEH-501
    title: Dates render in the requested locale
    state: proposed
    level: unit
    adapter: vitest
    locator: lib/date-formatter.test.ts::renders the locale
---
# body
"""

    def setUp(self):
        self.proj = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.proj, ignore_errors=True)

        # The spec is the fixture's evidence, not the graph. This setUp used to write a
        # behavior.json with nothing behind it, which is SEC-006's mechanism verbatim —
        # sitting in this suite as the thing that licensed a downgrade. `covering()` now
        # reads state and locator from the spec and requires the locator to resolve, so
        # the fixture has to carry both.
        specs = os.path.join(self.proj, "knowledge-base", "specs", "features")
        os.makedirs(specs)
        with open(os.path.join(specs, "SPEC-500.md"), "w", encoding="utf-8") as f:
            f.write(self.SPEC)
        os.makedirs(os.path.join(self.proj, "lib"))
        for name in ("anti-enumeration.test.ts", "date-formatter.test.ts"):
            with open(os.path.join(self.proj, "lib", name), "w", encoding="utf-8") as f:
                f.write("")

        graph_dir = os.path.join(self.proj, "knowledge-base", ".graph")
        os.makedirs(graph_dir)
        # BEH-500 is accepted and its test exercises the flagged file — the strongest
        # intentional-design evidence there is. BEH-501 covers the other flagged file
        # but is only proposed, which is intent nobody has executed.
        #
        # `source: "observed"` is spelled out because it is now load-bearing: an entry
        # whose source is `static` is the import graph's inference with no test behind it,
        # and it no longer licenses a downgrade (SEC-006). The runner always writes the
        # field; a fixture omitting it tests a shape only a hand-edited file has.
        with open(os.path.join(graph_dir, "behavior.json"), "w", encoding="utf-8") as f:
            json.dump({"version": 1, "commit": "fixture", "behaviors": {
                "BEH-500": {"spec_id": "SPEC-500", "state": "accepted",
                            "coverage": "observed",
                            "exercises": [{"path": "lib/anti-enumeration.ts",
                                           "source": "observed"}]},
                "BEH-501": {"spec_id": "SPEC-500", "state": "proposed",
                            "coverage": "unknown",
                            "exercises": [{"path": "lib/date-formatter.ts"}]},
            }}, f)

        self.index_path = os.path.join(
            self.proj, "knowledge-base", "security", "codebase-security", "findings.json")
        os.makedirs(os.path.dirname(self.index_path))
        self._write_index({"version": 1, "scanned_commit": "fixture",
                           "report": "knowledge-base/security/codebase-security/2026-08-21.md",
                           "findings": [
                               {"id": "SEC-001", "title": "Endpoint does not verify the user exists",
                                "severity": "high", "status": "open",
                                "file": "lib/anti-enumeration.ts", "line": 31},
                               {"id": "SEC-002", "title": "Locale read from an unvalidated header",
                                "severity": "medium", "status": "open",
                                "file": "lib/date-formatter.ts", "line": 12},
                           ]})

    def _write_index(self, index):
        with open(self.index_path, "w", encoding="utf-8") as f:
            json.dump(index, f)

    def _read_index(self):
        with open(self.index_path, encoding="utf-8") as f:
            return json.load(f)

    def test_a_behavior_explained_finding_is_reclassified_not_removed(self):
        """ADR-012's downgrade is the only sanctioned way for this toolkit to stop
        counting a real security finding, so the *shape* of it is the safety property:
        annotate and reclassify, never delete. A vanished row is a finding a model
        silenced with nobody able to check the claim afterwards.

        SPEC-027 records that this half is enforced nowhere in code — `findings.json`
        is agent-written from SKILL.md prose, so nothing fails today if a report loop
        drops the row instead of restating it. The last two assertions are why that is
        dangerous rather than merely untidy: `security_bucket` returns an identical
        answer for a reclassified index and for one the row was deleted from, so the
        surviving row is the *only* record that a downgrade ever happened.

        The gate half is real code and is asserted first: `covering()` returns the
        accepted behavior and refuses the proposed one. That refusal is load-bearing
        here — all 149 behaviors in this repository are still `proposed` (measured
        2026-08-21), so without it a bootstrap guess could silence a live finding.
        """
        covering = behavior_graph.covering(self.proj, "lib/anti-enumeration.ts")["covering"]
        self.assertEqual([c["behavior_id"] for c in covering], ["BEH-500"])
        # Proposed intent is not verified intent: it may annotate, never silence.
        self.assertEqual(
            behavior_graph.covering(self.proj, "lib/date-formatter.ts")["covering"], [])

        # The downgrade, applied the way the skill's report loop is specified to apply
        # it: edit the row in place, leave the list alone.
        index = self._read_index()
        row = next(f for f in index["findings"] if f["id"] == "SEC-001")
        row["status"] = "intentional"
        row["behavior_ref"] = covering[0]["behavior_id"]
        self._write_index(index)

        reclassified = self._read_index()["findings"]
        self.assertEqual([f["id"] for f in reclassified], ["SEC-001", "SEC-002"])
        self.assertEqual(reclassified[0]["status"], "intentional")
        self.assertEqual(reclassified[0]["behavior_ref"], "BEH-500")
        # Reclassified, not rewritten: the evidence a reviewer needs to reverse the
        # judgement is the finding itself, unedited apart from its disposition.
        self.assertEqual(reclassified[0]["severity"], "high")
        self.assertEqual(reclassified[0]["file"], "lib/anti-enumeration.ts")
        self.assertEqual(reclassified[0]["line"], 31)
        self.assertEqual(reclassified[0]["title"],
                         "Endpoint does not verify the user exists")

        # It stops being outstanding — that is the whole point of downgrading it.
        outstanding, note = collect_status.security_bucket(self.proj)
        self.assertIsNone(note)
        self.assertEqual([f["id"] for f in outstanding], ["SEC-002"])

        # And this is why "never delete" has to be a rule rather than a preference:
        # to every consumer of the outstanding count, a deleted finding and a
        # reclassified one are the same answer.
        self._write_index({"version": 1, "findings":
                           [f for f in reclassified if f["id"] != "SEC-001"]})
        deleted, _ = collect_status.security_bucket(self.proj)
        self.assertEqual([f["id"] for f in deleted], ["SEC-002"])
        self.assertEqual(deleted, outstanding)


if __name__ == "__main__":
    unittest.main()
