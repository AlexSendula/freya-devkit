---
id: SPEC-027
title: A Security Run That Could Not Finish Says So
category: infra
tags: [security, audit, exit-codes, honesty, findings, disposition, driver]
status: implemented
certainty: 78
created: 2026-08-21
updated: 2026-08-24
related_code:
  - skills/freya-codebase-security-scan/scripts/audit.py
  - skills/freya-codebase-security-scan/scripts/audit_engine.py
  - skills/freya-codebase-security-scan/SKILL.md
  - skills/freya-codebase-security-scan/references/findings-schema.md
intentional_decisions:
  - "Exit 3 is a distinct code so a truncated run cannot be read as a complete one"
  - "Zero verdicts settles as needs-review — a finding is never deleted for lack of information"
  - "A spec citation the project cannot corroborate is ignored rather than trusted"
  - "Findings sharing a location under different categories are annotated, never silently merged"
  - "A downgrade reclassifies a finding in place; nothing ever removes one from the report, and the evidence is labelled rather than verified unless the scan passed --verify"
  - "`mitigated` is a documented disposition that no code path currently emits"
behaviors:
  - behavior_id: BEH-131
    title: A run in which no task got a usable answer is never reported as clean — it exits 2 with the last error, instead of an empty array at exit 0
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#MainTest.test_a_run_where_every_finder_failed_is_never_reported_as_clean
  - behavior_id: BEH-132
    title: A run where only some tasks answered is reported INCOMPLETE at exit 3 — naming how many, the last error, and how much of the surviving evidence actually completed verification — with the survivors still printed
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#DegradedRunTest.test_a_mostly_failed_run_is_reported_as_incomplete
  - behavior_id: BEH-133
    title: A run whose discovery was cut short — by the findings cap or by the call ceiling — exits 3 saying what it discarded and that the remaining rounds never ran, and still reports the findings it had already paid to verify
    state: proposed
    level: integration
    adapter: unittest
    entry: skills/freya-codebase-security-scan/scripts/audit.py
    locator: skills/freya-codebase-security-scan/scripts/test_audit.py#TruncatedDiscoveryTest.test_a_cap_that_discarded_findings_is_never_reported_as_complete
  - behavior_id: BEH-134
    title: A finding is never dropped for lack of information — with no verdicts it settles as needs-review, and only a unanimous refutation removes it
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-codebase-security-scan/scripts/test_audit_engine.py#DispositionTest.test_no_verdicts_is_needs_review_not_drop
  - behavior_id: BEH-135
    title: A finding explained by an accepted behavior is reclassified in place — status intentional with a behavior_ref and the query's evidence label, still listed in the report and in findings.json — and is never deleted
    state: proposed
    level: e2e
    adapter: manual
    locator: skills/freya-codebase-security-scan/scripts/test_findings_index.py#DowngradeTest.test_a_behavior_explained_finding_is_reclassified_not_removed
---

# A Security Run That Could Not Finish Says So

## What

The driver's exit code, not its stdout, is the result. An empty array means a clean codebase
only at exit 0; at any other code it means the scan did not run. `main()` therefore ends in a
ladder of honesty checks over what actually happened on the wire, tracked in `Health` at two
levels — attempts, which drive the diagnostics, and *tasks*, which drive the trust decision.

- **Nothing answered → exit 2.** If the context call fails, the run stops before any finder is
  launched; if every finder fails, or if unanswered tasks coincide with an empty result, the
  run refuses to print `[]` at exit 0 and reports the last error instead.
- **Something did not answer → exit 3, INCOMPLETE.** Survivors are still printed, and the
  banner says how many tasks got no usable answer, out of how many, with the last error.
- **Discovery stopped early → exit 3, INCOMPLETE.** Whether the `--max-findings` cap ended it
  (naming how many discovered findings were discarded unverified, and that the remaining rounds
  never ran) or the attempt ceiling did (in which case the batches already verified survive the
  unwind and are reported).
- **Everything answered and discovery went dry → exit 0**, the only shape that means complete.

The banners are held to the same standard as the run: `verified_clause` states how much of the
surviving evidence actually completed verification, so a run whose skeptics all failed says
"NONE of the 1 findings below could be verified" rather than "verified and real".

