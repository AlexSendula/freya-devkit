#!/usr/bin/env python3
"""The audit engine: exhaustive discovery, then adversarial verification.

Ported from the JS engine retired in Phase 4b, which ran on a Claude-only
saved-script automation feature. All control flow is here; the only injected
pieces are `ask` (one LLM call) and `run` (how to execute a list of thunks).
That is what makes the engine testable offline and agent-agnostic.

Contract, unchanged from the JS: this returns deduped, verified findings. It
does NOT write the report, assign SEC-### IDs, or re-evaluate previous
findings — the skill's main loop does all of that.
"""

from __future__ import annotations

import os
import posixpath
import re
from collections import namedtuple

from audit_io import CATEGORIES, FINDER_SCHEMA, SKEPTICS, VERDICT_SCHEMA, redact_secret_evidence

K_EMPTY = 2       # consecutive dry rounds that stop discovery
MAX_ROUNDS = 5    # budget guard
VERIFY_BATCH = 8  # findings settled per flat wave of skeptic calls

#: What `discover` and `audit` hand back. `discarded`/`capped` are not
#: decoration: phase 7 review found `discover` ending in a bare
#: `return found[:max_findings]`, which voided loop-until-dry, threw away
#: findings the run had already paid for, and still let the driver exit 0 —
#: the code SKILL.md defines verbatim as "clean". A count that has to be
#: unpacked to reach the findings cannot be dropped on the floor the way a
#: log line or an optional callback can. `capped` is true whenever the cap
#: ended discovery, including when it discarded nothing: the remaining rounds
#: still never ran, so the codebase was still not swept.
Result = namedtuple("Result", "findings discarded capped")


class Halted(Exception):
    """The injected `ask` refuses further calls — stop, but keep what we have.

    The engine does not know *why* (the driver raises a subclass when its call
    budget runs out); it only knows that continuing is not permitted. Catching
    this rather than letting it unwind is what lets a truncated run return the
    findings it already paid to verify.
    """


class ContextUnavailable(Exception):
    """The context call produced nothing, so no finder prompt can be grounded.

    Raised rather than continuing with `Context: None`: if the very first call
    fails, every downstream call will fail too, and a run of empty finders is
    indistinguishable from a clean codebase.
    """

CONTEXT_PROMPT = (
    "Read /knowledge-base/reference and /knowledge-base/specs (if present). Summarize: "
    "architecture, auth model, trust boundaries, untrusted entry points, and an explicit "
    "list of SPEC'D-INTENTIONAL behaviors that must NOT be reported as vulnerabilities. "
    "Return prose."
)


def normalize_file(path):
    """A finding's file, as a stable identity.

    Phase 6 validation watched a live Copilot run report one SQL injection
    twice — once as `./src/auth.js`, once as `src/auth.js`. Two strings, two
    dedup keys, so both survived, and one of only three verification slots was
    spent re-litigating a duplicate. Workers write paths however they please;
    the engine decides what counts as the same file.

    posixpath, not os.path, and backslashes folded in by hand: this value is
    written back into the finding and travels into the report, where SKILL.md
    cross-references it against a behavior graph keyed on forward slashes. On
    Windows `os.path.normpath` rewrites every path to backslashes, so that
    cross-reference never matches and the shipped dedup test goes red — a
    finding then loses its accepted-behavior downgrade purely because of the
    host that ran the scan. A worker may also *report* a Windows path on any
    host, which is why the fold is unconditional.
    """
    return posixpath.normpath(str(path).replace("\\", "/")) if path else path


def place_key(finding):
    """A finding's location, to a five-line window."""
    return f"{normalize_file(finding['file'])}::{int(finding['line']) // 5}"


def dedup_key(finding):
    """Same file + same five-line window + same category collapse to one finding."""
    return f"{place_key(finding)}::{finding['category']}"


def annotate_colocated(findings):
    """Mark findings that share a location but arrived under different categories.

    Live on the phase 7 fixture: the `auth` finder and the `injection` finder
    both reported the SQL injection at `src/auth.js:5`, so the run carried one
    vulnerability as two findings and spent six verification calls on it. The
    same fixture at `--concurrency 1` produced only one, so this is not even
    reproducible — a user cannot predict whether their report double-counts.

    Deliberately NOT fixed by dropping category from the dedup key. Two
    genuinely different issues can share a five-line window (a hardcoded key on
    one line, an injection on the next), and merging them blind would delete
    one without a word. Between a visible duplicate and a silent deletion, a
    security tool takes the duplicate. So the engine states the ambiguity and
    the skill's report loop, which has the titles and descriptions in front of
    it, decides whether they are one issue.
    """
    groups = {}
    for item in findings:
        groups.setdefault(place_key(item), []).append(item)
    return [
        {**item, "colocated": sorted({other["category"]
                                      for other in groups[place_key(item)]
                                      if other is not item})}
        for item in findings
    ]


