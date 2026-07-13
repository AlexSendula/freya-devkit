# SP5 — Security ↔ Behavior Cross-Reference (design)

**Status:** Draft for review
**Date:** 2026-06-30
**Parent design:** `docs/design/behavior-layer/03-adoption-and-intent-lifecycle.md` (§7 security↔behavior, §9 SP5, §12 acceptance criteria).
**Depends on:** SP1 (the `accepted` state + the accepted-only gate), SP4 (`findings.json` index + its schema; `status` reads `open` findings). Builds on `codebase-security-scan`'s existing `check-specs` declarative cross-reference and `behavior-graph`'s `behavior.json`. Independent of SP2/SP3.

---

## 1. Goal

Make an **`accepted`, test-backed behavior** that explains a flagged security finding the **strongest possible "intentional" evidence** — a *verified guarantee*, not a prose claim — and downgrade the finding accordingly (dropping it from the outstanding count while keeping it visible with the behavior reference). Satisfies §12:

> `codebase-security-scan` cross-references `accepted` behaviors (not only declarative decisions) as intentional evidence.

The canonical case (§7): a scan flagging "endpoint doesn't verify the user exists" is silenced by "accepted behavior BEH-003, verified by a passing test, says the uniform response is the intended anti-enumeration guarantee."

## 2. Resolved decision (from brainstorming)

- **Only `accepted` (verified) behaviors downgrade a finding.** An `accepted` behavior — confirmed intent **and** a passing linked test — whose intent explains the finding downgrades it to *intentional (verified)*: the test proves the flagged pattern is the intended, working behavior. A `confirmed` behavior (intent confirmed, test owed) at most adds an **advisory note**; the finding **stays open** until a test verifies it. Unverified states never silence a security finding.

## 3. Architecture

Mirror the existing `check-specs` flow (deterministic candidate-gather → agent relevance judgment → annotate in place), adding a behavior pass alongside the declarative-spec pass. One small deterministic query is added to `behavior-graph`; the rest is a `codebase-security-scan` SKILL.md extension + a `findings.json` schema field.

### 3.1 `behavior-graph --covering <file>` (deterministic prefilter)

Add `--covering <file>` to `behavior_graph.py`. It returns the **`accepted`** behaviors in `behavior.json` whose `exercises` include the given project-relative file:

```json
{"version": 1, "file": "app/api/.../route.ts",
 "covering": [{"behavior_id": "BEH-003", "spec_id": "SPEC-001", "coverage": "static"}]}
```

- Filters to `state == "accepted"` (the verified bar). `coverage` is reported (`observed` is stronger evidence the path is actually executed than `static`) but does not change membership — `accepted` is the gate.
- Read-only; empty `covering` (with the file echoed) when there is no graph or no accepted behavior touches the file. Never raises.
- This bounds the scan's search to behaviors that actually touch the flagged code; the agent reads those behaviors' specs for intent and judges relevance.

### 3.2 `codebase-security-scan` cross-reference extension (SKILL.md)

Extend the cross-reference step (the `check-specs` command, and the inline cross-referencing inside `scan`/`update` report generation). For each finding, after the existing declarative-spec check:

1. Run `behavior-graph --covering <finding.file>` to get candidate accepted behaviors.
2. For each candidate, read its behavior/spec intent and judge: **does this behavior's verified intent explain this finding?** (Same kind of relevance judgment `check-specs` already makes for specs.)
3. On a match: mark the finding **intentional**, record `behavior_ref: BEH-NNN`, and add a note *"verified by passing test BEH-NNN (SPEC-MMM)"*. Keep the finding in the report (annotate, don't delete).
4. **Evidence ranking:** an accepted-behavior match is the **strongest** evidence — it stands on its own, even when no declarative spec covers the finding. When both a behavior and a declarative spec apply, prefer the behavior reference (verified > claimed) and may record both.
5. A `confirmed` behavior that matches adds only an advisory note ("intended per BEH-NNN, but test owed — not yet verified"); the finding **stays open**.

The existing declarative-spec cross-reference (INTENTIONAL DESIGN via `spec_ref`) is unchanged and remains the path for non-executable (declarative) decisions.

### 3.3 `findings.json` schema extension

Add `behavior_ref` to SP4's `findings.json` schema (`references/findings-schema.md`): the `BEH-NNN` of the accepted behavior that explains the finding (optional; present only for the verified-behavior case). `status: intentional` as today. Consumers (e.g. `status`) already treat any non-`open` finding as not-outstanding, so a behavior-explained finding drops from the open count automatically; `behavior_ref` vs `spec_ref` records *which kind* of evidence (verified vs declarative) for auditability.

## 4. Data flow

`scan`/`update`/`check-specs` → for each finding, declarative-spec check (existing) **and** `--covering <file>` → agent judges candidate accepted behaviors → on a match, the prose report gains a "verified by BEH-NNN" annotation and `findings.json` gets `status: intentional` + `behavior_ref`. `status`/`BACKLOG.md` then show the finding as not-open. Nothing is deleted; the human can audit every downgrade against the named behavior and its test.

## 5. Error & edge handling

- **No `behavior.json` / no accepted behaviors:** `--covering` returns empty; the behavior pass is a no-op; declarative cross-reference proceeds unchanged.
- **Finding file in no accepted behavior's `exercises`:** no candidate → finding stays `open`.
- **Candidate behavior whose intent does NOT explain the finding:** the agent does not match it; finding stays `open` (no false silencing).
- **Never silences on a `proposed`/`confirmed` behavior** — `--covering` only returns `accepted`, and the SKILL.md rule restricts downgrade to accepted matches.
- **Safe by construction:** downgrade = annotate + set `status: intentional`, never delete; a misjudgment is visible and reversible in the report, not a vanished finding.

## 6. Testing

- **`behavior-graph --covering` — unit tests** (extend `test_behavior_graph.py`, reusing the `SurfaceTest`-style fixture): returns the accepted behavior(s) whose `exercises` include the file; excludes a `confirmed`/`proposed` behavior even if it covers the file; excludes an accepted behavior that does NOT cover the file; empty (file echoed) when there is no graph.
- **Cross-reference + annotation** is an agent procedure, validated by the **testbed dogfood**: the BEH-003 case end-to-end — introduce (or hand-write) a finding like "auth-start endpoint does not verify the user exists" on the route BEH-003 exercises; run the scan's cross-reference; confirm the finding is marked intentional with `behavior_ref: BEH-003` + a "verified by passing test" note, that `findings.json` carries `status: intentional` + `behavior_ref`, and that it drops from `status`'s open-findings count. Also confirm a finding on code no accepted behavior covers stays `open`. Production webapp off-limits.

## 7. Scope

**In scope:** `behavior-graph --covering <file>`; the `codebase-security-scan` cross-reference extension (consult accepted behaviors; downgrade-on-verified-match; advisory-only for confirmed); the `behavior_ref` `findings.json` field.

**Out of scope:** model-based **contradiction checks / principle enforcement** (the governance track — this capability was its prerequisite, and is the natural next track after the behavior layer); auto-creating behaviors from findings; changing how findings are *discovered* (only how they are cross-referenced); the observed-coverage adapter (parking-lot).

## 8. Acceptance criteria

- [ ] `behavior-graph --covering <file>` returns the `accepted` behaviors whose `exercises` include the file (read-only; empty + file echoed on no graph), and is unit-tested to exclude non-accepted and non-covering behaviors.
- [ ] `codebase-security-scan`'s cross-reference consults accepted behaviors (via `--covering`) in addition to declarative specs, and downgrades a finding to `intentional` with `behavior_ref` only when an accepted behavior's intent explains it.
- [ ] A `confirmed` (or `proposed`) behavior never downgrades a finding — at most an advisory note; the finding stays `open`.
- [ ] `findings.json` carries `behavior_ref` for behavior-explained findings; such findings drop from `status`'s open count while remaining visible in the report.
- [ ] Dogfooded on the testbed: the BEH-003 anti-enumeration finding is downgraded with a verified-by-test reference and drops from the open count; a finding on uncovered code stays open.

## 9. Open questions

None blocking. The relevance judgment (does a behavior's intent explain a finding) is inherently agent judgment — the same kind `check-specs` already makes for declarative specs — and is validated by the dogfood, not a deterministic guarantee. The safety posture (annotate + downgrade, never delete; accepted-only) bounds the blast radius of a misjudgment to a visible, auditable, reversible annotation.