Inside the engine the same rule governs a single finding. Verdicts are counted, not assumed:
`verification.lenses` names the lenses that answered rather than the three that were asked, no
verdicts at all settles as `needs-review`, and only a unanimous refutation drops a finding.
A `spec-intentional` refutation may outrank the majority and reclassify a finding as
`intentional-design`, but only when it cites something the project actually contains.

One layer further out, in the report the skill writes, the same shape again: a finding that an
`accepted` behavior explains becomes `status: intentional` with a `behavior_ref`
and drops out of the outstanding count, while staying fully visible in the prose report and in
`findings.json`.

That last one is the place this spec's own rule is hardest to hold, so state what the evidence
is worth. **Whether a test ran depends on one flag, and this spec's rule is that the answer has
to say which.** Plain `--covering` runs nothing: `covering()`, in
`skills/freya-behavior-graph/scripts/behavior_graph.py`, re-derives state and locator from
`knowledge-base/specs/` and reads exercised paths from the committed
`knowledge-base/.graph/behavior.json`, and both of those are files the repository under audit
writes. What it requires of them is narrow: an `accepted` state, a locator that resolves, and an
exercised path carrying `source: observed`. An edge inferred from the import graph licenses
nothing, where until 2026-08-24 it silenced a finding exactly as a recorded run did.
`--covering --verify` re-runs the linked test through `freya-behavior-runner`, and the scan
passes that flag (`skills/freya-codebase-security-scan/SKILL.md:421`). Either way the query
returns an `evidence` string saying exactly what it trusted, the skill copies that string into
the note verbatim, and writing *"verified by passing test"* over a row that was not verified is
forbidden in as many words (`skills/freya-codebase-security-scan/SKILL.md:436`). Unverified, a
downgrade is the strongest evidence on offer and is still a labelled claim rather than a
verification — which is exactly the distinction this spec exists to keep visible, applied to the
scan's own reasoning rather than to a worker's. ADR-012 carries the full argument and both of
its dated corrections, the second retracting part of the first.

## Why

The headline defect this exists to prevent was measured, not imagined: a phase-6 audit of a
real 299-file repository had 22 of its 27 calls fail, reported three findings the way a
complete audit reports its results, and exited 0. Earlier, 26 failed calls exited 0 with `[]`
and the skill's report loop wrote that the codebase was clean. A security tool that says "no
findings" when it means "no answers" is worse than one that does not run, because the answer is
consumed by an agent that has no other way to tell the difference.

Truncation is the same failure wearing different clothes. `discover` once ended in a bare
`return found[:max_findings]`: real findings the run had already paid for were deleted, rounds
2..5 never ran, every health check still saw a healthy run, and the exit code was the one
SKILL.md defines as "Complete. The JSON array is the whole result."

The disposition rules come from the same principle applied per finding. Zero verdicts is not
unanimous refutation, it is no information, and treating the two alike is a silent delete on
error. An uncited or uncorroborated spec claim is not evidence either — on a fixture holding
two `.js` files and no knowledge-base, one skeptic cited an invented spec path and another
cited the sentence "No /knowledge-base/specs found in repo", and both downgraded live
vulnerabilities.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-131 A run in which no task got a usable answer is never reported as clean — it exits 2 with the last error, instead of an empty array at exit 0 | proposed | `test_audit.py#MainTest.test_a_run_where_every_finder_failed_is_never_reported_as_clean` (unittest) |
| BEH-132 A run where only some tasks answered is reported INCOMPLETE at exit 3 — naming how many, the last error, and how much of the surviving evidence completed verification — with the survivors still printed | proposed | `test_audit.py#DegradedRunTest.test_a_mostly_failed_run_is_reported_as_incomplete` (unittest) |
| BEH-133 A run whose discovery was cut short — by the findings cap or by the call ceiling — exits 3 saying what it discarded and that the remaining rounds never ran, and still reports what it had already paid to verify | proposed | `test_audit.py#TruncatedDiscoveryTest.test_a_cap_that_discarded_findings_is_never_reported_as_complete` (unittest) |
| BEH-134 A finding is never dropped for lack of information — with no verdicts it settles as needs-review, and only a unanimous refutation removes it | proposed | `test_audit_engine.py#DispositionTest.test_no_verdicts_is_needs_review_not_drop` (unittest) |
| BEH-135 A finding explained by an accepted behavior is reclassified in place — `status: intentional` with a `behavior_ref` and the query's evidence label, still listed in the report and in `findings.json` — and is never deleted | proposed | **no test** — `test_findings_index.py#DowngradeTest.test_a_behavior_explained_finding_is_reclassified_not_removed` is where one belongs (manual) |

