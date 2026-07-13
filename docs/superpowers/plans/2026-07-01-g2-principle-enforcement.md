# G2 — Principle Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `principles.md` actually enforced — a resolve-to-proceed principle checkpoint at wrap-up (model judgment) plus soft injection into the flows we own.

**Architecture:** One deterministic helper `principles.py` (`list` / `resolve` / `prior`) backs an agent-run checkpoint documented in wrap-up's SKILL.md: the agent judges the change diff against the principles, triages each finding against prior resolutions (auto-clear / retire / escalate), and resolves the rest with the human before completing. Resolutions are an append-only `principle-resolutions.jsonl`. Soft injection surfaces `principles.md` in wrap-up and spec-manager `create`/`scan`.

**Tech Stack:** Python 3.12 stdlib only (`unittest`, `argparse`, `json`, `re`, `datetime`, `pathlib`); git CLI (the diff/BASE come from wrap-up's existing Phase 3.5 context); SKILL.md agent procedures.

## Global Constraints

- **Stdlib-only Python** — zero pip installs.
- **Append-only resolutions.** `principle-resolutions.jsonl` is only ever appended to; **never rewrite a line.** Retirement of a stale resolution is a *later* `superseded` **record** (latest-wins per `(principle, path)`), **not** a mutated `status` field — a flipped field would require rewriting, breaking append-only.
- **Resolve-to-proceed, human is the calibration.** Each finding is resolved by **fix / refute / amend**; "ignore and push" is not a resolution. The gate is **procedure-enforced by the wrap-up agent** (not a script exit) and sits in the advisory phase **after** the deterministic hard-blocks. Never auto-fail on model confidence.
- **Auto-clear is fenced:** it re-judges the *current hunk against the specific prior reason* (not the file); **biases to escalate** on ambiguity; is **always logged** (`verdict: auto-cleared`); and a finding with **no prior** always reaches the human.
- **No standing backlog** — principle findings are resolved within the wrap-up that raised them; `status`/`BACKLOG.md` get no open-principle bucket.
- **No-op / fail-open:** no `principles.md` → checkpoint no-ops; no git / no diff / infra error → no-op, never a false "clean" and never a block.
- **Staging:** `principle-resolutions.jsonl` and any `principles.md` amendment are `knowledge-base/` **artifacts** (commit 2); a code *fix* rides the code commit (commit 1).
- **Path style:** invoke scripts via `"${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/…"` (the dominant convention in the files being edited).
- **Never touch the production webapp**; dogfood on the testbed only.
- Commit messages end with: `Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>`.

---

### Task 1: `principles.py` — parse / append / lookup helpers

**Files:**
- Create: `skills/spec-manager/scripts/principles.py`
- Test: `skills/spec-manager/scripts/test_principles.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (stdlib only).
- Produces:
  - `parse_principles(text: str) -> list[dict]` — `[{"n":int,"title":str,"text":str}]`.
  - `cmd_list(project: str, fmt: str) -> str` — `fmt` in `{"text","json"}`; `""`/`"[]"` when `principles.md` absent.
  - `append_resolution(project: str, record: dict) -> str` — append one JSONL line, return the file path.
  - `active_prior(project: str, paths=None, principle=None) -> tuple[list[dict], list[str]]` — latest-active resolutions per `(principle, path)`, filtered; plus warnings.
  - `PRINCIPLES_RELPATH = "knowledge-base/principles.md"`, `RESOLUTIONS_RELPATH = "knowledge-base/principle-resolutions.jsonl"`, `VERDICTS = ("refuted","amended","auto-cleared","superseded")`.
  - CLI: `list --project . --format text|json`; `resolve --project . --principle N --verdict V --reason "…" --paths f1 f2 [--ref SPEC-NNN] [--commit SHA] [--date YYYY-MM-DD]`; `prior --project . --paths f1 f2 [--principle N] [--format json]`. All exit 0 (lookups/appends never block).

- [ ] **Step 1: Write the failing test file**

Create `skills/spec-manager/scripts/test_principles.py`:

```python
#!/usr/bin/env python3
"""Proof suite for principles.py — the G2 principle-enforcement helpers."""

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from principles import (  # noqa: E402
    parse_principles, cmd_list, append_resolution, active_prior,
    RESOLUTIONS_RELPATH,
)

PRINCIPLES_MD = """# Principles

> intro prose ignored by the parser.

## Principles

1. **Authenticated by default.** Every endpoint requires auth unless a spec documents an exception.
   _Why: a forgotten check should fail closed._

2. **No secret in source.** Secrets come from the environment, never the repo.
"""


def _write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class ParseCase(unittest.TestCase):
    def test_parses_numbered_principles_with_titles(self):
        items = parse_principles(PRINCIPLES_MD)
        self.assertEqual([i["n"] for i in items], [1, 2])
        self.assertEqual(items[0]["title"], "Authenticated by default")
        self.assertIn("fail closed", items[0]["text"])  # continuation line folded in

    def test_freeform_file_yields_no_items(self):
        self.assertEqual(parse_principles("just some prose, no numbered rules"), [])


class ListCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def test_text_prints_section_when_present(self):
        root = self._root()
        _write(root / "knowledge-base/principles.md", PRINCIPLES_MD)
        out = cmd_list(str(root), "text")
        self.assertIn("Authenticated by default", out)
        self.assertNotIn("intro prose", out)  # only the ## Principles section

    def test_absent_file_is_empty_and_safe(self):
        root = self._root()
        self.assertEqual(cmd_list(str(root), "text"), "")
        self.assertEqual(cmd_list(str(root), "json"), "[]")


class ResolutionsCase(unittest.TestCase):
    def _root(self):
        d = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(d, ignore_errors=True))
        return Path(d)

    def _rec(self, verdict, paths, reason="r", principle=1):
        return {"date": "2026-07-01", "principle": principle, "verdict": verdict,
                "paths": paths, "reason": reason}

    def test_append_is_append_only(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"]))
        append_resolution(str(root), self._rec("refuted", ["b.ts"]))
        lines = (root / RESOLUTIONS_RELPATH).read_text().splitlines()
        self.assertEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["paths"], ["a.ts"])  # first line untouched

    def test_prior_returns_matching_active_record(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"], reason="intentional"))
        recs, warns = active_prior(str(root), paths=["a.ts"])
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["reason"], "intentional")
        self.assertEqual(warns, [])

    def test_prior_excludes_unqueried_paths_and_principles(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"], principle=1))
        self.assertEqual(active_prior(str(root), paths=["b.ts"])[0], [])
        self.assertEqual(active_prior(str(root), paths=["a.ts"], principle=2)[0], [])

    def test_superseded_record_retires_the_pair(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"]))
        append_resolution(str(root), self._rec("superseded", ["a.ts"], reason="stale"))
        recs, _ = active_prior(str(root), paths=["a.ts"])
        self.assertEqual(recs, [])  # retired
        # append-only: both lines still on disk
        self.assertEqual(len((root / RESOLUTIONS_RELPATH).read_text().splitlines()), 2)

    def test_latest_refutation_wins(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"], reason="first"))
        append_resolution(str(root), self._rec("refuted", ["a.ts"], reason="second"))
        recs, _ = active_prior(str(root), paths=["a.ts"])
        self.assertEqual([r["reason"] for r in recs], ["second"])

    def test_malformed_line_is_skipped_with_warning(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts"]))
        with (root / RESOLUTIONS_RELPATH).open("a", encoding="utf-8") as f:
            f.write("{not valid json\n")
        recs, warns = active_prior(str(root), paths=["a.ts"])
        self.assertEqual(len(recs), 1)
        self.assertTrue(warns)

    def test_multipath_record_dedupes(self):
        root = self._root()
        append_resolution(str(root), self._rec("refuted", ["a.ts", "b.ts"]))
        recs, _ = active_prior(str(root), paths=["a.ts", "b.ts"])
        self.assertEqual(len(recs), 1)  # one record, not one per path


if __name__ == "__main__":
    unittest.main(verbosity=2)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd skills/spec-manager/scripts && python test_principles.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'principles'`.

- [ ] **Step 3: Write `principles.py`**

Create `skills/spec-manager/scripts/principles.py`:

```python
#!/usr/bin/env python3
"""
Principle enforcement helpers (governance G2).

- `list`   : print the project's principles (soft injection + checkpoint input).
- `resolve`: append a resolution record to principle-resolutions.jsonl.
- `prior`  : return the active prior resolutions touching given files (recurrence
             handling — the wrap-up agent re-validates these against the current diff).

The checkpoint JUDGMENT (does the diff violate a principle?) and the triage
(auto-clear / retire / escalate) are agent work in wrap-up's SKILL.md; this script
only does the deterministic parse / append / lookup.

Paths (under --project, default "."):
  knowledge-base/principles.md
  knowledge-base/principle-resolutions.jsonl   (append-only)

Retirement is expressed as a LATER `superseded` record (latest-wins per
(principle, path)), never by mutating a field — that keeps the log append-only.
"""

import argparse
import json
import os
import re
import sys
from datetime import date as _date
from pathlib import Path

PRINCIPLES_RELPATH = "knowledge-base/principles.md"
RESOLUTIONS_RELPATH = "knowledge-base/principle-resolutions.jsonl"
VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")

_ITEM_RE = re.compile(r"^\s*(\d+)\.\s+(.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")


def _principles_path(project):
    return Path(project) / PRINCIPLES_RELPATH


def _resolutions_path(project):
    return Path(project) / RESOLUTIONS_RELPATH


def parse_principles(text):
    """Parse the numbered principles → [{"n":int,"title":str,"text":str}].

    A principle is a top-level numbered item (`1. **Title.** body`); indented
    continuation lines (e.g. `_Why: …_`) fold into `text`. Non-numbered content is
    ignored, so a free-form file yields fewer/no structured items.
    """
    items, cur = [], None
    for line in text.splitlines():
        m = _ITEM_RE.match(line)
        if m:
            if cur:
                items.append(cur)
            body = m.group(2).strip()
            bold = _BOLD_RE.search(body)
            title = bold.group(1).strip().rstrip(".") if bold else body
            cur = {"n": int(m.group(1)), "title": title, "text": body}
        elif cur is not None and line.strip():
            cur["text"] += " " + line.strip()
    if cur:
        items.append(cur)
    return items


def _principles_section(text):
    """Raw text under a `## Principles` heading, or the whole file if absent."""
    lines = text.splitlines()
    for i, ln in enumerate(lines):
        if ln.strip().lower().startswith("## principles"):
            return "\n".join(lines[i + 1:]).strip()
    return text.strip()


def cmd_list(project, fmt):
    path = _principles_path(project)
    if not path.exists():
        return "" if fmt == "text" else "[]"
    text = path.read_text(encoding="utf-8", errors="replace")
    if fmt == "json":
        return json.dumps(parse_principles(text), indent=2)
    return _principles_section(text)


def append_resolution(project, record):
    path = _resolutions_path(project)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return str(path)


def _load_records(project):
    """(records, warnings) — parsed JSONL lines in append order; skips bad lines."""
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


def active_prior(project, paths=None, principle=None):
    """Latest-active resolution per (principle, path).

    Explodes each record over its `paths`, keeps the LAST (append-order) record per
    (principle, path), drops pairs whose latest verdict is `superseded`, then filters
    to the queried paths/principle. Returns (records, warnings), de-duplicated so a
    multi-path record appears once.
    """
    records, warnings = _load_records(project)
    latest = {}  # (principle, path) -> (append_idx, record)
    for idx, rec in enumerate(records):
        p = rec.get("principle")
        for pth in rec.get("paths") or []:
            latest[(p, pth)] = (idx, rec)
    want = set(paths) if paths else None
    picked = {}  # append_idx -> record (de-dupe multi-path records)
    for (p, pth), (idx, rec) in latest.items():
        if rec.get("verdict") == "superseded":
            continue
        if want is not None and pth not in want:
            continue
        if principle is not None and p != principle:
            continue
        picked[idx] = rec
    return [picked[i] for i in sorted(picked)], warnings


def _cmd_resolve(args):
    record = {"date": args.day or _date.today().isoformat(),
              "principle": args.principle, "verdict": args.verdict,
              "paths": args.paths, "reason": args.reason}
    if args.ref:
        record["ref"] = args.ref
    if args.commit:
        record["commit"] = args.commit
    print(append_resolution(args.project, record))


def main():
    parser = argparse.ArgumentParser(description="Principle enforcement helpers (G2)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    pl = sub.add_parser("list", help="Print the project's principles")
    pl.add_argument("--project", "-p", default=".")
    pl.add_argument("--format", "-f", choices=["text", "json"], default="text")

    pr = sub.add_parser("resolve", help="Append a resolution record")
    pr.add_argument("--project", "-p", default=".")
    pr.add_argument("--principle", type=int, required=True)
    pr.add_argument("--verdict", choices=VERDICTS, required=True)
    pr.add_argument("--reason", required=True)
    pr.add_argument("--paths", nargs="+", required=True)
    pr.add_argument("--ref")
    pr.add_argument("--commit")
    pr.add_argument("--date", dest="day")

    pp = sub.add_parser("prior", help="Active prior resolutions touching given files")
    pp.add_argument("--project", "-p", default=".")
    pp.add_argument("--paths", nargs="+", required=True)
    pp.add_argument("--principle", type=int)
    pp.add_argument("--format", "-f", choices=["json"], default="json")

    args = parser.parse_args()
    if args.cmd == "list":
        print(cmd_list(args.project, args.format))
    elif args.cmd == "resolve":
        _cmd_resolve(args)
    elif args.cmd == "prior":
        recs, warns = active_prior(args.project, paths=args.paths, principle=args.principle)
        for w in warns:
            print(w, file=sys.stderr)
        print(json.dumps(recs, indent=2))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd skills/spec-manager/scripts && python test_principles.py`
Expected: PASS — `Ran 11 tests ... OK`.

- [ ] **Step 5: Verify the CLI end-to-end**

Run:
```bash
cd /tmp && rm -rf ptest && mkdir -p ptest/knowledge-base
printf '## Principles\n\n1. **Authenticated by default.** Endpoints need auth.\n' > ptest/knowledge-base/principles.md
S=/Users/main/Documents/projects/freya-devkit/skills/spec-manager/scripts
python "$S/principles.py" list --project ptest
python "$S/principles.py" resolve --project ptest --principle 1 --verdict refuted --reason "public health check" --paths app/api/health/route.ts
python "$S/principles.py" prior --project ptest --paths app/api/health/route.ts
```
Expected: the principle text prints; `resolve` prints the `.jsonl` path; `prior` prints a one-record JSON array with `"verdict": "refuted"`.

- [ ] **Step 6: Run the sibling suites to confirm no regressions**

Run: `cd skills/spec-manager/scripts && python test_verify_intent.py && python test_verify_links.py && python test_frontmatter.py && python test_intent.py`
Expected: all suites `OK`.

- [ ] **Step 7: Commit**

```bash
git add skills/spec-manager/scripts/principles.py skills/spec-manager/scripts/test_principles.py
git commit -m "feat(spec-manager): principles.py — list/resolve/prior helpers (G2)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Wrap-up principle checkpoint (SKILL.md)

**Files:**
- Modify: `skills/wrap-up/SKILL.md` (add Phase 3.5 step 5; add a staging-table row)

**Interfaces:**
- Consumes: `principles.py` (`list` / `prior` / `resolve`) from Task 1, via `"${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py"`; the `$BASE` variable already defined in Phase 3.5 step 3 (`BASE=$(git rev-parse HEAD~1)`).
- Produces: no code — the agent-run checkpoint procedure and its staging rule.

- [ ] **Step 1: Add Phase 3.5 step 5 (the principle checkpoint)**

In `skills/wrap-up/SKILL.md`, in "### Phase 3.5", **after** step 4 (the "Validate-on-hit (advisory — never blocks)" step) and **before** the `> Scope:` blockquote, insert:

````markdown
5. **Principle checkpoint (governance G2 — resolve-to-proceed).** After the
   deterministic blocks and validate-on-hit, check the change against the project's
   constitution. This is **model judgment**, so it is a *procedural* gate (honored by
   you, the wrap-up agent), not a script exit — but wrap-up **must not complete while a
   finding is unresolved.**

   a. **Load the constitution** (this is also the soft-injection point):
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" list --project .
      ```
      Empty output ⇒ no `principles.md` ⇒ **skip this step** (nothing to enforce).

   b. **Judge** `git diff "$BASE"` (the same `BASE` from step 3) against each
      principle: *does anything in this diff violate this rule?* Produce candidate
      findings — each naming the **principle number**, the **file(s)/hunk**, and
      **why**. Principles are few and project-wide, so check the whole list; no
      blast-radius scoping.

   c. **Triage each finding against prior resolutions.** For a finding's files:
      ```bash
      python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
        prior --project . --paths <finding files> --principle <N>
      ```
      If it returns a prior resolution, **re-validate it against the *current* hunk**
      (not just the file):
      - **Still clearly valid** — the flagged code *is* the same intentional thing the
        prior reason described, materially unchanged → **auto-clear** and log it:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
          resolve --project . --principle <N> --verdict auto-cleared \
          --reason "re-applied prior refutation; flagged code unchanged" --paths <files>
        ```
      - **Stale** — the code changed so the prior no longer maps → **retire** it and
        evaluate the finding fresh:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
          resolve --project . --principle <N> --verdict superseded \
          --reason "code changed; prior no longer applies" --paths <files>
        ```
      - **Now a real violation** — the prior reason no longer excuses it → **escalate**.

      **Auto-clear guardrails:** re-judge the current hunk against the *specific* prior
      reason, not the file (a *new/different* violation in a previously-refuted file
      **escalates**); **bias to escalate** on any ambiguity; a finding with **no prior
      always goes to the human.**

   d. **Resolve every escalated finding with the engineer** — and do not complete
      wrap-up until each is resolved as one of:
      - **Fix** — change the code to comply and re-judge (the code fix rides the code commit).
      - **Refute** (false positive):
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
          resolve --project . --principle <N> --verdict refuted \
          --reason "<why it is not actually a violation>" --paths <files> [--ref SPEC-NNN]
        ```
      - **Amend** — edit `knowledge-base/principles.md` (with a dated change-history
        line) **and** log it:
        ```bash
        python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" \
          resolve --project . --principle <N> --verdict amended \
          --reason "<how/why the principle changed>" --paths <files>
        ```

   "Ignore and push" is **not** a resolution. Principle findings are **not** carried
   forward as backlog debt — each is resolved in the wrap-up that raised it. On no git
   / no diff / any tooling error, note it and continue (advisory, fail-open).
````

- [ ] **Step 2: Add the staging-table row**

In `skills/wrap-up/SKILL.md`, in the "#### Behavior-aware staging rule" table, add a row (near the `INTENT-NNN.md` row added by G1):

```markdown
| `principle-resolutions.jsonl` + any `principles.md` amendment | **Artifacts** (commit 2) |
```

- [ ] **Step 3: Update the Phase 3.5 scope blockquote**

In `skills/wrap-up/SKILL.md`, the `> Scope:` blockquote at the end of Phase 3.5 currently ends with "Model-based contradiction checks remain a later track." Replace that final sentence with:

```markdown
> Model judgment enters here only as the **principle checkpoint** (G2, step 5:
> resolve-to-proceed, procedural — never a script hard-block); model-based
> *contradiction* checks (intent-vs-intent, G3) remain a later track.
```

- [ ] **Step 4: Verify the wiring text and confirm suites still green**

Run:
```bash
cd /Users/main/Documents/projects/freya-devkit
grep -c "principles.py" skills/wrap-up/SKILL.md
grep -n "Principle checkpoint (governance G2" skills/wrap-up/SKILL.md
grep -n "principle-resolutions.jsonl" skills/wrap-up/SKILL.md
(cd skills/spec-manager/scripts && python test_principles.py)
```
Expected: `principles.py` appears several times; the step-5 heading present; the staging row present; `test_principles.py` `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/wrap-up/SKILL.md
git commit -m "docs(wrap-up): principle checkpoint (G2) — resolve-to-proceed step in Phase 3.5

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Soft injection + `principles` command docs (spec-manager SKILL.md)

**Files:**
- Modify: `skills/spec-manager/SKILL.md` (Quick Reference row; `create` step; `scan` step; a short Principle-Enforcement pointer)

**Interfaces:**
- Consumes: `principles.py list` from Task 1.
- Produces: no code — documentation surfacing the constitution at design time.

- [ ] **Step 1: Add the Quick Reference row**

In `skills/spec-manager/SKILL.md`, in the Quick Reference table, after the `review` row, add:

```markdown
| `principles` | Print the project's principles (constitution) — used for soft injection & the G2 checkpoint |
```

- [ ] **Step 2: Inject principles into `create`**

In the `### /freya-devkit:spec-manager create <name>` section, insert a new first numbered step before the existing "Ask clarifying questions" step (renumber the rest):

````markdown
1. **Surface the constitution first** (soft injection — draft against the project's rules):
   ```bash
   python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" list --project .
   ```
   Keep these principles in view while authoring the spec/behaviors; a new spec should
   not propose intent that violates a principle. (Empty output ⇒ no constitution yet.)
````

- [ ] **Step 3: Inject principles into `scan`**

In the `### /freya-devkit:spec-manager scan` section, at the start of "**Phase 1: Coordinator Discovery**", add a leading bullet:

````markdown
- **Load the constitution first** (soft injection), so intent classification happens
  against the project's rules:
  ```bash
  python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/principles.py" list --project .
  ```
````

- [ ] **Step 4: Add a short Principle-Enforcement pointer**

In `skills/spec-manager/SKILL.md`, after the "Declared-Intent Records (governance G1)" section (added in G1), add:

````markdown
## Principle Enforcement (governance G2)

`knowledge-base/principles.md` is the project's constitution. It is enforced two ways
(vision §8), both of which G2 makes real:

- **Soft injection:** `principles.py list` surfaces it at design time (`create`, `scan`)
  and at wrap-up, so work happens with the rules in view.
- **Checkpoint (resolve-to-proceed):** at wrap-up, the change diff is judged against the
  principles; each finding is **fixed / refuted / amended** before wrap-up completes —
  "ignore and push" is not an option. This is model judgment (a *procedural* gate, never
  a script hard-block), with an LLM-first triage of prior resolutions (auto-clear /
  retire / escalate) recorded in the append-only `knowledge-base/principle-resolutions.jsonl`.
  See the wrap-up skill's Phase 3.5, step 5.

The `principles.py resolve` / `prior` subcommands back the checkpoint; `list` backs
soft injection.
````

- [ ] **Step 5: Verify and confirm suites green**

Run:
```bash
cd /Users/main/Documents/projects/freya-devkit
grep -c "principles.py" skills/spec-manager/SKILL.md
grep -n "Principle Enforcement (governance G2)" skills/spec-manager/SKILL.md
(cd skills/spec-manager/scripts && python test_principles.py)
```
Expected: `principles.py` appears in the create/scan/pointer edits; the G2 section present; tests `OK`.

- [ ] **Step 6: Commit**

```bash
git add skills/spec-manager/SKILL.md
git commit -m "docs(spec-manager): soft-inject principles into create/scan + G2 pointer

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Scope notes — clarifications from the spec

- **Retirement via `superseded` record, not a `status` field.** The spec (§4.1) illustrated a `status: active|superseded` field. A flippable field can't be honored append-only (flipping = rewriting a line), so the plan realizes the spec's *intent* with a later `superseded` **record** (latest-wins per `(principle, path)`). Same semantics, genuinely append-only. This is a faithful realization, not a scope cut.
- **Code-review pointer deferred (consistency).** The spec (§5/§8) listed a one-line principles pointer in the requesting-code-review rubric as in-scope. That rubric belongs to the third-party **superpowers** skill — the same "out of our reach" bucket the spec assigns to superpowers `brainstorming`/`writing-plans`. Editing a third-party skill's file would be overwritten on update and isn't ours to own, so the plan **defers** it to that same bucket rather than build it. The G2 pointer lives in *our* spec-manager SKILL.md (Task 3, step 4) instead. This is the one conscious deviation from the spec's in-scope list.

## Notes for the executor

- **DRY:** `principles.py` is self-contained (stdlib only); the checkpoint reuses wrap-up's existing `$BASE` and the ordinary `git diff` — no new diff helper.
- **Append-only is load-bearing:** never rewrite `principle-resolutions.jsonl`; retirement is a new `superseded` record. `test_superseded_record_retires_the_pair` and `test_append_is_append_only` guard this.
- **Tasks 2–3 are agent-procedure/doc wiring** — no unit tests beyond Task 1; verify by the grep checks and by keeping `test_principles.py` green. The checkpoint's judgment/triage is validated in the **final dogfood**, not a unit test.
- Every script is invoked in production via `${CLAUDE_PLUGIN_ROOT}`; keep the `sys.path.insert(0, dirname(__file__))` shim in the test so imports work regardless of cwd.
