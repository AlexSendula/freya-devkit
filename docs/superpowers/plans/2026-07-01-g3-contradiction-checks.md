# G3 — Tier-2 Contradiction Checks Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Catch when a changed spec's intent contradicts a higher-authority intent (a principle, or a same-category peer's decision) — advisory, resolve-to-proceed.

**Architecture:** One deterministic helper `contradictions.py` (`context` / `resolve` / `prior`) backs an agent-run contradiction check documented once in spec-manager's SKILL.md and referenced from `create`, `update <spec>`, and wrap-up Phase 3.5 (step 6). `context` reuses G2's `principles.parse_principles` and the existing spec index; resolutions are an append-only `contradiction-resolutions.jsonl` keyed by `(spec, against)`, with the same LLM-first triage as G2.

**Tech Stack:** Python 3.12 stdlib only (`unittest`, `argparse`, `json`, `datetime`, `pathlib`); reuses sibling scripts `principles.py` (`parse_principles`, `PRINCIPLES_RELPATH`) and `search_specs.py` (`load_all_specs`, `find_specs_dir`, `Spec.category`/`Spec.intentional_decisions`); SKILL.md agent procedures.

## Global Constraints

- **Stdlib-only Python** — zero pip installs.
- **Append-only resolutions.** `contradiction-resolutions.jsonl` is only appended to; **never rewrite a line.** Retirement is a later `superseded` **record** (latest-wins per `(spec, against)`), not a mutated field.
- **Advisory / procedural, resolve-to-proceed.** Model judgment → agent-honored gate (never a script hard-block, never auto-fail on model confidence). Each finding is **fixed / refuted / reconciled** before the cycle completes; "ignore and push" is not a resolution; **no standing backlog**.
- **Auto-clear is fenced:** re-judge the *current spec intent* against the *specific* prior reason (not the spec id); **bias to escalate** on ambiguity; **always logged** (`verdict: auto-cleared`); a finding with **no prior** always reaches the human.
- **Authority-order resolution:** vs a **principle** → fix the spec (or amend the principle); vs a **peer** → reconcile/refute.
- **ADR-blind:** never compare against `knowledge-base/decisions/` (no ADR machinery — Phase 4). **Declarative-drift out** (Phase 4).
- **Scope = category:** `context` includes principles + *same-category* peers' decisions, **excludes the changed spec itself**, and excludes peers with no decisions.
- **No-op / fail-open:** empty comparison set / spec-not-found / no git / tooling error → the check no-ops or degrades gracefully; never a false "clean," never a block.
- **Staging:** `contradiction-resolutions.jsonl` + any `principles.md`/spec amendment → `knowledge-base/` **artifacts** (commit 2); a code/spec *fix* rides its normal commit.
- **DRY:** reuse `principles.parse_principles` + `search_specs.load_all_specs` — do not re-implement principle parsing or spec loading. Do **not** extract a shared resolution module (deliberate — avoids churning G2).
- **Path style:** invoke via `"${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py"`.
- **Never touch the production webapp**; dogfood on the testbed only.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `contradictions.py` — context / resolve / prior helpers

**Files:**
- Create: `skills/spec-manager/scripts/contradictions.py`
- Test: `skills/spec-manager/scripts/test_contradictions.py`

**Interfaces:**
- Consumes: `principles.parse_principles(text) -> list[dict]`, `principles.PRINCIPLES_RELPATH`; `search_specs.load_all_specs(specs_dir) -> list[Spec]`, `search_specs.find_specs_dir(start) -> str` (Spec has `.id`, `.category`, `.intentional_decisions`).
- Produces:
  - `build_context(project: str, spec_id: str) -> dict` — `{"spec","category","principles":[…],"peers":[{"spec_id","decisions":[…]}],"note"?:str}`.
  - `append_resolution(project: str, record: dict) -> str` — append one JSONL line, return path.
  - `active_prior(project: str, spec: str, against=None) -> tuple[list[dict], list[str]]` — latest-active per `(spec, against)` for `spec`, + warnings.
  - `RESOLUTIONS_RELPATH = "knowledge-base/contradiction-resolutions.jsonl"`, `VERDICTS = ("refuted","amended","auto-cleared","superseded")`.
  - CLI: `context --spec <id> --project .`; `resolve --project . --spec <id> --against <principle:N|SPEC-NNN> --verdict V --reason "…" [--commit SHA] [--date YYYY-MM-DD]`; `prior --project . --spec <id> [--against X] [--format json]`. All exit 0.