#: Paths a citation may name. A spec lives in prose, not in source.
_CITED_PATH = re.compile(r"[\w./\\-]+\.(?:md|markdown|rst|txt|ya?ml|json)\b")
#: spec-manager's identifier shapes, and only those: SPEC-007, ADR-003, BEH-012.
#: `[A-Z]{2,6}-\d+` also matched CWE-89, CVE-2021, RFC-7231, ISO-9001, AES-256
#: and this tool's own SEC-### finding ids. Measured against this repository on
#: 2026-08-23: every one of those corroborated a citation. No attacker is needed
#: to reach it — a finding's `cwe` field is interpolated verbatim into the
#: skeptic prompt, so "per CWE-89 this is the accepted pattern" is a downgrade a
#: worker arrives at by paraphrasing its own input. SPEC-027 names these three
#: prefixes and no others; the code was wider than the decision it implements.
#:
#: Non-capturing group deliberately. `(SPEC|ADR|BEH)-\d+` makes `findall` return
#: the bare prefix, so the walk below would search a body for "ADR" instead of
#: "ADR-003" — looser than the pattern this replaced, not stricter.
_CITED_ID = re.compile(r"\b((?:SPEC|ADR|BEH)-\d{1,6})\b")
#: Where a corroborating document is allowed to live, cheapest first.
_SPEC_ROOTS = ("knowledge-base", "docs", "specs", ".")
_SPEC_SUFFIXES = (".md", ".markdown", ".rst", ".txt")
#: A whole tree is not worth walking to check one citation.
_MAX_SCANNED = 400
#: Where this skill puts its own reports, relative to a project root. One
#: constant because *both* branches of `resolve_spec_reference` have to skip the
#: same directory and they used not to: the id branch pruned it, the path branch
#: did not, so the invariant held for the harder of the two ways in and not for
#: the easier one. Two literals is how that drifts back apart.
_OWN_REPORTS = ("knowledge-base", "security")


def _own_reports_dir(root):
    """The directory holding this skill's own output, ready to compare.

    Lexical and normcase'd, matching how both callers spell their paths.
    `os.path.realpath` is not applied and the residual is the same one
    `_project_mentions` already states: a project that keeps these reports
    somewhere else — including behind a symlink at this path — is still its own
    witness, and no amount of normalising here finds them.
    """
    return os.path.normcase(os.path.join(root, *_OWN_REPORTS))


def resolve_spec_reference(reference, project):
    """Return the citation if the project corroborates it, else None.

    Requiring `specReference` to be merely non-empty is no guard when the model
    writes the field. Live on a fixture holding two .js files and no
    knowledge-base, a skeptic cited
    `/knowledge-base/specs/authentication.md#trusted-inputs-and-normalization`
    and downgraded a real SQL injection to `intentional-design`; another cited
    the sentence *"No /knowledge-base/specs ... found in repo"* and downgraded a
    hardcoded production credential at `upheld 0/3`. Both paths were invented.

    Corroboration is deliberately cheap and local: either the citation names a
    document that exists inside the project, or it names a spec ID that appears
    in one. Anything else falls through to the ordinary vote — an unverifiable
    claim must not outrank three skeptics.

    Neither branch will accept this skill's own reports: see `_OWN_REPORTS`. The
    path branch needs that at least as much as the id branch does, and probably
    more — the report file genuinely exists, so a skeptic that can list a
    directory can cite a real path, where the id branch needed last month's
    report to happen to name the id it wanted.
    """
    text = str(reference or "").strip()
    if not text or not project:
        return None
    root = os.path.realpath(project)
    own_reports = _own_reports_dir(root)

    for match in _CITED_PATH.finditer(text):
        candidate = match.group(0).split("#", 1)[0].replace("\\", "/")
        target = os.path.realpath(os.path.join(root, candidate.lstrip("/")))
        # `../../etc/passwd` exists everywhere and says nothing about intent.
        if os.path.commonpath([root, target]) != root:
            continue
        # Neither does a report this tool wrote. Prefix test rather than
        # equality: every report sits a directory or two down, under
        # `codebase-security/` or `dependency-vulnerabilities/`.
        normalized = os.path.normcase(target)
        if normalized == own_reports or normalized.startswith(own_reports + os.sep):
            continue
        if os.path.isfile(target):
            return text

    ids = _CITED_ID.findall(text)
    if ids and _project_mentions(root, ids):
        return text
    return None


