# Governance G3 — Contradiction Checks (research brief)

*Audience: an engineer who has never seen the Behavior Layer. This brief is
self-contained; you should be able to write explainer copy from it without
re-opening the source.*

Sources read for this brief (all verbatim-grounded):
- `docs/superpowers/specs/2026-07-01-g3-contradiction-checks-design.md` (G3 design)
- `docs/superpowers/plans/2026-07-01-g3-contradiction-checks.md` (G3 plan)
- `docs/superpowers/specs/2026-07-01-p4a-adr-support-design.md` (P4a — the ADR extension of G3)
- `skills/spec-manager/scripts/contradictions.py` (shipped code)
- `skills/spec-manager/scripts/resolution_log.py` (shared append-only core)
- `skills/spec-manager/scripts/adr.py` (ADR gather, verbatim spot-checks)
- `skills/wrap-up/SKILL.md` (Phase 3.5 step 6 wiring)

---

## 1. The one-sentence idea

When a **spec's intent is created or changed**, G3 judges whether it
**contradicts a higher-authority intent** and resolves the conflict by the
authority order. It is the third and final governance leaf:

- **G1** — does an accepted *test change* have an intent record?
- **G2** — does the *code diff* violate a principle?
- **G3** — does this *changed intent* conflict with *another recorded intent*?

So G3 is uniquely **intent × intent**. G1 is test-vs-record; G2 is code-vs-principle;
G3 is intent-vs-intent.

## 2. What tier this is, and why "advisory"

The design calls it the **Tier-2 contradiction check (LLM, advisory)**. The vision
excerpt it satisfies:

> Tier 2 — contradiction (LLM, advisory): on spec create-or-update and in batch at
> wrap-up, the *changed item only* is compared against same-domain, higher-authority
> items — initially **principles + feature-local decisions only**.

Two properties are load-bearing:

1. **Changed-item-only.** G3 never re-derives the whole repo. It looks at exactly the
   thing that changed and compares it against a small, higher-authority comparison set.
2. **Advisory / procedural / resolve-to-proceed.** Because the judgment is model work,
   G3 is an **agent-honored gate, never a script hard-block, never auto-fail on model
   confidence.** Posture is identical to G2. Each finding must be **resolved to proceed**
   — fix, refute, reconcile, or amend. "Ignore and push" is *not* a resolution;
   contradictions are resolved in the cycle that raised them (**no standing backlog**).
   It **fails open** on no principles / no peers / tooling error — never a false "clean,"
   never a block.

## 3. Why the check is SCOPED (the core design rationale)

This is the most important "why" for a newcomer. G3 is deliberately **narrow** so it
stays **incremental and trusted**:

- It compares the **changed item only** against **same-domain, higher-authority items**
  — never a whole-repo re-derivation.
- For a **spec**, the comparison set is **category-scoped**: `principles.md` (strictly
  higher authority) **plus** the intentional decisions of *other specs in the same
  category* (same authority level — a consistency check). The changed spec itself is
  excluded.

The rationale is trust and cost. A whole-repo re-derivation on every spec edit would be
expensive, slow, and noisy — and noise erodes the human's trust in the gate. By scoping
to the category (the blast-radius of the changed intent) the check stays cheap enough to
run at authoring time and focused enough that a surfaced finding is almost always real.

**Important nuance — ADRs are the exception to category-scoping.** ADRs are cross-cutting
*by definition*, so when the ADR extension shipped (P4a), the ADR half of the comparison
is **always-global** (see §7). Category-scoping applies to peer *specs*; ADRs are never
scoped. Design rationale (P4a §2): "Scoping only decides what reaches the LLM; the LLM
makes the contradiction judgment. Over-scoping (a filter that excludes a relevant ADR) is
a **silent miss** … and is unrecoverable. Under-scoping … is just **noise** it dismisses
in one line. A false negative here is far worse than a false positive."

## 4. The authority ladder (resolution semantics)

Authority order, refined across G3 + P4a: **principle > ADR > spec** (with `reference/`
below all). Resolution follows the ladder — the table below is verbatim from P4a §5.3:

| Changed item | Contradicts | Resolution (default) |
|---|---|---|
| spec | a principle | fix the spec (or consciously amend the principle) |
| spec | an **ADR** | **fix the spec** (ADR outranks) — or consciously amend the ADR |
| spec | a peer spec (same category) | **reconcile** — fix either side, or refute |
| **ADR** | a principle | **fix the ADR** (or amend the principle) |
| **ADR** | a peer ADR | **reconcile** |

