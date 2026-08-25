#!/usr/bin/env python3
"""
behavior-graph — owns behavior.json (the generated BEHAVIOR → TEST → CODE
projection). Builds it by projecting spec frontmatter, orchestrating
behavior-runner for fingerprints, and merging by trust; serves Direction A
(code change → affected behaviors) and Direction B (behavior → code).

Pure graph layer: it queries code-graph and behavior-runner (sibling skills);
code-graph stays unaware of behaviors (vision §5b).
"""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

# Reuse the freya-spec-manager frontmatter parser (stdlib-only).
_SPEC_SCRIPTS = Path(__file__).resolve().parents[2] / "freya-spec-manager" / "scripts"
sys.path.insert(0, str(_SPEC_SCRIPTS))
import frontmatter  # noqa: E402
from frontmatter import FrontmatterError  # noqa: E402
from adapters import parse_locator  # noqa: E402  (covering() splits a spec locator)

# The containment rule is owned by freya-code-graph and imported, not copied
# (ADR-030). `covering()` joins a project-supplied locator onto the project path,
# and a second body of that predicate is one that disagrees with the first at the
# margin — which is exactly where it matters.
_GRAPH_SCRIPTS = Path(__file__).resolve().parents[2] / "freya-code-graph" / "scripts"
sys.path.insert(0, str(_GRAPH_SCRIPTS))
from containment import escapes  # noqa: E402

_RUNNER = Path(__file__).resolve().parents[2] / "freya-behavior-runner" / "scripts" / "run_behaviors.py"
_CODE_GRAPH = Path(__file__).resolve().parents[2] / "freya-code-graph" / "scripts" / "graph_ops.py"

_RUNNER_SCRIPTS = Path(__file__).resolve().parents[2] / "freya-behavior-runner" / "scripts"
sys.path.insert(0, str(_RUNNER_SCRIPTS))
import run_behaviors  # noqa: E402  (reused for load_behaviors — reads proposed from specs)

_PROJECTED_FIELDS = ("state", "level", "adapter", "locator")


def merge_fingerprint(prior, incoming):
    """Merge a prior coverage-part with an incoming runner fingerprint by trust.

    observed > static; a test-failed run invalidates; any other unknown reason
    preserves the prior fingerprint. Coverage-parts are {coverage, exercises, reason?}.
    """
    cov = incoming.get("coverage")
    if cov == "observed":
        return {"coverage": "observed", "exercises": list(incoming.get("exercises", []))}
    if cov == "static":
        if prior and prior.get("coverage") == "observed":
            return {"coverage": "observed", "exercises": list(prior.get("exercises", []))}
        return {"coverage": "static", "exercises": list(incoming.get("exercises", []))}
    # unknown
    if incoming.get("reason") == "test-failed":
        return {"coverage": "unknown", "exercises": [], "reason": "test-failed"}
    if prior:
        part = {"coverage": prior.get("coverage", "unknown"), "exercises": list(prior.get("exercises", []))}
        if "reason" in prior:
            part["reason"] = prior["reason"]
        return part
    out = {"coverage": "unknown", "exercises": []}
    if incoming.get("reason") is not None:
        out["reason"] = incoming["reason"]
    return out


def project_behaviors(specs_dir):
    """Map BEH-NNN -> projected frontmatter fields for every accepted or
    confirmed behavior (proposed is excluded)."""
    out = {}
    for root, _dirs, files in os.walk(specs_dir):
        for name in files:
            if not name.endswith(".md"):
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8") as f:
                    fm, _body = frontmatter.parse_frontmatter(f.read())
            except (FrontmatterError, UnicodeDecodeError, OSError):
                # A read failure is not a frontmatter failure. Strict UTF-8 decoding means
                # one spec with a stray byte raised out of this walk entirely, taking the
                # whole behaviour projection with it — one bad file must cost one file.
                continue
            for b in fm.get("behaviors") or []:
                # accepted (authoritative) + confirmed (advisory, test owed) both
                # belong in the graph so Direction A/B can see them; proposed does
                # not (it is not confirmed intent). confirmed never gates because
                # the runner never executes it (design 03 §3).
                if not isinstance(b, dict) or b.get("state") not in ("accepted", "confirmed"):
                    continue
                bid = b.get("behavior_id")
                if not bid:
                    continue
                rec = {"spec_id": fm.get("id")}
                for key in _PROJECTED_FIELDS:
                    rec[key] = b.get(key)
                out[bid] = rec
    return out


def _behavior_json_path(project_dir):
    return os.path.join(project_dir, "knowledge-base", ".graph", "behavior.json")


def load_behavior_json(project_dir):
    path = _behavior_json_path(project_dir)
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}


# Kept byte identical to graph_ops.py's copy — whichever skill runs first writes
# the file, so a drift between the two would make its contents depend on run order.
CACHE_IGNORED = ("graph.json", "graph.*.json", "classifications.json", "docs.json")

CACHE_GITIGNORE = (
    "# Generated code-graph cache — do not commit.\n"
    "#\n"
    "# behavior.json is deliberately NOT listed. Its observed coverage is captured\n"
    "# by running the test suite, so it cannot be rebuilt by re-reading source the\n"
    "# way these can — committing it is what gives a fresh clone a blast radius.\n"
    "#\n"
    "# graph.*.json is the per-backend artifact (ADR-028): each substrate writes its own,\n"
    "# so a swap can be diffed instead of destroying the baseline it should be measured\n"
    "# against. graph.json stays the active graph that other skills read.\n"
    "#\n"
    "# docs.json is the doc-section -> code edge set. Parsed from the markdown that is\n"
    "# already committed, so it is regenerable in the same sense the graph is.\n"
    + "\n".join(CACHE_IGNORED) + "\n"
)