def _project_mentions(root, ids):
    """True if any identifier appears in a prose file under the project.

    Except in this skill's own reports. They live under `_OWN_REPORTS` and each
    one names every id it discusses — including the invented ones it quotes out
    of a test — so left in the walk, last month's report corroborates this
    month's citation. Measured on this repository on 2026-08-23 with the
    namespace above already narrowed: `SPEC-999` still resolved, and its only
    occurrence anywhere in the tree is a report sentence saying it must not.
    Narrowing the prefixes does not close that on its own, because a report
    carries SPEC-/ADR-/BEH- ids too. The tool does not get to be its own witness
    — and this half of that is only half: `resolve_spec_reference` skips the
    same directory on the path branch, and until it did, the invariant this
    paragraph asserts was false for the more reachable of the two.

    Lexical, not `containment.within`: `root` reaches this function already
    realpath'd (`resolve_spec_reference`), and `os.walk` does not descend a
    symlinked directory, so there is no path here that a `realpath` could
    disagree with — two syscalls per directory to learn nothing.

    Pruned to exactly that directory. A scanned project that keeps these reports
    somewhere else is still its own witness, and pruning every directory *named*
    `security` would throw away a third party's genuine threat-model prose,
    which is the corroboration this function exists to find.
    """
    reports = _own_reports_dir(root)
    scanned = 0
    for start in _SPEC_ROOTS:
        base = os.path.join(root, start)
        if not os.path.isdir(base):
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if not d.startswith(".")
                           and os.path.normcase(os.path.join(dirpath, d)) != reports]
            for name in filenames:
                if not name.endswith(_SPEC_SUFFIXES):
                    continue
                scanned += 1
                if scanned > _MAX_SCANNED:
                    return False
                try:
                    with open(os.path.join(dirpath, name), encoding="utf-8",
                              errors="replace") as handle:
                        body = handle.read()
                except OSError:
                    continue
                if any(i in body for i in ids):
                    return True
            if start == ".":
                break  # the project root itself, not every source directory
    return False


def disposition(verdicts, project=None):
    """Return (disposition, spec_reference, verification) for one finding.

    A spec-intentional refutation outranks the majority *when it cites a spec*:
    if the behaviour is specified, it is a design decision rather than a
    vulnerability. The citation is load-bearing, not a nicety — phase 7 review
    found an uncited spec refutation claiming `intentional-design` anyway, which
    both asserts a design decision nobody pointed at and made the documented
    `drop` path unreachable whenever all three lenses answered: a unanimous
    refutation always contains a spec refutation, so it short-circuited here and
    a finding every skeptic rejected was reported as intentional design.

    Divergence from the retired JS: with zero verdicts (every skeptic call
    failed) the JS reached `upheld == 0` and dropped the finding. That is a
    silent delete on error. The skill's rule is that only a *unanimous
    refutation* drops a finding, so no-information now yields needs-review.
    """
    verdicts = [v for v in verdicts if v]
    upheld = sum(1 for v in verdicts if v.get("verdict") == "upheld")
    total = len(verdicts)
    # The lenses that ANSWERED, not the ones we asked — and, because `_settle`
    # binds each slot to the lens it was REQUESTED for, named by the question
    # put to them rather than by whatever the answer called itself. This used to
    # be the SKEPTICS constant, so a timed-out exploitability call still read
    # `Upheld 2/2 · <all three>`. Ordered by SKEPTICS, so the row is stable.
    answered = {v.get("lens") for v in verdicts}
    verification = {"upheld": upheld, "total": total,
                    "lenses": [lens for lens in SKEPTICS if lens in answered]}

    # A citation the project cannot corroborate is not a citation: see
    # resolve_spec_reference. With no project to check against, behaviour is
    # unchanged rather than silently stricter — the driver always passes one.
    for v in verdicts:
        if v.get("lens") != "spec-intentional" or v.get("verdict") != "refuted":
            continue
        cited = str(v.get("specReference") or "").strip()
        if not cited:
            continue
        if project and not resolve_spec_reference(cited, project):
            continue
        return "intentional-design", v.get("specReference"), verification
    if total == 0:
        return "needs-review", None, verification
    if upheld * 2 > total:
        return "confirmed", None, verification
    if upheld == 0:
        return "drop", None, verification
    return "needs-review", None, verification


