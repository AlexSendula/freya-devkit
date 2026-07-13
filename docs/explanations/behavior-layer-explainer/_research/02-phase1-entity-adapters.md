# Phase 1 — Behavior entity, lifecycle & adapters (research brief)

**Audience:** an engineer who has never seen the Behavior Layer and is sitting on the
original `main`. This brief is grounded verbatim in the Phase-1 design docs and the
shipped `spec-manager` scripts on branch `feat/behavior-layer`.

**Sources read in full:**
- `docs/design/behavior-layer/01-phase-1.md` (the spec — the "what")
- `docs/design/behavior-layer/01b-phase-1-plan.md` (the plan — order, files, verification)
- `skills/spec-manager/scripts/frontmatter.py`
- `skills/spec-manager/scripts/adapters.py`
- `skills/spec-manager/scripts/verify_links.py`
- `skills/spec-manager/scripts/search_specs.py`
- `skills/spec-manager/SKILL.md`

---

## 1. The one-paragraph story

Before this phase, a spec was prose plus an inert "Acceptance Criteria" checkbox list.
Phase 1 makes a spec able to **declare its intended behavior as first-class `Behavior`
records** — each with a stable `BEH-NNN` id, a lifecycle `state`, and an `adapter` +
`locator` linking it to an executable test (Gherkin you author, *or* an existing native
test you link). Those links are checked **deterministically** (no LLM, no test execution)
by `verify_links.py`, and only `accepted` behaviors block on failure. Critically, the
codebase *cannot* mint authoritative behaviors on its own: `scan` produces a **review
queue of `proposed` candidates** that never touch the code tree — a human accepting a
candidate is the only thing that promotes it and lets a scaffold/link land as code.
The phase explicitly excludes the behavior graph, coverage fingerprints, and any
model-based checks (those are Phases 2–3).

Quote (`01-phase-1.md §1`):
> "After Phase 1, a feature spec can **declare its intended behavior as first-class
> `Behavior` records**, each with a **stable id**, a **lifecycle state**, and an
> **adapter** linking it to an executable test — authored as Gherkin *or* linked to an
> existing native test. Links are checked deterministically, and *accepted* behaviors are
> run at wrap-up, where **only deterministic failures block**."

---

## 2. The `Behavior` record schema (as actually defined in `frontmatter.py`)

A behavior lives inside a spec's frontmatter under `behaviors:` — a list of records.
`validate_behaviors(behaviors, spec_id=None)` in `frontmatter.py` is the authority for
the shape. Fields:

| Field | Required? | Type / rule (verbatim from code) |
|---|---|---|
| `behavior_id` | **required** | string matching `BEH-NNN`. Regex: `_BEH_ID_RE = re.compile(r"BEH-\d{3,}")`. Missing → `"missing required field: behavior_id"`; bad shape → `"behavior_id '{bid}' must match BEH-NNN"`. Duplicate **within the same spec** → `"duplicate behavior_id '{bid}' (already at {...})"` |
| `title` | **required** | non-empty string. Else `"missing or non-string title"` |
| `state` | **required** | one of `BEHAVIOR_STATES = ("proposed", "confirmed", "accepted", "quarantined", "deprecated")`. Else `"state '{state}' must be one of ..."` |
| `adapter` | required **only when `state == "accepted"`** | one of `KNOWN_ADAPTERS`. When present in *any* state it is still checked (typo fails loud) |
| `locator` | required **only when `state == "accepted"` and `adapter != "manual"`** | string. Else, when present, must be a string |
| `level` | optional | when present, one of `KNOWN_LEVELS = ("unit", "component", "integration", "e2e")`. It is "the runner's dispatch key, so a typo would silently route a behavior to the wrong (or no) coverage path" |
| `entry` | optional | when present, a string ("a project-relative path"). Used by integration behaviors — the route/handler its test drives |
| `spec_id` | optional | inherited from the parent spec; if present must equal the parent's `id`, else `"spec_id '{sid}' does not match parent spec '{spec_id}'"` |