Read the ladder as: *when two intents collide, the higher-authority one wins by default,
so you fix the lower one.* Two same-tier items have **no automatic winner** — that's a
**consistency conflict to reconcile** (fix one side, or refute if they don't truly
conflict).

## 5. The two context builders (what the deterministic helper gathers)

`contradictions.py` does **only** the deterministic gather / append / lookup. The
*judgment* ("does this changed intent contradict it?") and the *triage* (auto-clear /
retire / escalate) are agent work in the SKILL.md procedures.

### `build_context(project, spec_id)` — a changed SPEC's comparison set

Verbatim signature and return shape (shipped code):

```python
def build_context(project, spec_id):
    """Assemble {spec, category, principles, adrs, peers, adr_warnings} for a
    changed spec. `adrs` = ALL active ADRs (always-global, no scoping — design
    §2). `peers` = same-category specs (excluding self) with intentional_decisions.
    """
```

The peer filter (verbatim):

```python
peers = [
    {"spec_id": s.id, "decisions": s.intentional_decisions}
    for s in specs
    if s.category == target.category and s.id != spec_id and s.intentional_decisions
]
```

So `build_context` gathers, for a changed spec:
- **principles** — via `principles.parse_principles` (reused from G2),
- **adrs** — *all active ADRs*, always-global (P4a addition),
- **peers** — *same-category* specs, self excluded, empty-decision peers excluded,
- **adr_warnings** — malformed/unparseable ADRs surfaced (never silently dropped).

Return JSON shape (from P4a §5.1):

```json
{"spec":"SPEC-005","category":"auth","principles":[…],
 "adrs":[{"id":"ADR-001","title":"…","body":"…"}],
 "peers":[…],"adr_warnings":[]}
```

The agent then judges the changed spec against each principle, each active ADR, and each
same-category peer.

> **Historical note (design vs shipped):** the *original G3 design* (2026-07-01) was
> deliberately **ADR-blind** — `build_context` returned only `{spec, category,
> principles, peers}`, no `adrs`. G3 was built "ADR-**ready**, not ADR-**aware**" because
> `knowledge-base/decisions/` was an empty scaffold with no ADR format. **P4a** (same
> date) then added the `adrs` gather and `adr_warnings`, turning G3 "from ADR-*ready*
> into ADR-*aware*." The shipped `contradictions.py` is the P4a version. Explainer copy
> should present the *current* (ADR-aware) behavior; the ADR-blind story is the
> "why it was staged" backstory.

### `build_adr_context(project, adr_id)` — a changed ADR's comparison set

An ADR now outranks specs, so an ADR that itself contradicts a **principle** must be
caught — "else ADRs are the one authoritative artifact nothing governs" (P4a §5.2).
Verbatim signature (shipped code):

```python
def build_adr_context(project, adr_id):
    """Assemble {adr, principles, peer_adrs, adr_warnings, [note]} for a CHANGED ADR.

    A changed ADR is judged against the principles above it (authority:
    principle > ADR) and its peer ADRs at the same tier (reconcile). `peer_adrs`
    excludes the changed ADR. Returns a `note` if the ADR isn't found/active.
    """
```

So a changed ADR is compared against **its principles** (higher authority → fix the ADR)
+ **peer ADRs** (same tier → reconcile). `peer_adrs` = the *other* active ADRs; the
changed ADR is excluded.

### Summary of the two directions
- **A changed spec** → `build_context` → principles + **same-category** peer specs + **all
  active** ADRs.
- **A changed ADR** → `build_adr_context` → principles + **all** peer ADRs.

## 6. Where the check fires (triggers)