def discover(ask, context, run, *, max_findings=None, max_rounds=MAX_ROUNDS,
             on_round=None):
    """Loop the six category finders until K_EMPTY dry rounds or `max_rounds`.

    Second divergence from the retired JS: it filtered a whole round against
    `seen` *before* adding anything, so two finders reporting the same issue in
    the same round both survived. Keys are added as they are seen here, so an
    intra-round duplicate collapses like a cross-round one does. Deduping is
    the point of the key; the JS only ever applied it across rounds.

    `max_rounds` is what separates the `scan` preset (1) from `audit`
    (MAX_ROUNDS). It is the only knob the preset turns: cutting *skeptics*
    instead would be cheaper still and actively dangerous, because with one
    lens a single refutation reaches `upheld == 0` and drops a real finding.
    K_EMPTY is untouched — irrelevant at one round, load-bearing at five.

    Returns a `Result`, never a bare list: hitting `max_findings` means real
    findings were discarded and the remaining rounds never ran, and a caller
    that cannot see that reports a half-swept codebase as a finished one.
    """
    seen = set()
    found = []
    dry = 0
    rounds = 0

    while dry < K_EMPTY and rounds < max_rounds:
        rounds += 1
        known = sorted(seen)

        def finder(category):
            def thunk():
                return ask(
                    f"Category: {category}. Context: {context}. "
                    f"Already found (skip these dedup keys): {known}. "
                    f"Exhaustively scan the codebase for NEW {category} vulnerabilities "
                    f"on uncovered surface. Return {{ findings: [...] }} matching the "
                    f"schema; empty array if nothing new.",
                    schema=FINDER_SCHEMA,
                )
            return thunk

        results = run([finder(c) for c in CATEGORIES])

        fresh = []
        for result in results:
            if not result:
                continue
            for item in result.get("findings", []):
                # Normalize on the way in, not just inside the key: a report
                # listing the same file as both `./src/a.js` and `src/a.js`
                # reads like two places even once deduping is correct.
                #
                # Redact on the way in for a different reason. A secrets
                # finding's `codeSnippet` leaves this engine by three doors —
                # the skeptic prompt below, which the driver passes as an argv
                # element and every local user can read out of a process
                # listing; the driver's stdout; and the report the agent writes
                # from that stdout and then commits. This is the one door it
                # comes in by. Patching the three exits is three chances to
                # miss one, and the one missed is the one that commits it.
                item = redact_secret_evidence(
                    {**item, "file": normalize_file(item.get("file", ""))})
                if dedup_key(item) not in seen:
                    seen.add(dedup_key(item))
                    fresh.append(item)

        if not fresh:
            dry += 1
            if on_round:
                on_round(rounds, 0, len(found), dry)
            continue

        dry = 0
        found.extend(fresh)
        if on_round:
            on_round(rounds, len(fresh), len(found), dry)
        if max_findings is not None and len(found) >= max_findings:
            return Result(found[:max_findings], len(found) - max_findings, True)

    return Result(found, 0, False)


def _skeptic(finding, lens, ask, context):
    def thunk():
        return ask(
            f"Finding: {finding}. Spec-intentional context: {context}. Lens: {lens}. "
            f"Your job is to REFUTE this finding, not confirm it. Return verdict "
            f'"refuted" or "upheld" with a reason (and specReference if '
            f"spec-intentional).",
            schema=VERDICT_SCHEMA,
        )
    return thunk


def _bind_lenses(verdicts):
    """Attribute each verdict to the lens it was REQUESTED for, not the one it
    claims, and count the mismatches.

    Both call sites submit one thunk per lens in `SKEPTICS` order, so slot j IS
    `SKEPTICS[j]` — and that was thrown away. `disposition` re-derived the lens
    from each answer's own `lens` key and nothing compared the two, so a worker
    handed the *exploitability* question could answer `lens: spec-intentional`
    with a `specReference` and cast the single-lens veto that outranks a
    majority: three attempts at the veto per finding instead of the one the
    design intends. No attacker is needed to reach it. The three prompts differ
    by one word, VERDICT_SCHEMA offers all three names to every worker, and
    every worker is asked for a specReference. The same field builds
    `verification.lenses`, so one mislabel also made a report name a lens that
    never answered.

    Bound by POSITION on the RAW slice, before `disposition` drops the falsy
    entries. A failed call leaves `None` in its slot, and binding the filtered
    list slides every later lens one place to the left — promoting
    compensating-controls into slot 0 and carrying spec-intentional out of the
    slot where the veto is decided.

    Mismatches are rewritten and counted, never dropped. Discarding an upheld
    answer can leave an all-refuted remainder, and a finding every remaining
    skeptic refuted is dropped — so dropping here would delete real findings on
    the strength of a labelling mistake.
    """
    bound = []
    mislabeled = 0
    for index, verdict in enumerate(verdicts):
        # A slot past SKEPTICS was never requested, so there is no lens to bind
        # it to. Pass it through rather than silently dropping an answer.
        if not verdict or index >= len(SKEPTICS):
            bound.append(verdict)
            continue
        if verdict.get("lens") != SKEPTICS[index]:
            mislabeled += 1
        bound.append({**verdict, "lens": SKEPTICS[index]})
    return bound, mislabeled