`KNOWN_ADAPTERS` (verbatim, grouped by comment):
```python
KNOWN_ADAPTERS = (
    "cucumber", "behave", "pytest-bdd",          # Gherkin family
    "jest", "vitest", "mocha", "jasmine",         # JS unit
    "playwright", "cypress",                      # JS e2e
    "pytest", "unittest",                         # Python
    "manual",                                     # human-verified, no runner
)
```

`SCHEMA_VERSION = 1`. The spec schema itself (`SPEC_SCHEMA`) requires `id`, `title`,
`category`, `status` (all `str`); optional typed fields are `tags` (list),
`certainty` (int), `created`/`updated` (str), `related_code` (list),
`intentional_decisions` (list), `behaviors` (list).

**Design nuance — why `adapter`/`locator` are conditional.** From the code comment:
> "Only `accepted` asserts a real, linked, passing test, so adapter and locator are
> *required* only for accepted. Pre-test states (`proposed`, `confirmed`) may omit them —
> intent confirmed, test owed (design 03 §3). When either is present in any state it is
> still validated, so a typo fails loud rather than silently routing to the wrong runner."

Example record (from `SKILL.md` "Spec File Format", genericized-safe — passkey login is
the design doc's own illustrative example, not proprietary content):
```yaml
behaviors:
  - behavior_id: BEH-007
    title: Successful passkey login
    state: accepted            # proposed | confirmed | accepted | quarantined | deprecated
    adapter: cucumber          # cucumber | behave | pytest-bdd | jest | playwright | ... | manual
    locator: features/auth/passkey-login.feature#successful-passkey-login
```

---

## 3. The lifecycle & which state is authoritative

The **spec doc (`01-phase-1.md §3`)** originally defined a four-state lifecycle:
`proposed → accepted → quarantined → deprecated`. The table there:

| State | Meaning | Authoritative? |
|---|---|---|
| `proposed` | A candidate (e.g. from `scan` inference). Intent not yet approved by a human. | No |
| `accepted` | Approved as intended behavior; its test is the safety net. | **Yes** |
| `quarantined` | Test failing for infra reasons (flaky / fixture / env), temporarily out of the authoritative set. | No |
| `deprecated` | Behavior intentionally retired. | No |

**A fifth state, `confirmed`, was added later** (git: commit `ea2fe0f`
"feat(spec-manager): add confirmed lifecycle state + state-aware validation", which
lands *after* `aed2046` that introduced the original entity). The shipped code
(`frontmatter.py`) is the current truth and lists **five** states in order:
`proposed → confirmed → accepted (+ quarantined / deprecated)`.

From the `frontmatter.py` comment:
> "`confirmed` = a human confirmed the intent but the test is still owed (design 03 §3):
> it carries intent (and may declare an `entry`) but asserts no test, so adapter/locator
> are not required for it."

**Authoritative = `accepted` only.** The spec is emphatic:
> "`state` replaces the earlier `behavior_status` (`none/scaffolded/authored`), which
> conflated 'text exists' with 'approved as intent.' **Only `accepted` behaviors block on
> failure.**" (`01-phase-1.md §3`)

`SKILL.md` reframes the certainty vs. state relationship: `certainty` measures confidence
in an *inferred, not-yet-human-confirmed* spec (and backs declarative decisions), whereas
executable-behavior intent is carried by the lifecycle `state` where
"`confirmed` = a human confirmed the intent (test owed)" and
"`accepted` = confirmed intent that a real linked test verifies."

(Note: there is a *separate*, parallel closed set for ADRs added in a later phase —
`ADR_STATES = ("proposed", "accepted", "superseded", "deprecated")` — not part of the
behavior lifecycle; mentioned only so a reader doesn't confuse the two.)

---

## 4. The two adapters (as implemented in `adapters.py`)

`adapters.py` docstring: *"Behavior adapters: link a Behavior record to the test that
verifies it. Two adapters in Phase 1."* The module "only knows the *shape* of a scaffold
and how to read a locator; it writes no files itself."

### 4a. Gherkin scaffold (`cucumber` / `behave` / `pytest-bdd`)

`GHERKIN_ADAPTERS = ("cucumber", "behave", "pytest-bdd")`. The default for **new,
user-visible** behavior. spec-manager writes a **skeleton `.feature`** — required tags +
a `TODO(scaffold)` marker, but **no real steps and no step definitions** (authoring real
steps is human forward-design work).

The marker constant: `SCAFFOLD_MARKER = "TODO(scaffold)"`.

Key functions:
- `slugify(text)` → `"Successful passkey login"` becomes `"successful-passkey-login"`.
- `feature_locator(category, feature_name, scenario_title)` → the conventional locator
  `features/<cat>/<name>.feature#<scenario-slug>`.
- `render_scenario_scaffold(behavior_id, title)` — one tagged `Scenario` with the marker
  and placeholder `Given/When/Then` lines.
- `render_feature_scaffold(spec_id, feature_title, spec_relpath, behaviors)` — the full
  file: the `Feature` carries the `@SPEC-NNN` tag; each `Scenario` carries its `@BEH-NNN`
  tag. "The tags are the reverse links and are required."

CLI entry point (verbatim from `SKILL.md`):
```bash
python "${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/adapters.py" gherkin-scaffold \
  --spec-id SPEC-012 --title "Passkey Login" \
  --spec-path knowledge-base/specs/auth/SPEC-012-passkey-login.md \
  --behavior "BEH-007:Successful passkey login"
```
`--behavior` is repeatable (`action="append"`) and parsed by `_parse_behavior_arg` as
`BEH-NNN:Title` (it raises `argparse.ArgumentTypeError` on a missing colon/title). The
subcommand writes the rendered feature to stdout — it does not write the file itself.

The produced file (from `SKILL.md`), with the `TODO(scaffold)` marker load-bearing:
```gherkin
@SPEC-012
Feature: Passkey Login
  # Intent and rationale live in knowledge-base/specs/auth/SPEC-012-passkey-login.md

  @BEH-007
  Scenario: Successful passkey login
    # TODO(scaffold): replace with real steps. Step definitions are not generated.
    Given <initial state>
    When <action>
    Then <expected outcome>
```

The locator for this behavior is `features/<category>/<name>.feature#<scenario-slug>`.
A scaffold **keeps its `TODO(scaffold)` marker until a human fills in real steps**;
`verify` treats an `accepted` behavior that still carries the marker as an error (§6).

### 4b. Native test link (`jest`, `playwright`, `pytest`, …)

Links an **existing** test by `locator`. **No file is written, nothing is rewritten** —
"this keeps adoption cheap for projects that already have tests." You set `adapter` to the
runner and `locator` to `path/to/test#case` (or `path::node` for pytest).

`parse_locator(locator)` splits a locator into `(path, fragment)` and supports **both**
forms:
- Gherkin `path#scenario-slug` (splits on `#`)
- pytest-style `path::node` (splits on `::`)
- no fragment → returns `(locator, None)`

So the difference between the two adapters: **Gherkin = author a tagged scaffold in the
code tree (reverse link is the `@SPEC`/`@BEH` tags); Native = point a locator at a test
that already exists (the locator *is* the link — no reverse tag required).**

---

## 5. The `@SPEC-NNN` / `@BEH-NNN` tag round-trip

The tags are the **reverse link** from test → spec/behavior. Forward link is the spec's
`behaviors[].locator` → test file. Together they must round-trip.

Tag machinery in `adapters.py`:
- `_TAG_RE = re.compile(r"@([A-Za-z]+-\d+)")`
- `extract_tags(text, prefix)` → tags starting with `prefix + "-"`.
- `extract_spec_tags(text)` → `SPEC-*` tags; `extract_behavior_tags(text)` → `BEH-*` tags.
- `has_scaffold_marker(text)` → `True` while `TODO(scaffold)` is present.
- `scenario_blocks(text)` → splits a feature into **per-`Scenario` blocks**, each with the
  contiguous tag lines directly above the header, returning `[(behavior_tags:set,
  block_text)]`. This is what lets the scaffold-marker check be **scoped to a single
  behavior's scenario** — an authored `accepted` scenario in a file that *also* contains a
  separate `proposed` scaffold must not be flagged by the *other* scenario's marker.
- `scenario_block_for(text, behavior_id)` → the block tagged with `@behavior_id`, or `None`.

(The most recent commit on the branch — `54d6eb3 fix(spec-manager): scope the
accepted-but-scaffold check to one scenario` — is exactly this scoping fix.)

---

## 6. Tier-1 deterministic link-integrity checks (`verify_links.py`)

`verify_links.py` docstring: *"Tier-1 deterministic link-integrity checks for behaviors.
No LLM, no test execution, no contradiction analysis (that is Tier-2 / Phase 3). These
checks are cheap and certain — they are the ones allowed to **hard-block** at wrap-up."*

Entry point `verify(specs_dir=None)` returns a list of error dicts, each shaped by
`_err(spec_id, behavior_id, kind, message)` → `{"spec_id", "behavior_id", "kind",
"message"}`. `main()` prints text or `--format json` and **`sys.exit(1 if errors else
0)`** so wrap-up can gate on the exit code.

Path model: locators are resolved relative to the **project root** (the parent of
`knowledge-base/`), derived by `_project_root(specs_dir)`.

### The exact check set (by `kind` string, verbatim from the code)

**Identity:**
- `duplicate-id` — a `BEH-NNN` reused **across specs**. A global `beh_index` is built; a
  second occurrence emits `"behavior_id {bid} reused (already in {...})"`. (Within one
  spec, the same duplicate is caught earlier by `validate_behaviors`.)

**Forward (spec → test):**
- `entry-unresolved` — a declared `entry` path that does not exist under the project root
  (`"entry path does not exist: {entry}"`). Checked independently of the adapter, because a
  non-resolving entry would yield a "silently-degraded fingerprint at run time."
- `manual` adapter behaviors are **skipped** for locator resolution (`if adapter ==
  "manual": continue`).
- `missing-locator` — only when `state == "accepted"` and there is no locator:
  `"{bid} has adapter '{adapter}' but no locator"`. For `proposed`/`confirmed`, a missing
  locator is **not** an error (intent confirmed, test owed).
- `locator-unresolved` — a present locator whose path does not exist:
  `"locator path does not exist: {rel_path}"` (resolved via `parse_locator`, so the
  `#`/`::` fragment is stripped first). A present locator is resolved **whatever the
  state**, so a typo fails loud even on a proposed behavior.
- For Gherkin adapters (`adapter in GHERKIN_ADAPTERS`), the feature file is read and:
  - `missing-reverse-tag` — `@BEH-NNN` tag absent from the feature: `"@{bid} tag not found
    in {rel_path}"`.
  - `missing-spec-tag` — `@SPEC-NNN` tag absent: `"@{s.id} tag not found in {rel_path}"`.
  - `accepted-but-scaffold` — **only when `state == "accepted"`**: the behavior's *own*
    scenario block still has the `TODO(scaffold)` marker: `"accepted behavior still has
    TODO(scaffold) in {rel_path}"`. Scoped via `scenario_block_for(text, bid)` so a sibling
    proposed scaffold in the same file doesn't taint it.

**Reverse (test → spec/behavior), over every `*.feature` file under the root:**
- `orphan-spec-tag` — a `@SPEC` tag in a feature that matches no spec id: `"@{tag} in
  {rel} has no matching spec"`.
- `orphan-behavior-tag` — a `@BEH` tag in a feature that matches no behavior in the global
  index: `"@{tag} in {rel} has no matching behavior"`.

Feature-file walk skips
`SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", "knowledge-base",
"dist", "build"}`.

CLI:
```bash
python verify_links.py
python verify_links.py --dir knowledge-base/specs --format json
```
Clean output: `"OK — all behavior links pass Tier-1 integrity checks."`
Failing output: `"{N} link-integrity error(s):"` then one `[kind] spec/behavior: message`
line each.

> The five checks the task brief named map to these `kind`s: **unresolved locator** =
> `locator-unresolved`; **missing reverse tag** = `missing-reverse-tag` (plus
> `missing-spec-tag`); **accepted-but-scaffold** = `accepted-but-scaffold`; **duplicate
> BEH-NNN** = `duplicate-id`; **orphan tag** = `orphan-spec-tag` / `orphan-behavior-tag`.
> The code additionally ships `entry-unresolved` and `missing-locator`.

`spec-manager verify` (SKILL.md) runs this first, as a "deterministic hard-block."

---

## 7. Intent classification → a review queue (never staged scaffolds)

This is the central safety property of the phase. `scan` (and `create`) classify each
piece of intent with this decision tree (`01-phase-1.md §5`, mirrored in `SKILL.md`
Phase 2.5):

```
Is it observable behavior expressible as a test?
  ├─ Yes → propose a Behavior (state: proposed)
  │         ├─ new user-visible        → recommend a Gherkin scaffold
  │         └─ already covered by a test → recommend linking the native test
  └─ No  → declarative
            ├─ cheaply guarded by a (often negative) scenario? → recommend promotion
            └─ Feature-local → Intentional Design Decisions (inline)
               Cross-cutting → note for knowledge-base/decisions/ (ADR, deferred)
```

**The hard rules for `scan` (verbatim, `SKILL.md`):**
- "`scan` produces a **review queue of `proposed` candidates** — never `accepted`, and
  **never files written into the code tree.**"
- "A candidate becomes `accepted` — and only then does its scaffold/link enter the code
  tree (via the adapter) — when a **human accepts it**."
- "Classification is **interactive for low certainty**: reuse the one-question-at-a-time
  `review` flow and the existing certainty thresholds."

**Why (the rationale that makes this understandable):**
> "Intent cannot be reliably inferred from code; auto-generating authoritative-looking
> scaffolds from the implementation would reintroduce the 'tests mirror code' problem the
> behavior layer exists to fix." (`SKILL.md`)

So the flow is: `scan` → `proposed` records live *in the spec frontmatter* under
`knowledge-base/specs/`, carrying certainty scores → a human reviews and accepts → **only
then** does a Gherkin scaffold or native link enter the code tree.

**Two-commit staging follows lifecycle state, not location** (`01-phase-1.md §8`):

| Artifact | Commit |
|---|---|
| `proposed` behaviors / unaccepted scaffolds | **Artifacts** (commit 2) — intent under review |
| `accepted` behaviors' tests (`.feature` + steps, or the native test) | **Code** (commit 1) — executable, real |
| `SPEC-*.md`, `principles.md` | **Artifacts** (commit 2) |

> "A scaffold's commit class follows its **lifecycle state**, not its location: a
> `proposed`/`TODO` scaffold is an artifact even though it sits in the code tree; it joins
> the code commit only once `accepted` and executable."

---

## 8. Why the hand-rolled parser was replaced by a scoped, fail-loud parser

This is a **substrate prerequisite** — it had to land *before* the schema grew
(`01-phase-1.md §7`, `01b-phase-1-plan.md`). The old parser was
`search_specs.py: parse_frontmatter` — a regex hand-roll that **silently discarded
inline-array fields**: `tags: [a, b]` was parsed as a string and then dropped.

> "Extending the schema on top of it would silently corrupt the new `behaviors` data, so
> the parser is replaced and proven *before* the schema grows." (`01b-phase-1-plan.md`)

The replacement (`frontmatter.py`) is deliberately **not a full YAML engine** — the plugin
is stdlib-only / zero-install. It is a *scoped* parser for the exact, versioned,
model-authored grammar that **fails loud** — raising `FrontmatterError` on anything outside
the grammar rather than silently dropping it.

Supported grammar (from the docstring):
- `key: value` scalars (bare integers coerced to int; dates stay strings)
- single/double-quoted scalar strings
- inline flow arrays: `tags: [authentication, security, webauthn]`
- block sequences (`- item`)
- **one level** of list-of-mappings (for `behaviors:`)
- `#` line comments and trailing inline comments — but a `#` is a comment **only when
  preceded by whitespace**, so a locator like `foo.feature#scenario` keeps its `#`
  (`_strip_inline_comment`)

Anything else raises `FrontmatterError` (a `ValueError` subclass): tab indentation
(`"tab indentation is not allowed"`), an unterminated flow array, a missing closing `---`
(`"unterminated frontmatter: missing closing '---'"`), an orphan/malformed line
(`"could not parse frontmatter near: ..."`), etc.

Public API:
- `parse_frontmatter(text) -> (dict, body)` — no leading `---` fence returns `({}, text)`.
- `validate(frontmatter, schema_version=SCHEMA_VERSION, schema=None) -> list[error]` —
  required-field + type checks against the versioned schema; **unknown fields are preserved
  and never an error** (forward/backward compatibility). When the schema declares
  `behaviors`, it delegates to `validate_behaviors`.
- `validate_behaviors(behaviors, spec_id=None) -> list[error]` — the record validation in §2.

`search_specs.py` was rewired to import `parse_frontmatter` from `frontmatter.py`
(adding the script's own dir to `sys.path` so the import works regardless of cwd), and its
`Spec` dataclass gained a `behaviors: list = field(default_factory=list)` field so search
and `--format json` surface behaviors. The stated proof for the substrate is
`test_frontmatter.py` (present on branch, stdlib `unittest`): inline arrays round-trip,
block lists, list-of-maps, missing closing `---`, partial/empty frontmatter, unknown field
preserved, malformed grammar raises.

Verification the plan calls for: run `search_specs.py --id <id> --format json` on a
fixture with `tags: [a, b]` and the tags now appear (previously empty).

---

## 9. What Phase 1 explicitly is NOT (so a newcomer doesn't over-read it)

From `01-phase-1.md §2` "Out of scope" and §9 acceptance criteria:
- **No** behavior graph / `behavior.json` / blast-radius / coverage fingerprints (Phase 2).
- **No** model-based Tier-2 contradiction checks, principle enforcement, declarative-drift
  (Phase 3+).
- **No** ADR machinery (Phase 4 — `decisions/` exists empty until then).
- **No** `knowledge-base/` migration — that was a decoupled, standalone PR shipped ahead of
  this phase.

It is about **"identity, lifecycle, links, and integrity — not the graph and not
enforcement intelligence."**

---

## 10. Sequencing note (git-confirmed)

The commits on `feat/behavior-layer` land the plan foundation-first:
`c6d1642` (scoped fail-loud parser + stateless runner detection) →
`aed2046` (Behavior entity + lifecycle validation) →
`bcaa8c9` (level enum + entry validation) →
`ea2fe0f` (**added the `confirmed` state**) →
`ce519aa` (ADR_SCHEMA — a later phase) →
`4ab191a` (only behavior-validate when schema declares behaviors) →
… → `406071c` (two behavior adapters) → `e6a02f8` (Tier-1 link checks / verify) →
`68a5c03` (intent classification review queue + lifecycle-aware wrap-up staging) →
`54d6eb3` (scope the accepted-but-scaffold check to one scenario).

The important takeaway for a newcomer: **the parser was rebuilt before the schema grew**,
and **`confirmed` is a later refinement** to the originally-4-state lifecycle.
