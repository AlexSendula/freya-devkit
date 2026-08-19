# G1 — Declared-Intent Records (design)

**Status:** Draft for review
**Date:** 2026-07-01
**Parent design:** `docs/design/behavior-layer/00-vision.md` (§7 the governance rule that makes the two directions trustworthy; §8 enforcement / block-vs-warn; §9 Phase 3 — Governance).
**Track:** Phase 3 — Governance, sub-project **G1** (of G1 intent records / G2 principle enforcement / G3 contradiction checks).
**Depends on:** SP1 (the `accepted` state + the accepted-behavior run/gate at wrap-up), the spec↔behavior link + `locator` (Phase 1/2), and the ecosystem's incremental change-set convention (G1 keeps its **own** baseline marker — see §6/§7 for why it must not reuse `.spec-last-update`). Independent of G2/G3.

---

## 1. Goal

Give an `accepted` behavior's test **exactly one sanctioned way to change**: a durable, machine-checkable **declared-intent record** (`INTENT-NNN`). Editing an accepted test is treated as an attempt to change the intended behavior, and is a **deterministic hard-block at wrap-up** unless a record in the same change-set declares it. Satisfies vision §7:

> an accepted behavior's test may only be changed through a declared-intent record … a bare code change that breaks an accepted test is always a regression … without a concrete record, "declared intent" is unenforceable and every red test degrades into "just update it" until the safety net rots.

**The gap this closes.** After SP1, a failing accepted test hard-blocks wrap-up, and the blocking rules *refer* to "declare intent (file an `INTENT-NNN`)" as the escape hatch — but that artifact does not exist yet. So today the only sanctioned responses to a red accepted test are "fix the code" or "quarantine"; an *intentional* change to an accepted guarantee has **no legitimate path** through the gate. G1 builds that path.

## 2. The problem G1 actually solves — a hole in the fact-gate