Each of the first four is one guarantee with several edges:

- BEH-131's other entry point is `…MainTest.test_a_failed_context_call_stops_before_the_finders_run`
  — the context call is call #1, and if it fails every downstream call will too.
- BEH-132's honesty half is `…BannerHonestyTest.test_a_banner_never_claims_a_verification_that_did_not_happen`,
  with `…test_a_fully_verified_degraded_run_says_so` and `…test_a_partly_verified_run_counts_both_sides`
  on the wording itself; `…DegradedRunTest.test_a_fully_answered_run_is_not_flagged_incomplete`
  is the control that stops the guard from firing on every run.
- BEH-133's second trigger is `…MainTest.test_exhausting_the_budget_keeps_the_findings_already_verified`,
  its zero-discarded edge is `…TruncatedDiscoveryTest.test_a_cap_that_discarded_nothing_is_still_not_a_complete_sweep`
  (rounds 2..5 still never ran, so the sweep is still incomplete), and
  `…test_a_run_that_went_dry_under_the_cap_is_complete` is the control — without it the fix
  could simply be "always INCOMPLETE".
- BEH-134's companions are `…DispositionTest.test_unanimous_refute_is_dropped`,
  `…test_an_uncited_spec_refute_does_not_claim_intentional_design`, and
  `…SpecCitationTest.test_a_fabricated_path_does_not_buy_intentional_design`.

**BEH-135 is the gap, and it is the largest one in this area.** The downgrade rule is
authoritative (ADR-012) and its deterministic half is enforced — `behavior-graph --covering`
filters to `state == "accepted"` before the agent judges anything — but the part this behavior
names, that the downgraded finding survives in the report and in `findings.json` as a
reclassified row rather than a removed one, lives entirely in SKILL.md prose and in
`references/findings-schema.md`. No code writes `findings.json` and no test asserts its shape,
so nothing anywhere fails if a future report loop drops a downgraded finding instead of
restating it, or emits an index whose ids and statuses disagree with the prose report the schema
says it mirrors exactly. `freya-status` consumes that file.

Also worth recording as a known dead branch rather than a behavior: the skill's disposition
table documents `mitigated`, and no code path in the engine emits it (ADR-015 lists this in its
revisit conditions).

## Intentional Design Decisions

### Exit 3 is its own code, and exit 1 means exactly one thing

**Decision**: `EXIT_INCOMPLETE = 3` is distinct from both success and failure, and
`EXIT_NOTHING_TO_DO = 1` now means only "no agent CLI on PATH", with the confirmation refusal
moved to 4.

**Rationale**: The consumer is an agent following the exit table in SKILL.md, so "incomplete"
has to be readable without parsing stderr prose. Exit 1 was split because a perfectly healthy
driver that merely declined to spend money unattended was read as a missing CLI, and the agent
silently reverted to the prose fan-out the driver exists to replace.

**Security Scan Note**: The several distinct non-zero exit codes are a documented contract, not
inconsistent error handling. Collapsing them re-creates a real incident.

### No information is not a refutation

**Decision**: `disposition([])` returns `needs-review` with `verification.total = 0`, and the
`upheld == 0 → drop` branch is only reachable once at least one lens has answered.

**Rationale**: ADR-015 records this as a deliberate divergence from the retired JS engine, whose
empty-verdict path reached `upheld == 0` and deleted the finding. The skill's rule is that only
a *unanimous refutation* drops.

**Security Scan Note**: A branch that treats "no data" differently from "zero votes in favour"
is intentional and must not be simplified into one comparison. `verification.lenses` reporting
only the lenses that answered — rather than the `SKEPTICS` constant — is the same decision.

### An uncorroborated citation is not a citation

**Decision**: A `spec-intentional` refutation only outranks the majority when
`resolve_spec_reference` finds the cited document inside the project, or finds the cited
`SPEC-`/`ADR-`/`BEH-` id mentioned in a prose file under it. Anything else falls through to the
ordinary vote.