# Every entry this file has ever contained. A file listing only these was written by us and
# can be upgraded in place; one containing anything else was edited by hand and is left alone.
#
# Without this history the upgrade only fired on the legacy `*`, so a project that had run a
# single build kept its list forever — and every artifact added afterwards arrived un-ignored
# and committable. ADR-028's graph.<backend>.json did exactly that: `git add -A` staged it.
_EVER_IGNORED = frozenset({"*", "graph.json", "graph.*.json",
                          "classifications.json", "docs.json"})


def _is_ours(text):
    """Did we write this file? True for any version of it we have ever produced."""
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    return bool(lines) and all(line in _EVER_IGNORED for line in lines)


def _is_legacy_blanket_ignore(text):
    """True for the pre-0.2.1 `*` file, whichever skill wrote it."""
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.lstrip().startswith("#")]
    return lines == ["*"]


def _write_cache_gitignore(path):
    """Write the cache .gitignore, upgrading a legacy blanket but never a custom one."""
    try:
        if os.path.exists(path):
            with open(path, encoding="utf-8", errors="replace") as f:
                if not _is_ours(f.read()):
                    return
    except OSError:
        return
    with open(path, "w", encoding="utf-8") as f:
        f.write(CACHE_GITIGNORE)


def _stable(data):
    """Return `data` with the behaviors mapping and every exercise list in a fixed order.

    behavior.json is committed, so it has to be byte-stable: two builds of
    unchanged input must produce an identical file or every rebuild shows a
    spurious diff. The static edges come from code-graph's import closure, which
    is assembled from a set — proven to vary run to run in ordering while being
    identical in content. Sorting here is the single choke point that fixes it
    for every producer.

    The *keys* needed the same treatment and did not get it. `project_behaviors` fills the
    mapping in `os.walk` dirent order, which is directory order on APFS and hash order on
    ext4 — so the same specs produced a different key order on a colleague's machine or in
    CI, and `json.dump(..., indent=2)` preserved it. That is a whole-file diff on a tracked
    artifact whose diffs are supposed to *mean* something: behaviour drift is what a change
    to this file is read as.
    """
    behaviors = data.get("behaviors")
    if not isinstance(behaviors, dict):
        return data
    for entry in behaviors.values():
        ex = entry.get("exercises") if isinstance(entry, dict) else None
        if isinstance(ex, list):
            entry["exercises"] = sorted(
                ex, key=lambda e: e.get("path", "") if isinstance(e, dict) else str(e))
    data = dict(data)
    data["behaviors"] = {bid: behaviors[bid] for bid in sorted(behaviors)}
    return data


def write_behavior_json(project_dir, data):
    path = _behavior_json_path(project_dir)
    graph_dir = os.path.dirname(path)
    os.makedirs(graph_dir, exist_ok=True)
    _write_cache_gitignore(os.path.join(graph_dir, ".gitignore"))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(_stable(data), f, indent=2)