The system keeps three things in agreement: **code**, the **test**, and the **description** (the BEH record's prose).

- **Code ↔ test** is checkable as a **fact**: you *run the test*. Disagreement ⇒ red ⇒ hard-block. This is the strongest guarantee in the system.
- **Test ↔ description** is only a **judgment**: no machine can prove an English sentence correctly describes a test. This is owned by the judgment-shaped gate (G3), not G1.

The fact-gate has one blind spot: **editing the test itself.** If you change the code *and* the test together, the test still passes — **green** — so the fact-layer sees nothing, even though the guarantee was silently redefined. That is the one way to slip a changed guarantee past the strongest check in the system.

**G1 exists solely to plug that hole.** It makes the *act of editing an accepted test* require a durable, conscious record — converting an invisible green change into a visible, declared one. "Was an accepted test edited, and is there a record naming it?" is itself a **fact**, so G1 stays fully deterministic.

## 3. Resolved decisions (from brainstorming)

1. **Record home — standalone file + commit trailer.** The record is `knowledge-base/intents/INTENT-NNN.md`; the authorizing commit carries an `Intent: INTENT-NNN` trailer. **The file is the gate's source of truth** (commit messages get mangled by rebase/amend); the trailer is strongly-recommended traceability, not gate-enforcing.
2. **Detection — changed files ∩ accepted locators, incremental.** No content-hashing. The change-set diff already lists changed files, and the behavior→`locator` link already says which files are accepted tests; intersect them. Scoping is **temporal** (the record must be new in the same change-set), which falls out of the existing incremental tracking — a past record cannot bless a future edit.
3. **Gate scope — record-alone satisfies (deterministic presence only).** The gate checks that a record naming the edited behavior *exists in the change-set*. It does **not** verify the rationale is honest or that the description was updated — that is judgment (G3). Any edit to an accepted test triggers the requirement ("regardless of what" — no cosmetic-edit exemption).

## 4. The intent record

**Home & IDs.** `knowledge-base/intents/INTENT-NNN.md`. `INTENT-NNN` is allocated as the next sequential number across existing intent records (same convention as `SPEC-NNN` / `BEH-NNN`). Deterministic duplicate-ID detection is enforced by `verify_intent` (§6).

**Format — block-style lists only** (sidesteps the hand-rolled frontmatter parser's inline-array bug; see §9):

```markdown
---
id: INTENT-001
behaviors:
  - BEH-003
approver: Alex
date: 2026-07-01
---
## Rationale
Anti-enumeration response changed from a 404 to a uniform 200
per the revised threat model (status-code enumeration).
```

Fields: `id`, `behaviors` (the `BEH-NNN`s this record authorizes changing), `approver` (captured, not authenticated — see below), `date`, and a free-text `## Rationale`.

**Approver semantics.** Deterministically we cannot verify identity, so `approver` is captured, not authenticated. Solo, author == approver — the record's value is **durable conscious confirmation**, not external sign-off. In a team context (e.g. Ping/ForgeRock), external approval is supplied out-of-band by PR review of the commit that carries the record; the tooling does not try to own that.

**Lifecycle / "spent."** A record is scoped to the change-set it ships in (the incremental diff since the last successful wrap-up). Once that wrap-up succeeds and advances the baseline, the record has done its job and remains in the tree as durable history; it cannot authorize a later edit, because that edit appears in a subsequent diff with no accompanying (new) record. Optionally, accepting a record stamps a one-line pointer into the owning behavior's spec change-history (mechanical, no judgment) for traceability.

## 5. What triggers the requirement

Keyed off git status of the accepted-behavior locators, using the behavior's **state at HEAD** (post-change):

| Locator change | Behavior `accepted` at HEAD? | Record required? |
|---|---|---|
| **Modified** (M) | yes | **yes** — the "regardless of what" case |
| **Deleted** (D) | yes | **yes** — removing a live guarantee is an intent change |
| **Added** (A) for a brand-new behavior | yes | **no** — normal accept flow, not a change to an existing guarantee |
| **Renamed** (R, no content change) | yes | **no** — moving a file is not changing the guarantee |
| any change | no (`proposed`/`confirmed`/`quarantined`/`deprecated`) | **no** — only accepted guarantees are governed |

If a behavior is `quarantine`d or `deprecate`d **in the same change** as its test edit, it is not accepted at HEAD → no record needed.

## 6. The deterministic check (`verify_intent`)

A **sibling** to `verify_links.py` in spec-manager — it shares the Tier-1 hard-block tier and exit-code convention, but is kept separate because it is *git-aware / transition-based*, whereas `verify_links` is a stateless single-snapshot check. Mixing a baseline-diff into `verify_links` would muddy a clean, stateless script.

**Inputs:** the **baseline commit** (G1's own marker — see below); the accepted behaviors + their `locator`s (read from spec frontmatter, as `verify_links` does — no dependency on `behavior.json`); the current change-set.

**Baseline marker — G1 keeps its own, and here's why.** Reusing `.spec-last-update` is wrong: wrap-up advances that marker in **Phase 3** (spec-manager update), *before* the Phase 3.5 behavior-integrity check runs — so by check time the baseline would equal HEAD and the diff would be empty, silently disabling G1. G1 therefore keeps a dedicated `knowledge-base/intents/.intent-last-verified` marker, advanced **only when the gate passes at wrap-up completion** (after the check, not before it). Absent the marker (fresh repo / first run) the check **skips** and never blocks.

**Algorithm:**
1. `changed` = files changed between the baseline and the working tree, via `git diff --name-status -M <baseline>` (this diff spans committed changes since baseline **and** tracked working-tree edits — see the timing note in §7).
2. `edited_accepted` = behaviors that are `accepted` at HEAD whose `locator` is in `changed` with status **M or D** (excludes A and pure R).
3. `records_in_change` = every `knowledge-base/intents/INTENT-NNN.md` present **on disk** that was **absent at the baseline commit** (`git cat-file -e <baseline>:<path>` fails ⇒ new). Discovering records by filesystem scan + baseline-existence — rather than by `git diff` — means untracked, staged, and committed records all count uniformly (an untracked new record does not show in `git diff`). Pre-existing records are ignored: this is what makes a record self-scoping.
4. `covered` = union of every in-change record's `behaviors:`.
5. `unauthorized` = `edited_accepted − covered`.
6. If `unauthorized` is non-empty → **exit non-zero (hard-block)**, printing each behavior, its changed locator, and the remedy: *"file `knowledge-base/intents/INTENT-NNN.md` naming BEH-003 (`spec-manager intent new BEH-003`), or revert the test edit."*

Referential nicety: a record naming a non-existent `BEH` produces a **warning**, not a hard-block on that alone. A malformed/unparseable record (e.g. missing `behaviors:`) **fails loud** — a broken record must never silently "cover" anything.

**Output & exit-code contract.** `--format json` emits the full result (`unauthorized`, `edited_accepted`, `records_in_change`, warnings) and the process exits non-zero when `unauthorized` is non-empty. Consumers **must not** invoke it with `check=True` (they must read the JSON on a non-zero exit) — the same discipline `verify_links` established.

**No-baseline behavior.** G1 governs *transitions*, which require a baseline. If `.intent-last-verified` does not exist (fresh repo / full-scan mode), the check **skips** and never blocks; the marker is created at the first successful wrap-up.

## 7. Integration & data flow

**`spec-manager intent new <BEH-NNN…>`** — a low-friction authoring helper: allocates the next `INTENT-NNN`, prefills `behaviors:`, stamps `date`/`approver`, opens a rationale stub. Turns "blocked" into a ~20-second action.

**`spec-manager verify`** runs `verify_links` **and** `verify_intent` (both Tier-1 hard-block).

**Wrap-up Phase 3.5** gains one deterministic step alongside the existing `verify_links` hard-block: run `verify_intent`; a non-empty `unauthorized` set blocks wrap-up. The `.intent-last-verified` marker is advanced to the current commit **only after the gate passes** (never in Phase 3, which would blind the check — see §6) — mechanically, at Phase 5 with the other tracking files.

**Staging (behavior-aware rule).** `INTENT-NNN.md` and the `.intent-last-verified` marker live in `knowledge-base/` → **artifacts commit** (commit 2). The **code commit** (commit 1) carries the test edit and the `Intent:` trailer pointer.

**Timing note (why working-tree, not just committed).** In wrap-up's two-commit flow the test edit lands in commit 1, but the record is staged for commit 2 — and Phase 3.5 runs *between* them. So at check time the edited test is committed while the record is only in the working tree. `verify_intent` therefore reads working-tree state, not just `HEAD`, so it sees the record before commit 2 exists.

**End-to-end (the BEH-003 case):**
1. Engineer decides the anti-enumeration response should change; edits code **and** BEH-003's test together (stays green).
2. `wrap-up` → Phase 0 commits the code (incl. the test edit).
3. Phase 3.5 `verify_intent`: BEH-003's locator is `M`, no record names it → **BLOCK** with the remedy line.
4. Engineer runs `spec-manager intent new BEH-003`, writes one sentence of rationale, sets approver.
5. Re-run `wrap-up` → `verify_intent` sees the new record covering BEH-003 → passes. Artifacts commit includes `INTENT-001.md`; the code commit's trailer points to it.

## 8. Testing

**Unit (`verify_intent`, extending spec-manager tests), each a small git fixture:**
- edited accepted locator + no record → block (non-zero, names the behavior);
- edited accepted locator + record naming it → pass;
- newly-added accepted locator → pass (no record needed);
- deleted accepted locator + no record → block;
- **pre-existing** record (not new in the change-set) → does *not* authorize → block;
- edited `proposed`/`quarantined` locator → pass;
- behavior deprecated/quarantined in the same change + test edited → pass (not accepted at HEAD);
- pure rename (R, no content change) → pass;
- no baseline (`.intent-last-verified` absent) → check skipped, no block;
- **baseline == HEAD** (marker already at the current commit) → empty diff, no false pass/fail — guards the Phase-3-ordering hazard (§6);
- untracked (unstaged) new record → still counts as in-change (discovered on disk, absent at baseline);
- malformed record (missing `behaviors:`) → clear error;
- record naming a non-existent `BEH` → warning, not a hard-block.

Plus the **exit-code contract**: a non-zero exit still emits complete JSON (never lost), mirroring `verify_links`.

**Dogfood on the testbed:** the BEH-003 case end-to-end (edit code+test to stay green → blocked → `intent new BEH-003` → passes), and a control (edit a `proposed` test → not blocked). Production webapp off-limits.

## 9. Preconditions & known limits

- **Frontmatter substrate (vision §10) — resolved, not deferred.** The hand-rolled parser silently drops *inline* arrays. G1 sidesteps it by specifying **block-style** lists in the record (`behaviors:` as a `-` list), so G1 does **not** require replacing the parser first.
- **Code-graph capability contract (vision §10).** Not on G1's path: the check is `git diff ∩ locators`, needing no blast-radius from code-graph. (G3 will need the trustworthy blast radius; G1 does not.)
- **Shared test helpers.** If an accepted behavior's assertions live partly in a helper file that is not the `locator`, editing only the helper would not trip the path-based check. Accepted limitation for G1 (both a content-hash and a diff approach share it); a future refinement could widen detection to the test's import closure.

## 10. Scope

**In scope:** the `INTENT-NNN` artifact + ID allocation; `spec-manager intent new`; `verify_intent.py` (the deterministic transition check) + its `spec-manager verify` and wrap-up Phase 3.5 wiring; the behavior-aware staging rule for records; the mechanical change-history pointer stamp.

**Out of scope:** verifying a rationale is *honest* or that the description still matches the test (**G3** — judgment); principle enforcement (**G2**); any model/LLM check; ADR-awareness; identity/approval verification; auto-rewriting BEH descriptions; content-hash fingerprinting (deliberately dropped — temporal scoping replaces it).

## 11. Acceptance criteria

- [ ] `INTENT-NNN.md` records live at `knowledge-base/intents/`, block-style frontmatter, with `id`/`behaviors`/`approver`/`date` + `## Rationale`; IDs allocate sequentially; duplicates are caught by `verify_intent`.
- [ ] `verify_intent` hard-blocks (non-zero) when an `accepted` behavior's locator is **modified or deleted** in the change-set and no **in-change** record names it; passes when such a record is present; skips cleanly with no baseline.
- [ ] Newly-added accepted locators, pure renames, and edits to non-accepted behaviors never require a record.
- [ ] A **pre-existing** record does not authorize a new edit (temporal scoping proven by test).
- [ ] `spec-manager intent new <BEH…>` scaffolds a valid record; `spec-manager verify` and wrap-up Phase 3.5 both run `verify_intent` as a Tier-1 hard-block; records stage to the artifacts commit while the code commit carries the `Intent:` trailer.
- [ ] `verify_intent --format json` emits complete output on a non-zero exit (consumers read JSON, never `check=True`).
- [ ] Dogfooded on the testbed: the BEH-003 stays-green edit is blocked until a record is filed, then passes; editing a `proposed` test is never blocked.

## 12. Open questions

None blocking. The one judgment-shaped concern — whether a filed rationale is *truthful* and the description still matches the changed test — is deliberately **out of G1** and owned by G3 (model contradiction checks). G1's safety posture is presence-checking a durable, self-scoping record; its blast radius on a misjudgment is a visible, auditable artifact in the tree, never a silently-changed guarantee.