- [ ] **Step 1: Write the failing test file**

Create `skills/spec-manager/scripts/test_contradictions.py`:

```python
#!/usr/bin/env python3
"""Proof suite for contradictions.py — the G3 contradiction-check helpers."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from contradictions import (  # noqa: E402
    build_context, append_resolution, active_prior, RESOLUTIONS_RELPATH,
)

PRINCIPLES = "## Principles\n\n1. **Authenticated by default.** Endpoints need auth.\n"


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _spec(spec_id, category, decisions):
    block = ""
    if decisions:
        block = "intentional_decisions:\n" + "".join(f"  - {d}\n" for d in decisions)
    return (
        "---\n"
        f"id: {spec_id}\n"
        f"title: {spec_id} Title\n"
        f"category: {category}\n"
        "status: implemented\n"
        "certainty: 90\n"
        "created: 2026-07-01\n"
        "updated: 2026-07-01\n"
        f"{block}"
        "---\n\n"
        f"# {spec_id}\n"
    )


class ContextCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _project(self, root):
        _write(root / "knowledge-base/principles.md", PRINCIPLES)
        _write(root / "knowledge-base/specs/auth/SPEC-001.md",
               _spec("SPEC-001", "auth", ["No password fallback"]))
        _write(root / "knowledge-base/specs/auth/SPEC-002.md",
               _spec("SPEC-002", "auth", ["Uniform 404 to prevent enumeration"]))
        _write(root / "knowledge-base/specs/api/SPEC-003.md",
               _spec("SPEC-003", "api", ["Rate limit at the edge"]))

    def test_context_has_principles_and_same_category_peers(self):
        root = self._root(); self._project(root)
        ctx = build_context(str(root), "SPEC-001")
        self.assertEqual(ctx["category"], "auth")
        self.assertEqual(len(ctx["principles"]), 1)
        self.assertEqual([p["spec_id"] for p in ctx["peers"]], ["SPEC-002"])  # same cat, not self

    def test_context_excludes_self_and_other_categories(self):
        root = self._root(); self._project(root)
        peers = [p["spec_id"] for p in build_context(str(root), "SPEC-001")["peers"]]
        self.assertNotIn("SPEC-001", peers)   # self excluded
        self.assertNotIn("SPEC-003", peers)   # different category excluded

    def test_context_excludes_peers_without_decisions(self):
        root = self._root()
        _write(root / "knowledge-base/principles.md", PRINCIPLES)
        _write(root / "knowledge-base/specs/auth/SPEC-001.md", _spec("SPEC-001", "auth", ["d"]))
        _write(root / "knowledge-base/specs/auth/SPEC-002.md", _spec("SPEC-002", "auth", []))
        self.assertEqual(build_context(str(root), "SPEC-001")["peers"], [])

    def test_context_spec_not_found_is_safe(self):
        root = self._root(); self._project(root)
        ctx = build_context(str(root), "SPEC-999")
        self.assertEqual(ctx["peers"], [])
        self.assertIn("note", ctx)

    def test_context_no_principles(self):
        root = self._root()
        _write(root / "knowledge-base/specs/auth/SPEC-001.md", _spec("SPEC-001", "auth", ["d"]))
        self.assertEqual(build_context(str(root), "SPEC-001")["principles"], [])


class ResolutionsCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _rec(self, verdict, against, spec="SPEC-001", reason="r"):
        return {"date": "2026-07-01", "spec": spec, "against": against,
                "verdict": verdict, "reason": reason}

    def test_append_is_append_only(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1"))
        append_resolution(str(root), self._rec("refuted", "SPEC-002"))
        lines = (root / RESOLUTIONS_RELPATH).read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["against"], "principle:1")

    def test_prior_returns_active_for_spec(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1", reason="intentional public"))
        recs, warns = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["reason"], "intentional public")
        self.assertEqual(warns, [])

    def test_prior_filters_by_spec_and_against(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1", spec="SPEC-001"))
        self.assertEqual(active_prior(str(root), "SPEC-002")[0], [])           # other spec
        self.assertEqual(active_prior(str(root), "SPEC-001", against="SPEC-009")[0], [])  # other against

    def test_superseded_retires_the_pair(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1"))
        append_resolution(str(root), self._rec("superseded", "principle:1", reason="spec rewritten"))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual(recs, [])
        self.assertEqual(len((root / RESOLUTIONS_RELPATH).read_text().splitlines()), 2)  # append-only

    def test_latest_wins(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1", reason="first"))
        append_resolution(str(root), self._rec("refuted", "principle:1", reason="second"))
        recs, _ = active_prior(str(root), "SPEC-001")
        self.assertEqual([r["reason"] for r in recs], ["second"])

    def test_malformed_line_skipped_with_warning(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", "principle:1"))
        with (root / RESOLUTIONS_RELPATH).open("a", encoding="utf-8") as f:
            f.write("{bad json\n")
        recs, warns = active_prior(str(root), "SPEC-001")
        self.assertEqual(len(recs), 1)
        self.assertTrue(warns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/spec-manager/scripts && python test_contradictions.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'contradictions'`.