Two entry points to the *same* check (vision §8: "on spec create-or-update and in batch
at wrap-up"):

1. **Interactive — spec-manager `create` / `update <spec>`** (and, with P4a, `adr create`
   for ADR-vs-principle). Right after a spec is authored or changed, run the check on
   *that* spec and resolve any contradiction then — "the cheapest place to catch a
   conflict, before it's even committed."
2. **Batched — wrap-up Phase 3.5 step 6.** Over the specs (and ADRs) changed this cycle,
   run the check as a **resolve-to-proceed** step, **immediately after G2's principle
   checkpoint (step 5)**. The ordering is deliberate:
   > deterministic facts (G1 + links + accepted-behavior run) → principle judgment (G2)
   > → intent-coherence judgment (G3).
   With P4a + P4b the wrap-up ordering is: G2 principle (step 5) → G3 intent-coherence
   (step 6) → P4b declarative-drift (step 7). This batched pass is the safety net for
   specs changed *outside* the interactive flow.

### The wrap-up step 6 mechanics (verbatim structure)
- **a.** Find the specs **and ADRs** changed this cycle — the `knowledge-base/specs/**`
  files AND `knowledge-base/decisions/**` files in `git diff "$BASE" --name-only`. No
  changed specs and no changed ADRs ⇒ **skip this step.**
- **b.** For each changed spec: `contradictions.py context --project . --spec <SPEC-ID>`,
  judge against each principle / peer / active ADR, triage against `prior`, resolve.
- **c.** For each changed ADR: `contradictions.py adr-context --project . --adr <ADR-NNN>`,
  judge the ADR body against each principle (→ fix the ADR) and each peer ADR
  (→ reconcile), triage, resolve.

## 7. ADR always-global scoping (P4a) — why ADRs break the category rule

- **No `applies_to` field.** The only "filter" for ADRs is **lifecycle/authority status**:
  G3 compares against **`accepted`**, non-`superseded`/`deprecated` ADRs only. (`active_adrs`
  keeps `status == "accepted"`, verbatim from `adr.py`.)
- **Volume is tiny** ("single digits now; <20 realistically"), so scoping "saves nothing
  and costs silent-miss risk."
- **Prior art agrees** — Nygard/adr-tools/MADR keep ADRs a flat, status-only list; tag
  scoping is known to cause "tag rot" and the "cross-cutting decision has no home" failure.
- If ADR volume ever crosses ~30 the only safe narrowing lever is an **opt-out**
  (`skip_for`), never opt-in — "keeping the failure mode 'noise,' never 'silence.'" YAGNI
  for now.

## 8. The resolution log — `contradiction-resolutions.jsonl`

G3 gets its **own** append-only log at
`knowledge-base/contradiction-resolutions.jsonl` (constant
`RESOLUTIONS_RELPATH = "knowledge-base/contradiction-resolutions.jsonl"`).

- **Keyed by `(spec, against)`** where `against` is the conflicting item — `principle:2`,
  `SPEC-003`, or (P4a) `ADR-007`. A changed ADR keys as `(ADR-001, against)`. The design
  deliberately did **not** extract a shared resolution module *at first* — "to avoid
  churning G2's shipped code." (Later, `resolution_log.py` *was* extracted as a shared
  append-only core used by G2/G3/P4b — see §9.)
- **Example record** (verbatim from design; `reason` genericized here to avoid domain
  content — it originally described a hashed-token spec decision):

  ```json
  {"date":"2026-07-01","spec":"SPEC-005","against":"principle:2","verdict":"refuted","reason":"<why this is a false positive>","commit":"abc1234"}
  ```

- **Verdicts:** `VERDICTS = ("refuted", "amended", "auto-cleared", "superseded")`.
  - A **fix** (editing the spec, or a peer to reconcile) needs **no entry** — git is the
    record.
  - **amend** = the *higher-authority* item (a principle) was consciously changed.
  - **superseded** = retirement. The log is **append-only**; a stale resolution is retired
    by a *later* `superseded` record (**latest-wins per `(spec, against)`**), never a
    mutated field.
  - **auto-cleared** = a logged auto-clear on recurrence (see §10).
- **`--against` is free-form**, so `ADR-NNN` slots into the existing `(spec, against)`
  keying with **no new JSONL field, no new module** (P4a §5.4). `ADR-NNN` is documented as
  a valid `--spec` and `--against` value.
- **Staging:** `contradiction-resolutions.jsonl` + any `principles.md`/spec amendment →
  **artifacts** (commit 2). (A code/spec *fix* rides its normal commit.)

## 9. The shared append-only core — `resolution_log.py`

`contradictions.py` now delegates its log mechanics to `resolution_log.py`, "shared by the
governance resolution logs (G2 `principles.py`, G3 `contradictions.py`, P4b `drift.py`)."
Each caller keeps its own `RELPATH`, `VERDICTS`, record schema, and public signatures;
only the mechanics live in the shared core:

- **`append(path, record)`** — write one JSONL line (`json.dumps(record, sort_keys=True)`),
  creating parents; returns the path.
- **`load(path, label=None) -> (records, warnings)`** — parse in append order; **skip a
  malformed line with a warning** naming `label` (default the file name)
  (`"skipped malformed line {i} in {label}"`); a missing file → `([], [])`.
- **`active(records, keys_of, want=None) -> list`** — latest-active: keep the **LAST**
  record per key, **drop keys whose latest verdict is `superseded`**, apply the `want`
  filter, return survivors de-duped in append order.

G3's `active_prior` wraps the core:

```python
def active_prior(project, spec, against=None):
    """Latest-active resolution per (spec, against) for the given spec."""
    records, warnings = _load_records(project)
    keys_of = lambda r: [(r.get("spec"), r.get("against"))]
    want = lambda k: k[0] == spec and (against is None or k[1] == against)
    return resolution_log.active(records, keys_of, want), warnings
```

Each G3 record has a **single `against`** (unlike G2's `paths` list), so `active_prior`
needs no key explosion / de-dup — one `(spec, against)` per record.

## 10. Recurrence triage (auto-clear / retire / escalate) — and why it's fenced

The check runs on every spec change, so a *prior resolution* may recur. `prior` returns
the latest-active resolution per `(spec, against)`; the agent **re-validates it against
the current spec text**:

- **still valid** (current intent still *is* what the prior reason described) → **auto-clear**
  (logged as `verdict: auto-cleared`),
- **stale** (the spec was rewritten so the prior no longer maps) → **retire**
  (`verdict: superseded`),
- **now a real contradiction** → **escalate** to the human.

Guardrails (identical to G2), the reason a mis-judgment can only ever produce friction or
an auditable auto-clear, never a silently-shipped contradiction:
- re-judge the current intent against the **specific prior reason** (not the spec id),
- **bias to escalate** on ambiguity,
- **always log** auto-clears,
- a finding with **no prior always reaches the human**.

## 11. Error & edge handling (verbatim)

- **Empty comparison set** (spec alone in its category, no principles) → `context` returns
  empty → the check **no-ops**.
- **Spec with no decisions** → **still checked** (its purpose/scope prose can contradict a
  principle).
- **`contradiction-resolutions.jsonl` malformed / partially corrupt** → `prior`/`resolve`
  skip unparseable lines with a warning; never crash, never silently authorize an
  auto-clear.
- **Spec not found / no git** → `context` returns a graceful empty result with a `note`;
  **fail-open** — never a false "clean," never a block.
- **No ADRs** (empty `decisions/`) → `active_adrs` empty → `adrs: []` → the ADR comparison
  no-ops; G3 behaves exactly as pre-P4a (zero-regression).
- **Malformed ADR** → surfaced in `adr_warnings` (never silently excluded) and hard-flagged
  by the deterministic `adr verify`.

## 12. CLI surface (verbatim from shipped `contradictions.py`)

- `context --project . --spec <SPEC-ID>` — assemble a changed spec's comparison set.
- `adr-context --project . --adr <ADR-NNN>` — assemble a changed ADR's comparison set.
- `resolve --project . --spec <SPEC-NNN|ADR-NNN> --against <principle:N|SPEC-NNN|ADR-NNN>
  --verdict <refuted|amended|auto-cleared|superseded> --reason "…" [--commit SHA]
  [--date YYYY-MM-DD]` — append one JSONL line.
- `prior --project . --spec <SPEC-ID> [--against X] [--format json]` — latest-active per
  `(spec, against)`.

All subcommands **exit 0** (advisory posture — no non-zero blocking). Invoke via
`"${CLAUDE_PLUGIN_ROOT}/skills/spec-manager/scripts/contradictions.py"`.

## 13. Testing posture

- **`contradictions.py` unit tests** (stdlib `unittest`) cover the *deterministic* gather /
  append / lookup: `context` returns principles + same-category peer decisions, **excludes
  the changed spec itself**, empty when alone / no principles; `resolve` appends a
  well-formed line **without rewriting prior lines**; `prior` is **latest-wins per
  `(spec, against)`**, excludes `superseded`, skips a malformed line with a warning. P4a
  adds: `build_context` includes `adrs` (active only, excludes `superseded`);
  `build_adr_context` returns principles + peer ADRs; both no-op with no ADRs.
- **The judgment + LLM triage is an agent procedure** → validated by the **testbed
  dogfood**, not a unit test. Scenarios: spec-vs-principle contradiction surfaces +
  resolve-to-proceed; refute → logged; re-run unchanged → auto-cleared (no re-nag); rewrite
  the spec → retired; a *new* contradiction → escalates; two same-category specs with
  conflicting decisions → peer reconcile; (P4a) spec-vs-ADR → fix-the-spec, ADR-vs-principle
  → fix-the-ADR. **Production webapp off-limits.**

## 14. What G3 explicitly does NOT do

- **Declarative-drift** ("code drifted from a declared spec," e.g. spec says Postgres, code
  uses Mongo) is a *code-vs-intent* check — **not G3**. It's Phase-4 Expansion (P4b `drift.py`).
- The **original G3 was ADR-blind**; ADR-awareness arrived with P4a (both dated 2026-07-01).
- No **auto-fail hard gate** on model confidence (vision defers until the false-positive
  rate is measured).
