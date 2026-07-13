# The Shared Resolution-Log Refactor

*Research brief for the Behavior Layer explainer. Audience: an engineer who has
never seen this feature. Everything here is copied verbatim from source and
verified against the code / tests on branch `feat/behavior-layer`.*

---

## 1. What this refactor is (one sentence)

Three governance scripts — `principles.py` (called **G2**), `contradictions.py`
(**G3**), and `drift.py` (**P4b**) — each carried a **near-verbatim copy** of the
same append-only "resolution log" logic. This refactor extracts that logic into a
single new module, `resolution_log.py`, and rewrites the three scripts to
**delegate** to it, with **zero public-behavior change**.

It is explicitly a **behavior-preserving refactor** — "no new capability, no
public-API change." Nothing a user sees changes: not the CLI, not the record
schema, not the file paths, not the verdict names.

All four files live in:
`/Users/main/Documents/projects/freya-devkit/skills/spec-manager/scripts/`

---

## 2. What a "resolution log" is (background for the newcomer)

Each of the three governance checks answers a yes/no *judgment* question during
wrap-up, and when a human resolves that judgment, the outcome is **appended** to a
JSONL file (one JSON object per line). These files are **append-only** — you never
mutate or delete a line. Retirement of an old resolution is expressed by appending
a *later* record with `verdict: "superseded"` (this is the "latest-wins" rule
described below).

The three checks and their log files:

| Sub-project | Module | Question it resolves | Log file (`RESOLUTIONS_RELPATH`) |
|---|---|---|---|
| **G2** | `principles.py` | Does the diff violate a stated principle? | `knowledge-base/principle-resolutions.jsonl` |
| **G3** | `contradictions.py` | Does a changed spec/ADR contradict a higher-authority intent? | `knowledge-base/contradiction-resolutions.jsonl` |
| **P4b** | `drift.py` | Does changed code contradict *declarative* intent (a spec's `intentional_decisions` or an accepted ADR)? | `knowledge-base/drift-resolutions.jsonl` |

Each module's source comment stresses that the script does only the
**deterministic parse / append / lookup** — the actual *judgment* and *triage*
(auto-clear / retire / escalate) is agent work in the SKILL.md, not in Python.

Each module keeps three log-related functions:

- `append_resolution(project, record)` — append one resolution record.
- `_load_records(project)` — load all records (with warnings for bad lines).
- `active_prior(...)` — return the currently-active resolutions (latest-wins,
  superseded dropped), filtered to the caller's query. This is the recurrence
  handling: the wrap-up agent re-validates these against the current diff.

---

## 3. The DRY story — *why* this refactor exists (the important part)

This is the design rationale a newcomer most needs, taken verbatim from the design
doc (`docs/superpowers/specs/2026-07-01-shared-resolution-log-design.md`):

> Governance sub-projects G2 (`principles.py`), G3 (`contradictions.py`), and P4b
> (`drift.py`) each carry a **near-verbatim copy** of the append-only
> resolution-log logic (`append_resolution` / `_load_records` / `active_prior`).
> This was a **deliberate, spec-approved decision at 2 copies** (G3: "we
> deliberately did not extract a shared module, to avoid churning G2's shipped
> code"). **At 3 copies the DRY case wins**; parking-lot logged it as its own
> refactor sub-project. This is that sub-project.

The narrative arc, in plain terms:

1. **1 copy** — G2 wrote the logic. Fine.
2. **2 copies** — G3 needed the same logic. The team **deliberately chose to
   copy** rather than extract, *specifically to avoid churning G2's already-shipped
   code*. This was a conscious, spec-approved tradeoff — duplication was cheaper
   than the risk/blast-radius of touching working code.
3. **3 copies** — P4b needed it too. **Now the DRY case wins.** The "rule of three"
   tipping point. The duplication was logged in a parking lot as its own refactor
   sub-project, deferred until it was worth doing — and this is that deferred
   sub-project being cashed in.

This is a good story because it shows duplication is not always a bug: two copies
was the *right* call at the time, made explicitly. The refactor only happens when
the third copy tips the cost/benefit — and even then it is done under a strict
safety net (Section 6) so it can't regress the shipped behavior.

The design doc classifies its dependency as: **"the three shipped modules and their
test suites (the regression net). No functional dependency."**

---

## 4. The duplication, precisely — two variants, not one

This is the subtle technical point. `append_resolution` and `_load_records` were
**verbatim** across all three modules — only the module's `RESOLUTIONS_RELPATH`
constant differed. But `active_prior` had **two different shapes**:

### Variant A — path-exploding, key `(field, path)` — used by G2 and P4b

A single resolution record carries a **list** of `paths`, and the record is
"exploded" into one key per path. The key is `(field, path)`, where `field` is
the record's `principle` (G2) or `item` (P4b).

- **G2** `principles.py`: `active_prior(project, paths=None, principle=None)`,
  key `(principle, path)`.
- **P4b** `drift.py`: `active_prior(project, item, paths=None)`,
  key `(item, path)`.

### Variant B — single key `(spec, against)` — used by G3

Each record has exactly **one** `against` value (no `paths` list, no explosion).
The key is `(spec, against)`.

- **G3** `contradictions.py`: `active_prior(project, spec, against=None)`,
  key `(spec, against)`.

**Despite the two shapes, all three share the same core algorithm** (verbatim from
the design doc §2):

> keep the latest (append-order) record per key, drop keys whose latest verdict is
> `superseded`, filter to the caller's query, de-dupe a multi-key record to one
> entry by append index, and thread `(records, warnings)`.

The refactor's whole trick is: this one algorithm is **parameterized by two
callbacks** so both shapes fall out of it. See Section 5.

---

## 5. The new module: `resolution_log.py`

A small **stdlib-only** module (Python 3.12; `json` + `pathlib`), **no class** —
"matches the codebase style." Three public functions.

### 5.1 Signatures (verbatim)

```python
def append(path, record):
    """Append one JSONL line (sorted keys) to `path`, creating parents. Returns str(path)."""

def load(path, label=None):
    """(records, warnings) — parsed JSONL lines in append order; a malformed line
    is skipped with a warning naming the line number. Missing file → ([], [])."""

def active(records, keys_of, want=None):
    """Latest-active records ..."""
```

> **Doc-vs-code note:** the *design doc* §3 shows `load(path)` and
> `active(records, keys_of, want)`. The *plan* and the **actual shipped code** use
> `load(path, label=None)` and `active(records, keys_of, want=None)`. The `label`
> parameter is the real, shipped signature (see 5.3 for why it matters).

### 5.2 `active` — the parameterized core (verbatim from the shipped file)

```python
def active(records, keys_of, want=None):
    latest = {}  # key -> (append_idx, record)
    for idx, rec in enumerate(records):
        for k in keys_of(rec):
            latest[k] = (idx, rec)
    picked = {}  # append_idx -> record (de-dupe multi-key records)
    for k, (idx, rec) in latest.items():
        if rec.get("verdict") == "superseded":
            continue
        if want is not None and not want(k):
            continue
        picked[idx] = rec
    return [picked[i] for i in sorted(picked)]
```

How the algorithm maps to the four documented behaviors:

- **Latest-wins per key** — the first loop overwrites `latest[k]` in append order,
  so the *last* record covering key `k` wins.
- **`keys_of` explodes a record into keys** — this is the parameterization. A
  path-exploding module returns one key per path; a single-key module returns a
  one-element list. Same loop, both shapes.
- **Drop `superseded`** — `if rec.get("verdict") == "superseded": continue`.
- **`want` is the caller's query filter** — `if want is not None and not want(k)`;
  default (`want=None`) keeps everything.
- **De-dupe a multi-key record to one entry by append index** — `picked` is keyed
  by `idx` (the append index), so a record that covers several keys collapses to a
  single entry. `sorted(picked)` returns survivors in append order.

### 5.3 `append` and `load` (verbatim from the shipped file)

```python
def append(path, record):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, sort_keys=True) + "\n")
    return str(path)


def load(path, label=None):
    path = Path(path)
    label = label or path.name
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
            warnings.append(f"skipped malformed line {i} in {label}")
    return records, warnings
```

Key details:

- `append` writes `json.dumps(record, sort_keys=True)` (sorted keys) plus a
  newline, `mkdir(parents=True, exist_ok=True)` first, and returns `str(path)`.
- `load` returns `([], [])` for a **missing file**, **skips blank lines**, and
  **skips a malformed line** with the warning `f"skipped malformed line {i} in {label}"`.
- **Why `label` exists (behavior preservation):** the warning string had to stay
  *byte-identical* to what each module produced before. Each module passes its own
  `RESOLUTIONS_RELPATH` as `label`, so the warning names the project-relative path
  (e.g. `knowledge-base/principle-resolutions.jsonl`), **not** the bare file name.
  The plan states this explicitly: *"`load(path, label)` uses `label` for the
  'skipped malformed line …' message, and each module passes its
  `RESOLUTIONS_RELPATH` so the string is identical to today."* The default
  (`label or path.name`) covers the case where no label is passed (used by the
  helper's own tests).

---

## 6. How the three modules now delegate (`keys_of` + `want`)

Every module keeps its **exact public surface** — `RESOLUTIONS_RELPATH`,
`VERDICTS`, the signatures of `append_resolution` / `_load_records` /
`active_prior`, its record schema, and its CLI. Only the *bodies* change. All
three now do the same two trivial delegations:

```python
def append_resolution(project, record):
    return resolution_log.append(_resolutions_path(project), record)


def _load_records(project):
    return resolution_log.load(_resolutions_path(project), RESOLUTIONS_RELPATH)
```

And each builds its own `keys_of` + `want` closures for `active_prior`
(all verbatim from the shipped modules):

### G2 — `principles.py` (path-exploding, `(principle, path)`)

```python
def active_prior(project, paths=None, principle=None):
    """Latest-active resolution per (principle, path)."""
    records, warnings = _load_records(project)
    want_paths = set(paths) if paths else None
    keys_of = lambda r: [(r.get("principle"), p) for p in (r.get("paths") or [])]
    want = lambda k: (want_paths is None or k[1] in want_paths) and \
                     (principle is None or k[0] == principle)
    return resolution_log.active(records, keys_of, want), warnings
```

### P4b — `drift.py` (path-exploding, `(item, path)`)

```python
def active_prior(project, item, paths=None):
    """Latest-active resolution per (item, path) for the given item."""
    records, warnings = _load_records(project)
    want_paths = set(paths) if paths else None
    keys_of = lambda r: [(r.get("item"), p) for p in (r.get("paths") or [])]
    want = lambda k: k[0] == item and (want_paths is None or k[1] in want_paths)
    return resolution_log.active(records, keys_of, want), warnings
```

### G3 — `contradictions.py` (single-key, `(spec, against)`)

```python
def active_prior(project, spec, against=None):
    """Latest-active resolution per (spec, against) for the given spec."""
    records, warnings = _load_records(project)
    keys_of = lambda r: [(r.get("spec"), r.get("against"))]
    want = lambda k: k[0] == spec and (against is None or k[1] == against)
    return resolution_log.active(records, keys_of, want), warnings
```

Note the differences that survive into the closures:
- G2/P4b `keys_of` **explodes over `paths`**; G3's returns a **one-element list**.
- G2's `principle` filter is optional (`principle is None or …`); P4b **always**
  requires `k[0] == item`; G3 **always** requires `k[0] == spec`.

### Import style

Each module inserts the script dir on `sys.path` then imports the helper:

```python
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import resolution_log  # noqa: E402
```

Per the plan, `principles.py` did *not* previously manipulate `sys.path` (it had to
gain `import os` + the insert), whereas `contradictions.py` and `drift.py` already
had the `sys.path.insert(...)` block plus sibling imports, so they only added the
one `import resolution_log` line.

---

## 7. The safety net — behavior preservation is *mechanically* guaranteed

This is the second pillar of the story. The refactor is proven safe not by
argument but by an existing regression net:

> **The three existing suites are the regression net** — they must pass
> **unchanged** (no edits to `test_principles.py` / `test_contradictions.py` /
> `test_drift.py`). Any needed edit there is a signal the refactor changed behavior
> — stop and fix the refactor, not the test.

The plan makes this a hard global constraint: the three test files must stay
**byte-unchanged** (`git diff --stat … expect: no output`) and still pass. The
design doc's Open Questions section says there are **none**, because *"The refactor
is bounded by 'existing suites pass unchanged,' which mechanically guarantees
behavior preservation; the only new surface is the helper and its own tests."*

A brand-new focused suite, `test_resolution_log.py`, proves the helper directly and
covers **both `keys_of` shapes**:
- append is append-only; creates parents; returns the path
- `load` on a missing file → `([], [])`; skips a malformed line with a
  **label**-named warning (the test asserts the label string appears, "not
  path.name"); ignores blank lines
- `active` with a path-exploding `keys_of` (G2/P4b shape): latest-wins per
  `(field, path)`, drops `superseded`, de-dupes a multi-path record, honors `want`
- `active` with a single-key `keys_of` (G3 shape): latest-wins per `(a, b)`,
  honors `want`

### Verified numbers (I ran these on branch `feat/behavior-layer`)

| Suite | Test methods | Result |
|---|---|---|
| `test_resolution_log.py` | **11** | OK |
| `test_principles.py` | **11** | OK |
| `test_contradictions.py` | **16** | OK |
| `test_drift.py` | **19** | OK |

I also confirmed the acceptance criterion *"the duplication is gone"*: `grep -c
'latest\['` returns **0** for each of `principles.py`, `contradictions.py`,
`drift.py` — none of them still contains the local latest-wins loop; it lives only
in `resolution_log.py`.

The design/plan's acceptance criteria state the same counts verbatim:
`test_principles.py` (11), `test_contradictions.py` (16), `test_drift.py` (19) all
pass with no edits; `test_resolution_log.py` "Expected: PASS (11 tests)."

---

## 8. Scope — what is explicitly *out*

From design §6 (verbatim intent):

- **In scope:** `resolution_log.py` (`append`/`load`/`active`); refactor the three
  modules to delegate while preserving public APIs, CLIs, record schemas,
  RELPATHs, and `VERDICTS`; `test_resolution_log.py`.
- **Out of scope:** any change to record schemas, keys, verdicts, or CLI flags;
  **unifying the three `active_prior` *signatures*** (they stay module-specific —
  callers depend on them); the resolution *judgment/triage* prose in the SKILLs;
  and **the security findings log (a different shape, not part of this pattern)**.

That last exclusion is worth calling out for the explainer: the security-findings
log looks superficially similar but has a different shape, so it was deliberately
left alone — the refactor unifies *only* the three governance resolution logs.

All three modules share the identical `VERDICTS` tuple:
`("refuted", "amended", "auto-cleared", "superseded")`.

---

## 9. One concrete worked example (path-exploding, G2/P4b shape)

Say the drift log (`drift-resolutions.jsonl`) contains, in append order:

1. `{"item": "SPEC-001", "paths": ["a.ts", "b.ts"], "verdict": "refuted", ...}`
2. `{"item": "SPEC-001", "paths": ["a.ts"], "verdict": "superseded", ...}`

`keys_of` explodes record 1 into keys `("SPEC-001","a.ts")` and
`("SPEC-001","b.ts")`, and record 2 into `("SPEC-001","a.ts")`.

- `latest[("SPEC-001","a.ts")]` = record 2 (later wins) → dropped, verdict is
  `superseded`.
- `latest[("SPEC-001","b.ts")]` = record 1 → kept.

Result: record 1 survives (via its `b.ts` key), **de-duped to one entry** even
though it originally covered two keys — because `picked` is keyed by append index.
`a.ts` is retired. That is latest-wins + drop-superseded + dedupe in one pass.

*(Placeholder identifiers `SPEC-001`, `a.ts`, `b.ts` are generic — the real logs
live under a project's `knowledge-base/` and are not reproduced here.)*

---

## 10. Files to cite in the explainer

- New helper: `skills/spec-manager/scripts/resolution_log.py`
- New tests: `skills/spec-manager/scripts/test_resolution_log.py`
- Refactored (delegating) modules: `skills/spec-manager/scripts/principles.py`,
  `.../contradictions.py`, `.../drift.py`
- Regression net (byte-unchanged): `.../test_principles.py`,
  `.../test_contradictions.py`, `.../test_drift.py`
- Design: `docs/superpowers/specs/2026-07-01-shared-resolution-log-design.md`
- Plan: `docs/superpowers/plans/2026-07-01-shared-resolution-log.md`