- [ ] **Step 3: Write `contradictions.py`**

Create `skills/spec-manager/scripts/contradictions.py`:

```python
#!/usr/bin/env python3
"""
Contradiction checks (governance G3) — deterministic helpers.

- `context`: assemble the higher-authority comparison set for a changed spec
             (principles + same-category peer decisions; the spec itself excluded).
- `resolve`: append a resolution record to contradiction-resolutions.jsonl.
- `prior`  : active prior resolutions for a spec (recurrence handling — the agent
             re-validates these against the current spec text).

The contradiction JUDGMENT (does the changed intent contradict a higher-authority
intent?) and the triage (auto-clear / retire / escalate) are agent work in the
spec-manager / wrap-up SKILL.md; this script only does the deterministic gather /
append / lookup.

ADR-blind: cross-cutting knowledge-base/decisions/ ADRs are NOT compared (no ADR
machinery yet — Phase 4). Retirement is append-only: a later `superseded` record
(latest-wins per (spec, against)), never a mutated field.

Paths (under --project, default "."):
  knowledge-base/principles.md                     (via principles.py)
  knowledge-base/specs/                             (via search_specs)
  knowledge-base/contradiction-resolutions.jsonl    (append-only)
"""

import argparse
import json
import os
import sys
from datetime import date as _date
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from search_specs import load_all_specs, find_specs_dir  # noqa: E402
from principles import parse_principles, PRINCIPLES_RELPATH  # noqa: E402

RESOLUTIONS_RELPATH = "knowledge-base/contradiction-resolutions.jsonl"
VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")


def _resolutions_path(project):
    return Path(project) / RESOLUTIONS_RELPATH


def _load_principles(project):
    path = Path(project) / PRINCIPLES_RELPATH
    if not path.exists():
        return []
    return parse_principles(path.read_text(encoding="utf-8", errors="replace"))


def build_context(project, spec_id):
    """Assemble {spec, category, principles, peers} for a changed spec.

    peers = same-category specs (excluding the changed spec) that carry
    intentional_decisions. Returns category=None + empty peers + a note if the
    spec isn't found (caller treats an empty comparison set as a no-op).
    """
    specs = load_all_specs(find_specs_dir(project))
    principles = _load_principles(project)
    target = next((s for s in specs if s.id == spec_id), None)
    if target is None:
        return {"spec": spec_id, "category": None, "principles": principles,
                "peers": [], "note": f"spec {spec_id} not found"}
    peers = [
        {"spec_id": s.id, "decisions": s.intentional_decisions}
        for s in specs
        if s.category == target.category and s.id != spec_id and s.intentional_decisions
    ]
    return {"spec": spec_id, "category": target.category,
            "principles": principles, "peers": peers}


def append_resolution(project, record):
    path = _resolutions_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return str(path)


def _load_records(project):
    path = _resolutions_path(project)
    records, warnings = [], []
    if not path.exists():
        return records, warnings
    for i, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            warnings.append(f"skipped malformed line {i} in {RESOLUTIONS_RELPATH}")
    return records, warnings


def active_prior(project, spec, against=None):
    """Latest-active resolution per (spec, against) for the given spec.

    Keeps the LAST (append-order) record per (spec, against); drops pairs whose
    latest verdict is `superseded`; filters to `spec` (and `against` if given).
    Each record has a single `against`, so no explosion/de-dup is needed.
    """
    records, warnings = _load_records(project)
    latest = {}  # (spec, against) -> (idx, record)
    for idx, rec in enumerate(records):
        latest[(rec.get("spec"), rec.get("against"))] = (idx, rec)
    picked = {}
    for (sp, ag), (idx, rec) in latest.items():
        if rec.get("verdict") == "superseded":
            continue
        if sp != spec:
            continue
        if against is not None and ag != against:
            continue
        picked[idx] = rec
    return [picked[i] for i in sorted(picked)], warnings


def _cmd_resolve(args):
    record = {"date": args.day or _date.today().isoformat(),
              "spec": args.spec, "against": args.against,
              "verdict": args.verdict, "reason": args.reason}
    if args.commit:
        record["commit"] = args.commit
    print(append_resolution(args.project, record))


def main():
    parser = argparse.ArgumentParser(description="Contradiction-check helpers (G3)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("context", help="Assemble the comparison set for a spec")
    c.add_argument("--project", "-p", default=".")
    c.add_argument("--spec", required=True)

    r = sub.add_parser("resolve", help="Append a resolution record")
    r.add_argument("--project", "-p", default=".")
    r.add_argument("--spec", required=True)
    r.add_argument("--against", required=True, help="conflicting item: principle:N or SPEC-NNN")
    r.add_argument("--verdict", choices=VERDICTS, required=True)
    r.add_argument("--reason", required=True)
    r.add_argument("--commit")
    r.add_argument("--date", dest="day")

    pr = sub.add_parser("prior", help="Active prior resolutions for a spec")
    pr.add_argument("--project", "-p", default=".")
    pr.add_argument("--spec", required=True)
    pr.add_argument("--against")
    pr.add_argument("--format", "-f", choices=["json"], default="json")

    args = parser.parse_args()
    if args.cmd == "context":
        print(json.dumps(build_context(args.project, args.spec), indent=2))
    elif args.cmd == "resolve":
        _cmd_resolve(args)
    elif args.cmd == "prior":
        recs, warns = active_prior(args.project, args.spec, against=args.against)
        for w in warns:
            print(w, file=sys.stderr)
        print(json.dumps(recs, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/spec-manager/scripts && python test_contradictions.py`