def _run_behavior_runner(project_dir, only=None):
    """Spawn behavior-runner and return its fingerprints JSON; raise on a non-zero exit.

    The child's stderr is forwarded rather than swallowed. `run_behaviors` writes every
    diagnosis it has there — the failing test's own output (`run_behaviors.py:407`),
    "test passed but coverage was not measured", "the locator is stale" — and then exits
    0 anyway, because a red behavior is a fingerprint and not a runner failure. So the
    *success* path is where the diagnosis lives, and `capture_output=True` was dropping
    all of it: `--covering --verify` reported `reason: test-failed` with an empty stderr,
    leaving nothing on the machine that said whether the test failed or the toolchain
    never started. Stdout stays captured — it is the JSON channel.

    `check=True` is kept, so a non-zero exit is still a `CalledProcessError` for the
    callers that document catching one; the forward happens on both paths.
    """
    argv = [sys.executable, str(_RUNNER), "--project", project_dir,
            "--states", "accepted", "confirmed", "--emit-fingerprints"]
    if only:
        argv += ["--only", *only]
    try:
        out = subprocess.run(argv, capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exc:
        if exc.stderr:
            sys.stderr.write(exc.stderr)
        raise
    if out.stderr:
        sys.stderr.write(out.stderr)
    return json.loads(out.stdout)


def build(project_dir):
    """Project specs + run behaviors + merge by trust → write & return behavior.json."""
    specs_dir = os.path.join(project_dir, "knowledge-base", "specs")
    projected = project_behaviors(specs_dir)
    runner = _run_behavior_runner(project_dir)
    fingerprints = runner.get("fingerprints", {})
    prior = load_behavior_json(project_dir).get("behaviors", {})

    behaviors = {}
    for bid, fields in projected.items():
        incoming = fingerprints.get(bid, {"coverage": "unknown", "exercises": [], "reason": "not-run"})
        prior_part = prior.get(bid)
        merged = merge_fingerprint(prior_part, incoming)
        behaviors[bid] = {**fields, **merged}

    data = {"version": 1, "commit": runner.get("commit", "unknown"), "behaviors": behaviors}
    write_behavior_json(project_dir, data)
    return data


def direction_b(behaviors, beh_id):
    """Direction B: the code a behavior exercises (implementing files)."""
    entry = behaviors.get(beh_id)
    if not entry:
        return []
    return sorted(e["path"] for e in entry.get("exercises", []))


def _code_graph_impact(changed_files, project_dir):
    """Blast-radius set for changed files: the inputs plus direct+transitive dependents."""
    impact = set(changed_files)
    if not changed_files:
        return impact
    try:
        out = subprocess.run(
            [sys.executable, str(_CODE_GRAPH), "--impact", *changed_files,
             "--dir", project_dir, "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        data = json.loads(out.stdout)
        for key in ("input_files", "direct_dependents", "transitive_dependents"):
            impact.update(data.get(key, []))
    except (subprocess.CalledProcessError, json.JSONDecodeError, FileNotFoundError, OSError):
        pass
    return impact


def _affected_from_impact(behaviors, impact):
    """BEH ids in the projected graph whose exercised code intersects `impact`."""
    affected = []
    for bid, entry in behaviors.items():
        paths = {e["path"] for e in entry.get("exercises", [])}
        if paths & impact:
            affected.append(bid)
    return sorted(affected)


def direction_a(behaviors, changed_files, project_dir):
    """Direction A: projected behaviors whose exercised code intersects the blast radius."""
    return _affected_from_impact(behaviors, _code_graph_impact(changed_files, project_dir))


# Graph nodes that are not code a behaviour could ever exercise. The homegrown backend only
# ever indexed source, so "graph node" and "source file" were the same set and this
# distinction did not exist. A polyglot backend indexes manifests and project files too —
# `package.json`, `pom.xml`, `app.csproj`, a solution file — and every one of them then
# appeared in `--gaps` as source with no behaviour, and from there into a tracked BACKLOG.md
# and into wrap-up's "write a behavior for this" prompt. Asking someone to write a behaviour
# for `package.json` is noise, and noise in a gap report is how the report stops being read.
#
# Keyed on the language the graph itself recorded, not on a guess from the extension: the
# backend already decided what each file is, and re-deciding it here is how two copies of one
# idea drift apart.
_NON_SOURCE_LANGUAGES = frozenset({"json", "xml", "msbuild"})


def _graph_files(project_dir):
    """Project-relative source files code-graph tracks, mapped to the language the backend
    recorded for each (None when it recorded none); empty if there is no graph.

    A mapping rather than a set because `gaps` needs the language to decide what is
    behavior-coverable, and reading `graph.json` a second time to get it is how two copies of
    one answer drift apart. `surface` only ever asks this for membership and truthiness, both
    of which read the same on a dict as on the set this replaced.
    """
    path = os.path.join(project_dir, "knowledge-base", ".graph", "graph.json")
    if not os.path.exists(path):
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            files = json.load(f).get("files", {})
    except (json.JSONDecodeError, OSError):
        return {}
    out = {}
    for rel, info in files.items():
        language = info.get("language") if isinstance(info, dict) else None
        if language in _NON_SOURCE_LANGUAGES:
            continue
        out[rel] = language
    return out


# A graph node can be a file without being something a behavior could ever cover. Coverage is
# `exercises[].path` — the production code a test's import closure reached — union the `entry:`
# values specs declare. A file no import statement can name enters neither set, ever, so it is a
# permanent line in a git-tracked BACKLOG.md and in wrap-up's "write a behavior for this" prompt.
#
# Measured on freya-devkit itself, 2026-08-21: `--gaps` reported 57 files, of which 33 were of
# that kind — 29 `test_*.py`, `conftest.py`, the extensionless `bin/freya`, and `install.sh` /
# `install.ps1`. 24 were real source. A worklist that is 58% unactionable is a worklist people
# stop reading, which is the same failure mode as a check that cries wolf.
#
# The predicate is deliberately NOT "a `.py` file that is not a test". That reads correctly on
# this repository and is wrong on every other one: the graph is polyglot (ADR-018, ADR-019), so
# `lib/webauthn.ts` is exactly the kind of file this census exists to name, and an extension
# allowlist would report zero gaps on any TS, Go or C# project — trading 33 false entries for a
# confidently-empty answer, which ADR-005 rules out outright.
#
# Three narrower rules instead, each a claim about what a *file* is and never about which
# directory it sits in. Directory-name judgement is ADR-022's two-tier override territory and is
# not re-litigated here; the census also never sees a directory the graph already excluded.
#
# Where the rules are uncertain they under-exclude: a missing exclusion costs one noisy line,
# a wrong one hides real uncovered code, which is the failure the report exists to prevent.
# That is why `*Test.java` / `*Tests.cs` (camelCase, no separator to anchor on) and Django's
# bare `tests.py` are absent — add them when a project measures them, not on speculation.

# Names that mean "this file is a test" outright, regardless of the conventions below.
_TEST_BASENAMES = frozenset({"conftest.py"})

# Languages the graph indexes whose files are *invoked*, never imported: no import closure can
# reach a shell or PowerShell script, so no fingerprint can name one. Distinct from
# _NON_SOURCE_LANGUAGES, which is about nodes that are not code at all — these are code, and
# are still outside what this mechanism can measure. Keyed on the recorded language for the
# same reason that list is: the backend already decided what each file is.
_UNIMPORTABLE_LANGUAGES = frozenset({"shell", "powershell", "batch"})


def _is_test_file(name):
    """True for the test-file naming conventions, matched anchored rather than as substrings.

    `test_x.py` / `x_test.py` / `x_test.go` on the separator conventions, `x.test.ts` /
    `x.spec.tsx` on the colocated ones. Anchored because the unanchored version of this idea
    already shipped once in the exclusion rules and made `contest.py` look like a test.
    """
    if name in _TEST_BASENAMES:
        return True
    parts = name.split(".")
    if len(parts) < 2:
        return False
    stem, middles = parts[0], parts[1:-1]
    if stem.startswith("test_") or stem.endswith("_test"):
        return True
    return any(part in ("test", "spec") for part in middles)


def _is_coverable(rel, language):
    """Could a behavior's exercised code ever name this file?

    Applied by `gaps` only. `surface`'s `recall_gaps` is the same shape of question over a
    single change and has the same noise, but its answer is advisory per-change rather than a
    tracked census, and narrowing it belongs with its own spec row and its own tests.
    """
    name = rel.replace("\\", "/").rsplit("/", 1)[-1]
    if _is_test_file(name):
        return False
    if "." not in name:
        # No extension: a script or an executable (`bin/freya`, `Makefile`), not a module any
        # language's import system can address, so nothing can depend on it in the graph.
        return False
    return language not in _UNIMPORTABLE_LANGUAGES


def _covered(behaviors, specs_behaviors):
    """Project-relative files any behavior covers: graph `exercises` paths ∪ declared
    `entry` values. Shared by surface (recall gaps) and gaps (whole-repo audit)."""
    covered = set()
    for rec in behaviors.values():
        for e in rec.get("exercises", []):
            covered.add(e["path"])
    for b in specs_behaviors:
        if b.get("entry"):
            covered.add(b["entry"])
    return covered


def surface(project_dir, base):
    """Validate-on-hit surface for base..HEAD (read-only, advisory).

    Returns three buckets:
      - affected_accepted: accepted behaviors the change touches (context only; the
        accepted-behavior gate lives in the separate --check step, not here).
      - validate_candidates: affected proposed + confirmed behaviors to confirm on hit.
      - recall_gaps: changed source files covered by no behavior.

    A proposed/confirmed behavior is "affected" iff its `entry` is in the change's
    impact set. impact = changed ∪ transitive dependents, and the entry depends on
    its whole closure, so `entry ∈ impact` is equivalent to closure(entry) ∩ impact
    ≠ ∅ — the precise match, without recomputing closures.

    `skipped` separates the two ways every bucket comes back empty: nothing was
    surfaced because there was nothing to surface, or because this could not look.
    Advisory output needs it more than a gate does, not less — nothing here changes an
    exit code, so the note is the entire signal, and until 2026-08-24 the note a failed
    diff produced was `no changed files in base..HEAD`, a false sentence.
    """
    specs_dir = os.path.join(project_dir, "knowledge-base", "specs")
    changed, ok = _changed_files(base, project_dir)
    result = {
        "version": 1, "base": base, "changed": changed, "skipped": False,
        "affected_accepted": [], "validate_candidates": [], "recall_gaps": [],
    }
    graph_files = _graph_files(project_dir)
    if not graph_files:
        result["skipped"] = True
        result["note"] = ("no code-graph at knowledge-base/.graph/graph.json — "
                          "run code-graph build; surfacing skipped")
        return result
    if not ok:
        result["skipped"] = True
        result["note"] = (f"surfacing skipped — git could not diff {base}..HEAD, so the "
                          "changed set is unknown rather than empty")
        return result
    if not changed:
        result["note"] = "no changed files in base..HEAD"
        return result

    impact = _code_graph_impact(changed, project_dir)
    behaviors = load_behavior_json(project_dir).get("behaviors", {})

    affected = _affected_from_impact(behaviors, impact)
    result["affected_accepted"] = [b for b in affected
                                   if behaviors[b].get("state") == "accepted"]
    confirmed_hit = [b for b in affected if behaviors[b].get("state") == "confirmed"]

    # Proposed live in specs (not the projected graph); load all states once so we
    # can both surface proposed candidates and collect declared entries for recall.
    specs_behaviors = run_behaviors.load_behaviors(
        specs_dir, states=("proposed", "confirmed", "accepted"))
    by_id = {b.get("behavior_id"): b for b in specs_behaviors}

    candidates = []
    for bid in confirmed_hit:
        src = by_id.get(bid, {})
        candidates.append({
            "behavior_id": bid, "state": "confirmed",
            "spec_id": src.get("spec_id"), "title": src.get("title"),
            "entry": src.get("entry"), "spec_path": src.get("spec_path"),
        })
    for b in specs_behaviors:
        if b.get("state") != "proposed":
            continue
        entry = b.get("entry")
        if entry and entry in impact:
            candidates.append({
                "behavior_id": b.get("behavior_id"), "state": "proposed",
                "spec_id": b.get("spec_id"), "title": b.get("title"),
                "entry": entry, "spec_path": b.get("spec_path"),
            })
    result["validate_candidates"] = sorted(candidates, key=lambda c: c.get("behavior_id") or "")

    covered = _covered(behaviors, specs_behaviors)
    result["recall_gaps"] = sorted(f for f in changed if f in graph_files and f not in covered)
    return result


def gaps(project_dir):
    """Whole-repo uncovered audit: behavior-coverable graph files no behavior covers (read-only).

    Counts only what `_is_coverable` admits — test files, extensionless scripts and shell/
    PowerShell nodes can never appear in an `exercises` list, so listing them asks for a
    behavior nobody can write.
    """
    specs_dir = os.path.join(project_dir, "knowledge-base", "specs")
    result = {"version": 1, "gaps": [], "total": 0}
    graph_files = _graph_files(project_dir)
    if not graph_files:
        result["note"] = ("no code-graph at knowledge-base/.graph/graph.json — "
                          "run code-graph build")
        return result
    behaviors = load_behavior_json(project_dir).get("behaviors", {})
    specs_behaviors = run_behaviors.load_behaviors(
        specs_dir, states=("proposed", "confirmed", "accepted"))
    covered = _covered(behaviors, specs_behaviors)
    uncovered = sorted(f for f, language in graph_files.items()
                       if f not in covered and _is_coverable(f, language))
    result["gaps"] = uncovered
    result["total"] = len(uncovered)
    return result


def _locator_resolves(project_dir, locator):
    """Does this spec locator name a file that exists inside the project?

    A file, not a path: `isfile`, not `exists`. A locator addresses the test a
    behavior claims verifies it, and eleven of the twelve entries in
    `frontmatter.KNOWN_ADAPTERS` address one by file; the twelfth is `manual`,
    which addresses nothing. A locator naming a directory has not resolved, it
    has failed to wearing a green tick — measured on the `exists` spelling this
    line replaces, `locator: .::x` resolved and bought an ADR-012 downgrade.

    **The caller no longer has an exemption, and the shape of the one it had is
    worth keeping.** This predicate was reached only when a locator was declared,
    so `covering()` — which never reads `adapter` — skipped it for *any* behavior
    declaring none. Measured 2026-08-23: `state: accepted, adapter: vitest`, no
    locator — Tier 1 refused it (`missing-locator`) and `--covering` returned it,
    licensing a downgrade with no forgery, just an omission. Closed at the caller
    rather than here (`covering()`'s `if not locator or ...`), because "a behavior
    that names no test" is a question about what the query means and not about
    whether a path resolves. `test_a_missing_locator_is_now_refused_by_both` pins
    the agreement; it is the same row, renamed when it changed sides.

    A locator with no path part (`#scenario` alone) is the same defect one step
    earlier — joined onto the project it *is* the project directory — and the
    `not rel_path` guard rejects it before the join. **That guard is redundant
    and stays anyway, a claim no test can check, so it is made here.** `isfile`
    already answers no for the empty path, and deleting the guard was
    mutation-checked on 2026-08-23: the suite stayed green. It stays as the only
    place the empty-path case is *stated* — widen `isfile` back to `exists`, or
    to `lexists` for a symlinked test file, and the hole reopens silently.
    """
    rel_path, _frag = parse_locator(locator)
    if not rel_path or escapes(rel_path):
        return False
    return os.path.isfile(os.path.join(project_dir, rel_path))


def covering(project_dir, file, verify=False):
    """Accepted behaviors whose `exercises` include `file` — read-only unless `verify`.

    Only `accepted` behaviors are returned — they are the strongest "intentional"
    evidence the security cross-reference has (SP5), and this query is what
    licenses a downgrade (ADR-012). Four things bound what that means:

    * `state`, `spec_id` and `locator` come from the spec frontmatter, never from
      behavior.json. The spec is where state lives (ADR-002, ADR-003), so a
      behavior demoted to `proposed` stops licensing a downgrade at the next
      query instead of at the next `--build`, and a behavior.json entry with no
      spec behind it licenses nothing at all.
    * a locator is **required**, and must stay inside the project and name a file
      that exists. verify_links checks something similar at Tier 1, but this query
      answers about a repository whose gates nobody here ran, so the check is
      made here rather than assumed. **It is not the same check, and neither
      one implies the other** — say so plainly, because the asymmetry means a
      gate-green repository can still have `--covering` refuse a behavior, and
      the next maintainer to meet that will read a correct refusal as a bug.
      Measured, one fixture through both (see `LocatorCheckDivergesFromTier1Test`):

        - no path part (`locator: "#scenario"`) — refused by both. Tier 1 used to
          pass it, because `escapes("")` is false and `root / ""` is the root,
          which exists; it now refuses it as `locator-names-no-file`.
        - names a directory — refused by both. Tier 1 asked `Path.exists`, which
          a directory satisfies, and now asks `is_file` as this does.
        - no locator at all with a non-`manual` adapter — refused by both. Tier 1
          always refused it (`missing-locator`); this query read only what was
          declared, so an omission alone licensed a downgrade, and it is the hole
          that needed no forgery. Closed here by requiring a locator.
        - a `.py` fragment naming no symbol — Tier 1 refuses it, and here it is
          **returned**: this check stops at the file, so "the locator resolves"
          means the file is there and not that the named test is. A Gherkin file
          missing its `@BEH-NNN` reverse tag is believed to behave the same way
          and is the one shape in this list no test measures — read it as an
          expectation rather than as a measurement.

      **The reassurance that used to sit here is spent, and it was spent from
      both ends.** Two of these rows were divergences in this query's favour — it
      refused where Tier 1 passed, which fails closed and leaves the finding
      open — and both were closed on 2026-08-23 by tightening Tier 1. The third
      ran the other way and was the one that mattered: Tier 1 refused a behavior
      declaring no locator while this query returned it, closed on 2026-08-24 by
      tightening this query. What survives is the fourth, and it still fails
      **open** — Tier 1 refuses, this query returns, and a downgrade Tier 1 would
      have blocked goes through. So running the gate is worth strictly more than
      running this, and no measured shape makes a gate-green repository meet a
      refusal here.
    * without `--verify`, none of this proves the behavior passes. Both inputs are
      supplied by the project being scanned, so `observed` means a test passed
      once, on somebody's machine, at the commit `freshness` names — a label on
      evidence, not a verification of it, and `evidence` says so in those words
      for the caller to carry into the report a human reads. `--verify` re-runs
      the linked test, and is how the security scan gets more than a label; what
      that verdict can and cannot establish is `_verify_behaviors`' docstring,
      and the answer is narrower than the flag's name suggests.

      An earlier version of this paragraph argued that running the test was
      out of the question — "executing a scanned repository's suite is worse than
      the problem it would solve". That was an argument against a capability this
      toolkit ships as a feature, in a sibling skill this module imports, and
      ADR-012 formally retracts it. It is recorded rather than deleted because
      the reasoning failed in a way worth recognising again: it imported a
      hostile-clone threat model that does not match what freya is.

    Empty `covering` (file echoed) when there is no graph or none cover it.
    """
    behaviors = load_behavior_json(project_dir).get("behaviors", {})
    projected = project_behaviors(os.path.join(project_dir, "knowledge-base", "specs"))
    out = []
    for bid, rec in behaviors.items():
        spec = projected.get(bid)
        if not spec or spec.get("state") != "accepted":
            continue
        locator = spec.get("locator")
        # A locator is now REQUIRED, where it used to be checked only if declared. The old
        # `if locator and ...` let a behavior that declared none skip the check entirely and
        # still license a downgrade — the widest of the three holes SEC-006 named, because it
        # needed no forgery at all, just an omission. What it costs is stated rather than
        # hidden: an `accepted` + `adapter: manual` behavior legitimately has no locator, and
        # it no longer downgrades anything. That is the right answer for this query — a
        # manual behavior has no test that could have run — but it is a real narrowing and
        # ADR-012 records it.
        if not locator or not _locator_resolves(project_dir, locator):
            continue
        # `source == "observed"`, and this is the change that matters most. An exercises entry
        # carries `observed` (a real run, with coverage) or `static` — INFERRED FROM THE
        # IMPORT GRAPH, no test ever ran (`run_behaviors.static_exercises`). This query read
        # neither, so a dependency-graph inference silenced security findings exactly as a
        # passing test did. Nothing needs to run to fix that; it just stops treating an
        # inference as evidence.
        covering_entries = [e for e in rec.get("exercises", [])
                            if isinstance(e, dict) and e.get("path") == file
                            and e.get("source") == "observed"]
        if not covering_entries:
            continue
        # The symbols that actually ran, where the runner captured them. The file anchor
        # alone is weak in a way worth naming: a test touching anywhere in a 500-line module
        # downgraded a finding on a line it never executed. This does not fix that — the
        # judgement is still the agent's — but it hands the agent the evidence to make it.
        # File-plus-symbols, never lines: `coverage_symbols` records named functions, and
        # claiming line granularity the data cannot support would be the overclaim this
        # branch keeps deleting.
        symbols = sorted({s for e in covering_entries for s in (e.get("symbols") or [])})
        row = {"behavior_id": bid, "spec_id": spec.get("spec_id"),
               "coverage": rec.get("coverage"), "locator": locator,
               "source": "observed"}
        if symbols:
            row["symbols"] = symbols
        out.append(row)
    out.sort(key=lambda c: c["behavior_id"])
    if verify and out:
        # One runner invocation for every candidate, not one per row. `--only` already takes a
        # list, and a query that spawned N test runs for N behaviors would be slow enough that
        # somebody would turn verification off — which is the failure mode that matters more
        # than the wasted seconds.
        verdicts = _verify_behaviors(project_dir, [c["behavior_id"] for c in out])
        for row in out:
            row["verified"] = verdicts[row["behavior_id"]]
    if verify:
        kept = [c for c in out if c.get("verified", {}).get("passed")]
        evidence = ("state and locator re-derived from knowledge-base/specs; only "
                    "`source: observed` exercised paths counted, so a statically inferred "
                    "edge licenses nothing; and each behavior's linked test was handed to "
                    "freya-behavior-runner to be RE-RUN by this query. %d of %d passed. A "
                    "row with `verified.passed` false is evidence against the behavior "
                    "only where its test actually ran, and this query cannot always tell: "
                    "`test-failed` is the runner's word for ANY non-zero exit from the test "
                    "command, so an uninstalled toolchain is spelled exactly like a red "
                    "test, while `could not run: ...` means the runner never started. Read "
                    "`verified.reason` and the runner's stderr before reporting a behavior "
                    "as failing." % (len(kept), len(out)))
    else:
        evidence = ("state and locator re-derived from knowledge-base/specs; only "
                    "`source: observed` exercised paths counted, so a statically inferred "
                    "edge licenses nothing. Exercised paths and symbols are read from the "
                    "project's committed knowledge-base/.graph/behavior.json, which records "
                    "that a test passed once — no test was run by this query, so this is a "
                    "label on the evidence and not a verification of it. Re-run with "
                    "--verify to execute the linked tests.")
    return {"version": 1, "file": file, "covering": out, "verified": bool(verify),
            "evidence": evidence}


# Runner reasons that mean two different things and cannot be told apart from here, mapped to
# the sentence that says so. Keyed on the reason rather than applied to all of them: every
# other token in `run_behaviors` names exactly one situation, and a caveat attached to those
# would be a caveat the reader learns to skip on the row where it is load-bearing.
_AMBIGUOUS_REASONS = {
    "test-failed": ("the test command exited non-zero — a failing test and a runner that "
                    "could not start (no toolchain installed, no package manifest) are the "
                    "same exit code to freya-behavior-runner; its stderr says which"),
}


def _verify_behaviors(project_dir, bids):
    """Re-run each named behavior's linked test; return {bid: {passed, reason}}.

    This exists because the argument against it was wrong, and the way it was wrong is worth
    keeping. The earlier reasoning held that running a scanned repository's test is "arbitrary
    code execution, worse than the finding it would close" — an argument against a capability
    this toolkit ships as a feature, in a sibling skill this module already imports.
    `freya-behavior-runner` exists to run the project's tests, and `regression_check` below
    already re-runs accepted behaviors through the same helper this uses. freya is a tool a
    developer points at a repository they are working in; by then they have installed its
    dependencies and run its suite, and one more test run adds nothing to that risk.

    `passed` is False on a red test AND on any inability to run, because this is the one query
    that can silence a security finding: "could not determine" must never read as "verified".

    **The reason says as much as the runner's vocabulary allows, which is less than this
    docstring used to claim.** It said "a refusal can be told from a failure". Two of them
    can: `could not run: ...` is this function failing to spawn the runner at all, and
    `runner returned no verdict` is a behavior it never reported on. Inside `test-failed` the
    two are welded together — that is `run_behaviors`' word for ANY non-zero exit from the
    test command (`run_behaviors.py:408`, `:463`), so a red test, an uninstalled vitest and a
    project with no package manifest arrive here as one token, and nothing this module can
    read separates them. Measured 2026-08-24 on a checkout with no JS toolchain: every row
    came back `test-failed`, and the evidence string said the tests had been re-run and none
    passed.

    So the token is passed through as the runner spelled it — laundering one reason into
    prose while the rest stay tokens is how a caller learns to trust the wrong field — and
    `test-failed` alone carries a `note` naming the second meaning. Absent on every
    unambiguous reason, because a caveat printed on every row is one nobody reads on the row
    that needed it. It matters because the consumer is told a false row "is a finding in its
    own right" (`skills/freya-codebase-security-scan/SKILL.md:440`), and "this repository
    asserts an accepted behavior whose test does not pass" is the wrong sentence to write
    about a machine where nothing was installed. `_run_behavior_runner` forwards the child's
    stderr for the same reason: it is the only place the difference is visible.

    No `except Exception`. `_run_behavior_runner` uses `check=True`, so a non-zero exit raises
    `CalledProcessError`, and malformed stdout raises `ValueError`; those two plus `OSError`
    are what a spawn can do here. A blanket catch would also swallow a bug in this function
    and report it as an unverified behavior, which is the shape that hides a defect behind a
    conservative-looking answer.
    """
    try:
        fingerprints = _run_behavior_runner(project_dir, only=list(bids)).get("fingerprints", {})
    except (subprocess.CalledProcessError, OSError, ValueError) as exc:
        return {bid: {"passed": False,
                      "reason": "could not run: %s" % exc.__class__.__name__} for bid in bids}
    out = {}
    for bid in bids:
        fp = fingerprints.get(bid)
        if not isinstance(fp, dict):
            out[bid] = {"passed": False, "reason": "runner returned no verdict"}
        elif fp.get("coverage") == "observed":
            out[bid] = {"passed": True, "reason": "test passed under this query"}
        else:
            # Anything that is not `observed` is False, and the reason says what the runner
            # said. `test-failed` is the one token that hides a second meaning, so it is the
            # one that carries a note; see the docstring for why it cannot be split here.
            reason = fp.get("reason") or "no coverage observed"
            out[bid] = {"passed": False, "reason": reason}
            if reason in _AMBIGUOUS_REASONS:
                out[bid]["note"] = _AMBIGUOUS_REASONS[reason]
    return out


def _changed_files(base, project_dir):
    """(project-relative files changed in base..HEAD, ok) — `ok` False when git could not say.

    The pair is the whole point. `[]` used to mean both "nothing changed" and "git
    refused to diff", and the callers below intersect that empty set: `regression_check`
    found no affected behavior, started no runner, and returned `0 affected, 0 failed`
    with exit 0 — the Direction-A hard block reporting a clean run over a diff it never
    computed, in output byte-identical to a genuinely unaffected change. Measured
    2026-08-24 with `--base origin/main` in a repository with no remote (a CI checkout, a
    shallow clone, a fork whose default branch is not `main`): git exits 128, the gate
    exits 0. `surface` had the same input and said `no changed files in base..HEAD`,
    which is a sentence rather than an answer — false in exactly this case.

    It is the shape `verify_intent._changed_status` was rewritten to close with its own
    `ok=False`, left open in the sibling gate. The remedy is that one: fail open, because
    ADR-009 rejects failing closed on a git error by name — wrap-up would break hardest
    when the repository is already in trouble — and label it, because a no-op nothing
    distinguishes from a pass is the false clean the same record forbids.

    The three tokens are `graph_ops._get_changed_files`' (`graph_ops.py:590`), and this
    asks that function's question, so it now asks it with that function's argv. Each is
    load-bearing:

      `--end-of-options` — the revision slot accepts `--output=<file>`: git truncates
          that file, writes the diff into it and exits 0 with an empty stdout, so the run
          looks clean *and* clobbers a path outside the project. Operator-supplied here
          rather than repository-supplied, which makes it a footgun rather than
          `verify_intent`'s forgery route; the token costs nothing either way. It does
          impose git 2.24 (Nov 2019) — below that the option is unknown, rc is non-zero,
          and this gate is not degraded but permanently skipped, which is the trade the
          two sibling call sites already made.
      `--relative`      — `--name-only` prints paths from the REPOSITORY root, while
          every path joined against them here is project-relative (`behavior.json`'s
          `exercises[].path`, `graph.json`'s keys). For any `--project` below the repo
          root — a monorepo package, a sub-project — every path carried an extra prefix,
          nothing ever matched, and the gate reported `0 affected` with no error at all.
          A no-op when the project *is* the repository root, so the common case is
          unchanged.
      `--no-renames`    — this asks which paths moved, not what the author meant. With
          detection on (git's default) a rename is reported once, as its destination, and
          the path it vanished from is never named — so an accepted behavior whose
          `exercises` still record the old path is not affected by the commit that moved
          its code, which is the run that most needed to happen.

    `^{commit}` is deliberately absent, where `verify_intent` peels: its baseline comes
    from a file the scanned repository commits, and `<tree>..HEAD` is an honest diff of
    that tree, not a lie about one. Here the base is a command-line argument.
    """
    try:
        out = subprocess.run(
            ["git", "-C", project_dir, "diff", "--name-only", "--no-renames", "--relative",
             "--end-of-options", f"{base}..HEAD"],
            capture_output=True, text=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return [], False
    return [ln.strip() for ln in out.stdout.splitlines() if ln.strip()], True


def regression_check(project_dir, base):
    """Direction-A regression check: re-run only the accepted behaviors a change
    touches; block (exit 1) if any is test-failed. Returns (report, exit_code).

    `skipped` is on every report, not only the skipped ones, because a key that
    appears when the answer is bad is a key consumers read only after being burned.
    `skipped: true` means no behavior was selected and none was run: exit 0 says the
    gate did not block, and only `skipped` says whether it looked (ADR-009's
    fail-open, with the correction that a fail-open must say so).
    """
    data = load_behavior_json(project_dir)
    behaviors = data.get("behaviors", {})
    changed, ok = _changed_files(base, project_dir)
    if not ok:
        return {"affected": [], "failed": [], "changed": [], "skipped": True,
                "note": (f"regression check skipped — git could not diff {base}..HEAD, "
                         "so no behavior was selected and none was run")}, 0
    affected = direction_a(behaviors, changed, project_dir)
    if not affected:
        return {"affected": [], "failed": [], "changed": changed, "skipped": False}, 0

    runner = _run_behavior_runner(project_dir, only=affected)
    fingerprints = runner.get("fingerprints", {})
    failed = []
    for bid in affected:
        incoming = fingerprints.get(bid, {"coverage": "unknown", "exercises": [], "reason": "not-run"})
        prior_part = behaviors.get(bid)
        merged = merge_fingerprint(prior_part, incoming)
        fields = {k: v for k, v in behaviors[bid].items()
                  if k not in ("coverage", "exercises", "reason")}
        behaviors[bid] = {**fields, **merged}
        # Guard: only `accepted` behaviors can gate the regression check.
        # Non-accepted states (confirmed, proposed) are advisory by construction.
        # The runner contract is the first line of defense (it never emits test-failed
        # for confirmed), but this check enforces the invariant locally so that future
        # SP2/SP3 executable paths cannot accidentally gate on a non-accepted behavior.
        if (behaviors[bid].get("state") == "accepted"
                and incoming.get("coverage") == "unknown"
                and incoming.get("reason") == "test-failed"):
            failed.append(bid)

    data["behaviors"] = behaviors
    data["commit"] = runner.get("commit", data.get("commit", "unknown"))
    write_behavior_json(project_dir, data)
    return ({"affected": affected, "failed": failed, "changed": changed, "skipped": False},
            1 if failed else 0)


def main():
    parser = argparse.ArgumentParser(description="Build and query the behavior graph.")
    parser.add_argument("--project", required=True, help="Project root directory.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--build", action="store_true", help="Build/refresh behavior.json.")
    group.add_argument("--affected", nargs="+", metavar="FILE",
                       help="Direction A: behaviors affected by these changed files.")
    group.add_argument("--implements", metavar="BEH",
                       help="Direction B: code a behavior exercises.")
    group.add_argument("--check", action="store_true",
                       help="Direction-A regression check (re-run affected accepted behaviors).")
    group.add_argument("--surface", action="store_true",
                       help="Validate-on-hit surface (affected proposed/confirmed + recall gaps) for base..HEAD.")
    group.add_argument("--gaps", action="store_true",
                       help="Whole-repo uncovered-code audit (source files no behavior covers).")
    group.add_argument("--covering", metavar="FILE",
                       help="Accepted behaviors whose exercised code includes FILE (security cross-ref).")
    parser.add_argument("--base", help="Base commit for --check (diff base..HEAD).")
    # Off by default because `--covering` is a graph query other things call in a loop, and a
    # query that spawns a test run cannot be that. On for the security scan, which is the one
    # caller whose answer can silence a finding and which is already expensive.
    parser.add_argument("--verify", action="store_true",
                        help="Re-run each returned behavior's linked test instead of trusting "
                             "the committed record (--covering only).")
    args = parser.parse_args()

    if args.covering:
        print(json.dumps(covering(args.project, args.covering, verify=args.verify), indent=2))
        return 0

    if args.gaps:
        print(json.dumps(gaps(args.project), indent=2))
        return 0

    if args.surface:
        if not args.base:
            parser.error("--surface requires --base COMMIT")
        print(json.dumps(surface(args.project, args.base), indent=2))
        return 0

    if args.check:
        if not args.base:
            parser.error("--check requires --base COMMIT")
        report, code = regression_check(args.project, args.base)
        print(json.dumps(report, indent=2))
        return code

    if args.build:
        data = build(args.project)
        print(json.dumps(data, indent=2))
        return 0

    behaviors = load_behavior_json(args.project).get("behaviors", {})
    if args.affected:
        print(json.dumps({"affected": direction_a(behaviors, args.affected, args.project)}, indent=2))
    else:
        print(json.dumps({"implements": direction_b(behaviors, args.implements)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