**Rationale**: ADR-015 — requiring `specReference` to be merely non-empty is no guard when the
model writes the field, and both agents were observed inventing one to downgrade a live
finding.

**Security Scan Note**: This code joins a model-supplied string onto a filesystem path, which is
a legitimate thing to flag and is deliberately bounded: the candidate is `realpath`'d and
rejected unless `commonpath` puts it inside the project, only `isfile` is called on it (its
contents are never read), and the id search walks at most `_MAX_SCANNED` (400) prose files under
four fixed roots. The traversal case is pinned by
`…SpecCitationTest.test_a_citation_may_not_escape_the_project`.

### A duplicate is annotated, never merged away

**Decision**: Findings sharing a five-line window under *different* categories keep their own
rows and gain a `colocated` list naming the others; the category stays in the dedup key.

**Rationale**: ADR-002 ownership — ADR-015 records the decision and the live case behind it.
The short version: between a visible duplicate and a silent deletion, a security tool takes the
duplicate.

**Security Scan Note**: Apparent double-counting in a report is intentional, and the annotation
is applied *after* the drop filter so a survivor is never told it shares a location with a
finding the skeptics just deleted.

### A downgrade reclassifies; nothing deletes a finding from the report

**Decision**: The strongest evidence available — an `accepted` behavior whose locator resolves
to a file in the project and whose exercised path was `observed` rather than inferred — changes
a finding's `status` to `intentional` and attaches
a `behavior_ref` plus the query's `evidence` string, copied verbatim. It does not remove the
finding from the prose report or from `findings.json`, and `proposed`/`confirmed` behaviors may
annotate but never silence.

**Rationale**: ADR-012, and its two 2026-08-24 corrections for what the evidence is and is not.

**Security Scan Note**: A finding that a scan has already explained still appearing in the
report is the audit trail working as designed. Its absence from the *outstanding* count is
where the silencing shows up, and it is reversible because the named behavior, its locator and
the symbols the run touched are all recorded for a reader to check. On a row the scan did not
verify, that is still a different and weaker claim than "its test passed": both inputs came from
the repository being audited, and `observed` means a test passed once, on somebody's machine, at
the commit `freshness` names. Read `verified.passed` before reading a `behavior_ref` as
verification — on a row where it is false, the behavior is evidence against itself.

## Related Specs

- [SPEC-025: Read-Only Audit Workers and Agent Selection](./SPEC-025-read-only-audit-workers.md) —
  the workers whose answers this spec is about
- [SPEC-026: The Security Scan Spend Gate](./SPEC-026-security-scan-spend-gate.md) — the
  ceiling whose exhaustion triggers half of BEH-133

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests | Brownfield scan (`freya-spec-manager bootstrap`) |
| 2026-08-24 | Struck "test-backed" from the downgrade rule in three places (BEH-135's title, the *What* section and the design decision) and replaced it with what `--covering` actually establishes: state and a resolving locator re-derived from project-supplied files, carried into the report as a labelled `evidence` string. | SEC-006. This spec exists to stop a run claiming more than it checked, and its own downgrade rule was doing exactly that — no test is run by a downgrade, and every consumer that inherited the phrase from ADR-012 read it as one. |
| 2026-08-24 (later) | Rewrote the *What* section and the design decision again: a downgrade now also requires `source: observed` and a locator that is present rather than merely valid-if-declared, and `--covering --verify` re-runs the linked test, which the scan passes. | The row above was written on the premise that no better evidence could exist, because running the audited repository's tests would be arbitrary code execution. The user overturned that premise: freya is pointed at a repository its operator works in, and `freya-behavior-runner` ships to run that repository's tests. Closing SEC-006 properly then found the wider hole — a `static` edge, inferred from the import graph with no test involved, licensed a downgrade exactly as a recorded run did. |

---

*Certainty 78 — the lowest of the three specs in this area, and deliberately so. The driver's
own guarantees (BEH-131..134) are as well-evidenced as anything here: each guard carries a
comment naming the incident and the numbers behind it, each has a test whose docstring repeats
the failure, and each has a control test proving the guard is not simply always-on. But
BEH-135 is a guarantee this project states in three places and enforces nowhere in code, so the
spec as a whole describes a rule the codebase only half keeps — and the `mitigated` disposition
is documented and unreachable, which is a smaller instance of the same thing.*