Expected: PASS — `Ran 11 tests ... OK`.

- [ ] **Step 5: Verify the CLI end-to-end**

Run:
```bash
cd /tmp && rm -rf ctest && mkdir -p ctest/knowledge-base/specs/auth
printf '## Principles\n\n1. **Authenticated by default.** Endpoints need auth.\n' > ctest/knowledge-base/principles.md
printf -- '---\nid: SPEC-001\ntitle: A\ncategory: auth\nstatus: implemented\ncertainty: 90\ncreated: 2026-07-01\nupdated: 2026-07-01\nintentional_decisions:\n  - No password fallback\n---\n# A\n' > ctest/knowledge-base/specs/auth/SPEC-001.md
S=/Users/main/Documents/projects/freya-devkit/skills/spec-manager/scripts
python "$S/contradictions.py" context --project ctest --spec SPEC-001
python "$S/contradictions.py" resolve --project ctest --spec SPEC-001 --against principle:1 --verdict refuted --reason "start endpoint is public by design"
python "$S/contradictions.py" prior --project ctest --spec SPEC-001
```
Expected: `context` prints JSON with `"category": "auth"` and 1 principle (no peers — SPEC-001 is alone); `resolve` prints the `.jsonl` path; `prior` prints a one-record array with `"against": "principle:1"`.