def _settle(finding, verdicts, project=None):
    bound, mislabeled = _bind_lenses(verdicts)
    disp, spec_reference, verification = disposition(bound, project)
    if mislabeled:
        # Annotated here rather than inside `disposition`, which twenty-seven
        # tests call directly with hand-ordered lists and one of them asserts by
        # whole-dict equality. Absent on a clean run, so the documented
        # `{upheld, total, lenses}` shape is unchanged for every consumer that
        # never meets a mislabel.
        verification = {**verification, "mislabeled": mislabeled}
    return {**finding, "disposition": disp, "specReference": spec_reference,
            "verification": verification}


def verify(finding, ask, context, run, *, project=None):
    """Run every skeptic lens against one finding and settle its disposition."""
    return _settle(finding, run([_skeptic(finding, lens, ask, context)
                                 for lens in SKEPTICS]), project)


def verify_all(findings, ask, context, run, *, on_settled=None, project=None):
    """Settle findings in flat waves of VERIFY_BATCH x len(SKEPTICS) calls.

    One wave per batch rather than one wave per finding: the JS ran every
    finding's skeptics concurrently, and verifying three calls at a time wastes
    most of a pool. Batching rather than one single wave is what makes a
    `Halted` mid-verification cost at most one batch instead of everything.

    Note the thunks are flat. Calling `run` from inside a thunk that `run` is
    already executing would let a bounded pool deadlock on itself.

    CONTRACT: `run` MUST return results in submission order. The wave is
    regrouped by index below, so a `run` that returned completion order would
    hand every finding its neighbour's verdicts — and a finding whose
    neighbours were refuted then reaches `upheld == 0` and is dropped before it
    can leave the engine. The driver's pool test pins this.
    """
    settled = []
    width = len(SKEPTICS)
    try:
        for start in range(0, len(findings), VERIFY_BATCH):
            batch = findings[start:start + VERIFY_BATCH]
            results = run([_skeptic(f, lens, ask, context)
                           for f in batch for lens in SKEPTICS])
            settled.extend(_settle(f, results[i * width:(i + 1) * width], project)
                           for i, f in enumerate(batch))
            if on_settled:
                on_settled(len(settled), len(findings))
    except Halted as halt:
        halt.settled = settled  # completed batches survive the unwind
        raise
    return settled


def audit(ask, run, *, max_findings=None, max_rounds=MAX_ROUNDS,
          on_round=None, on_settled=None, project=None):
    """Full audit. Returns a `Result` whose findings are survivors only —
    dropped findings never leave here.

    On `Halted` the work already paid for is returned rather than discarded.
    Callers tell a *budget* halt from a complete run by asking whatever raised
    (the driver checks its Budget); they tell a *discovery* truncation from a
    complete sweep by reading `discarded`/`capped` off this result, because
    nothing else on the way out records it.
    """
    context = ask(CONTEXT_PROMPT)
    if not context:
        raise ContextUnavailable(
            "the context call returned nothing, so no finder can be grounded"
        )

    try:
        found = discover(ask, context, run, max_findings=max_findings,
                         max_rounds=max_rounds, on_round=on_round)
    except Halted:
        # Nothing has been verified yet, so there is nothing to keep. Not
        # `capped`: the budget halted this, and the driver reports that itself.
        return Result([], 0, False)

    try:
        verified = verify_all(found.findings, ask, context, run,
                              on_settled=on_settled, project=project)
    except Halted as halt:
        verified = getattr(halt, "settled", [])

    # Annotate after the drop filter, never before: a survivor must not be told
    # it shares a location with a finding the skeptics just deleted.
    survivors = annotate_colocated([v for v in verified if v["disposition"] != "drop"])
    return Result(survivors, found.discarded, found.capped)