- [ ] **Step 6: Run the sibling suites to confirm no regressions**

Run: `cd skills/spec-manager/scripts && python test_principles.py && python test_verify_intent.py && python test_verify_links.py && python test_intent.py`
Expected: all suites `OK`.

- [ ] **Step 7: Commit**

```bash
git add skills/spec-manager/scripts/contradictions.py skills/spec-manager/scripts/test_contradictions.py
git commit -m "feat(spec-manager): contradictions.py — context/resolve/prior helpers (G3)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wrap-up batched contradiction check (SKILL.md)

**Files:**
- Modify: `skills/wrap-up/SKILL.md` (add Phase 3.5 step 6; add a staging-table row; update the scope blockquote)

**Interfaces:**
- Consumes: `contradictions.py` (`context` / `prior` / `resolve`) from Task 1, via `"${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py"`; the shared G3 procedure defined in spec-manager SKILL.md (Task 3).
- Produces: no code — the batched contradiction gate + staging rule.

- [ ] **Step 1: Add Phase 3.5 step 6 (the batched contradiction check)**

In `skills/wrap-up/SKILL.md`, in "### Phase 3.5", **after** step 5 (the G2 "Principle checkpoint …" block) and **before** the `> Scope:` blockquote, insert:

````markdown
6. **Contradiction check (governance G3 — resolve-to-proceed).** After the principle
   checkpoint, check the *intent* changed this cycle. Same posture as step 5: **model
   judgment → procedural gate**, never a script hard-block, never auto-fail on model
   confidence; wrap-up **must not complete while a finding is unresolved.**

   a. **Find the specs changed this cycle** — the `knowledge-base/specs/**` files in
      `git diff "$BASE" --name-only` (the same `BASE` from step 3). No changed spec ⇒
      **skip this step.**

   b. **For each changed spec, run the G3 contradiction check** — see the shared
      procedure in the spec-manager skill ("Contradiction Check (governance G3)"):
      assemble the comparison set with
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
        context --project . --spec <SPEC-ID>
      ```
      then judge the changed spec's intent against each `principle` (higher authority)
      and each `peer` decision (same authority), triage any finding against
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
        prior --project . --spec <SPEC-ID>
      ```
      (auto-clear / retire / escalate, per the same guardrails as G2), and **resolve**
      each escalated finding: **fix** the spec (or amend the principle / reconcile the
      peer), or **refute** —
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
        resolve --project . --spec <SPEC-ID> --against <principle:N|SPEC-NNN> \
        --verdict <refuted|amended|auto-cleared|superseded> --reason "…"
      ```

   "Ignore and push" is not a resolution; contradictions are resolved in the cycle that
   raised them (no backlog). **ADR-blind** (no comparison against `decisions/`).
   Fail-open on no changed specs / no principles / tooling error.
````

- [ ] **Step 2: Add the staging-table row**

In `skills/wrap-up/SKILL.md`, in the "#### Behavior-aware staging rule" table, add a row (near the `principle-resolutions.jsonl` row from G2):

```markdown
| `contradiction-resolutions.jsonl` + any `principles.md`/spec amendment | **Artifacts** (commit 2) |
```

- [ ] **Step 3: Update the Phase 3.5 scope blockquote**

In `skills/wrap-up/SKILL.md`, the `> Scope:` blockquote currently ends with the G2-era sentence: *"Model judgment enters here only as the **principle checkpoint** (G2, step 5: resolve-to-proceed, procedural — never a script hard-block); model-based *contradiction* checks (intent-vs-intent, G3) remain a later track."* Replace that entire sentence (it may span two lines) with:

```markdown
> Model judgment enters here as the **principle checkpoint** (G2, step 5: code-vs-principle)
> and the **contradiction check** (G3, step 6: intent-vs-intent) — both resolve-to-proceed,
> procedural, never a script hard-block. G3 is **ADR-blind** until the Phase-4 ADR machinery
> ships; **declarative-drift** (code-vs-declared-intent) also remains a Phase-4 track.
```

- [ ] **Step 4: Verify the wiring and confirm suites green**

Run:
```bash
cd /Users/main/Documents/projects/freya-devkit
grep -c "contradictions.py" skills/wrap-up/SKILL.md
grep -n "Contradiction check (governance G3" skills/wrap-up/SKILL.md
grep -n "contradiction-resolutions.jsonl" skills/wrap-up/SKILL.md
(cd skills/spec-manager/scripts && python test_contradictions.py)
```
Expected: `contradictions.py` appears several times; the step-6 heading present; the staging row present; `test_contradictions.py` `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/wrap-up/SKILL.md
git commit -m "docs(wrap-up): contradiction check (G3) — Phase 3.5 step 6, resolve-to-proceed

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: spec-manager G3 procedure + create/update wiring (SKILL.md)

**Files:**
- Modify: `skills/spec-manager/SKILL.md` (a "Contradiction Check (governance G3)" procedure section; a pointer in `create`; a pointer in `update <spec>`)

**Interfaces:**
- Consumes: `contradictions.py` from Task 1.
- Produces: no code — the shared G3 procedure (referenced by wrap-up Task 2) + the interactive triggers.

- [ ] **Step 1: Add the "Contradiction Check (governance G3)" procedure section**

In `skills/spec-manager/SKILL.md`, after the "Principle Enforcement (governance G2)" section (added in G2), add:

````markdown
## Contradiction Check (governance G3)

When a spec's intent is **created or changed**, check it doesn't **contradict a
higher-authority intent** (vision §5 authority order). Runs interactively here
(`create`, `update <spec>`) and batched at wrap-up (Phase 3.5 step 6). Model
judgment → **advisory / resolve-to-proceed**, never a hard-block on model confidence.

**The procedure, for a changed spec `<SPEC-ID>`:**

1. **Assemble the comparison set:**
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
     context --project . --spec <SPEC-ID>
   ```
   Returns `principles` (higher authority) + same-category `peers`' decisions (same
   authority); the spec itself is excluded. Empty set ⇒ **no-op** (nothing to check).

2. **Judge** the changed spec's intent (purpose, scope, decisions) against each item:
   *does this changed intent contradict it?* Name each finding by the conflicting item
   (`principle:2` or `SPEC-003`) and why.

3. **Triage against prior resolutions:**
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
     prior --project . --spec <SPEC-ID>
   ```
   Re-validate any prior against the *current* spec text: **still valid** → auto-clear
   (`resolve --verdict auto-cleared`); **stale** (spec rewritten) → retire
   (`resolve --verdict superseded`); **now a real contradiction** → escalate. Guardrails:
   re-judge the current intent vs the *specific* prior reason (not the spec id); bias to
   escalate on ambiguity; always log auto-clears; a finding with no prior always reaches
   the human.

4. **Resolve each finding** (by the authority order):
   - **vs a principle** → **fix the spec** (default), or consciously **amend the principle**.
   - **vs a peer decision** → **reconcile** (fix one side) or **refute** if they don't truly conflict.
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py" \
     resolve --project . --spec <SPEC-ID> --against <principle:N|SPEC-NNN> \
     --verdict <refuted|amended|auto-cleared|superseded> --reason "…"
   ```
   A **fix** (editing the spec / peer) needs no record — git is the record. Records +
   any amendment stage with the **artifacts** commit.

**ADR-blind:** `decisions/` ADRs are not compared (no ADR machinery yet — Phase 4). The
same check extends to ADRs once that ships. **Declarative-drift** (code-vs-declared-intent)
is a separate Phase-4 track.
````

- [ ] **Step 2: Add a pointer in `create`**

In `skills/spec-manager/SKILL.md`, in the `### /freya-devkit:spec-manager create <name>` section, after the step that updates the README index (the last numbered step), add a final numbered step (use the next number in that list):

```markdown
N. **Contradiction check (governance G3).** Run the G3 contradiction check on the new
   spec (see "Contradiction Check (governance G3)"): a freshly authored spec must not
   contradict a principle or a same-category peer's decision. Resolve any finding before
   finishing.
```

(Replace `N.` with the actual next number in the `create` list.)

- [ ] **Step 3: Add a pointer in `update <spec>`**

In `skills/spec-manager/SKILL.md`, in the `### /freya-devkit:spec-manager update <spec>` section, after its final numbered step, add:

```markdown
N. **Contradiction check (governance G3).** After updating the spec, run the G3
   contradiction check on it (see "Contradiction Check (governance G3)") — a changed
   decision must not contradict a principle or a same-category peer. Resolve any finding.
```

(Replace `N.` with the actual next number in the `update <spec>` list.)

- [ ] **Step 4: Verify and confirm suites green**

Run:
```bash
cd /Users/main/Documents/projects/freya-devkit
grep -c "contradictions.py" skills/spec-manager/SKILL.md
grep -n "Contradiction Check (governance G3)" skills/spec-manager/SKILL.md
(cd skills/spec-manager/scripts && python test_contradictions.py)
```
Expected: `contradictions.py` appears in the section + create/update pointers reference the section; the G3 section present; tests `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/spec-manager/SKILL.md
git commit -m "docs(spec-manager): G3 contradiction-check procedure + create/update wiring

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Dogfood (after all tasks, on the testbed — not part of the plan's commits)

On the testbed (`/Users/main/Documents/projects/viva-croatia-testbed`), on a throwaway branch: ensure `principles.md` has a sharp rule and there are ≥2 same-category specs with decisions. (1) Add/adjust a spec decision that contradicts a principle → run the G3 procedure → confirm it surfaces the `principle:N` finding + resolve-to-proceed. (2) Refute it (`resolve --verdict refuted`) → confirm logged; re-run unchanged → confirm the agent would auto-clear from `prior`. (3) Supersede it and confirm `prior` drops it while the file keeps both lines. (4) Two same-category specs with conflicting decisions → confirm a peer (`SPEC-NNN`) finding surfaces as reconcile. Restore the testbed to `main` and delete the branch. Production webapp off-limits.

---

## Notes for the executor

- **DRY reuse:** `contradictions.py` imports `principles.parse_principles` + `search_specs.load_all_specs` — do not re-implement principle parsing or spec loading. Keep the `sys.path.insert(0, dirname(__file__))` shim so sibling imports work regardless of cwd.
- **Append-only is load-bearing:** never rewrite `contradiction-resolutions.jsonl`; retirement is a later `superseded` record. `test_superseded_retires_the_pair` + `test_append_is_append_only` guard this.
- **Single `against` per record** (unlike G2's `paths` list) — `active_prior` needs no explosion/de-dup; keep it simple.
- **Tasks 2–3 are agent-procedure/doc wiring** — no unit tests beyond Task 1; verify by the grep checks and by keeping `test_contradictions.py` green. The judgment/triage is validated in the **dogfood**.
- The G3 procedure is defined **once** in spec-manager SKILL.md (Task 3) and referenced by `create`, `update <spec>`, and wrap-up (Task 2) — do not duplicate the full procedure into wrap-up.
