---
id: SPEC-017
title: Spec search and corpus discovery
category: features
tags: [search, specs, discovery, cli, spec-manager]
status: implemented
certainty: 70
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-spec-manager/scripts/search_specs.py
  - skills/freya-spec-manager/scripts/frontmatter.py
  - bin/commands.json
  - skills/freya-spec-manager/SKILL.md
intentional_decisions:
  - "Full-text search reads a 500-character body preview, not the whole spec"
  - "--max-certainty/--below is exclusive at the threshold while --min-certainty is inclusive"
  - "A markdown file with no id is not a spec and is skipped without a warning"
  - "Discovery falls back to a legacy docs/specs layout, then to a path that need not exist"
behaviors:
  - behavior_id: BEH-082
    title: Query search matches title, category, tags and the first 500 characters of the body
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-spec-manager/scripts/test_search_specs.py#SearchCase.test_query_matches_title_tags_and_preview
  - behavior_id: BEH-083
    title: Tag, category, status and id filters are case-insensitive exact matches and compose as AND
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-spec-manager/scripts/test_search_specs.py#SearchCase.test_filters_are_case_insensitive_and_compose
  - behavior_id: BEH-084
    title: A spec at exactly the threshold is excluded by --below and included by --min-certainty
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-spec-manager/scripts/test_search_specs.py#CertaintyCase.test_below_excludes_threshold_min_includes_it
  - behavior_id: BEH-085
    title: A project that still keeps its specs in docs/specs is found and searched
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-spec-manager/scripts/test_search_specs.py#DiscoveryCase.test_legacy_docs_specs_fallback
  - behavior_id: BEH-086
    title: An unparseable spec file warns on stderr and the remaining specs are still returned
    state: proposed
    level: unit
    adapter: manual
    locator: skills/freya-spec-manager/scripts/test_search_specs.py#DiscoveryCase.test_malformed_spec_warns_and_others_load
---

# Spec search and corpus discovery

## What

`freya spec` is the read side of the spec corpus and the loader every other
spec-manager script builds on. It does two separable jobs.

**Discovery** — locate the corpus. `find_specs_dir` tries, in order,
`knowledge-base/specs`, a bare `specs/`, the parent's `knowledge-base/specs`,
then the legacy `docs/specs` and the parent's `docs/specs`; the first directory
that exists wins. Every `*.md` under it is loaded recursively, `README.md` is
skipped by name, and a file whose frontmatter cannot be parsed is reported on
stderr and left out while the rest of the corpus still loads.

**Filtering** — narrow the loaded set. `--query` is a case-insensitive substring
match over title, category, tags and a 500-character body preview. `--tag`,
`--category`, `--status` and `--id` are case-insensitive exact matches.
`--min-certainty` / `--max-certainty` (aliased `--below`) bound the certainty
score, `--intentional` keeps only specs that declare intentional decisions, and
`--sort-certainty` orders lowest-first — the review flow, which works up from the
least trustworthy record. Filters compose: every one given must match. Output is a
markdown table, JSON, or bare paths.

Nothing here writes. An empty result is an empty table and exit 0.

## Why

Everything downstream needs "give me the specs" to be one answer rather than five
re-implementations: `verify_intent`, `verify_links`, `drift` and `contradictions`
all import `load_all_specs`/`find_specs_dir` rather than walking the tree
themselves, so the corpus one tool sees is the corpus all of them see. The
search flags exist for the human half — locating the record that governs the file
you are about to change, and working the low-certainty tail during review.

The legacy `docs/specs` fallback is a compatibility promise: the knowledge-base
layout arrived after projects were already carrying specs under `docs/`, and a
migration must not be the price of running a query.

**Certainty (70).** The flag surface is documented in
`skills/freya-spec-manager/SKILL.md`, which is what puts these behaviors above a
guess. It is held down by two things. First, **there is no test file for this
module at all** — `skills/freya-spec-manager/scripts/` has a `test_*.py` beside
every other script; `search_specs.py` is the exception, and its only coverage is
one fixture-sanity assertion borrowed by
`test_verify_links.py#VerifyLinksCase.test_fixture_actually_parses`. Second, two
of the semantics below (the 500-character search window, the silent skip of an
id-less file) read as implementation artifacts that were never decided, so their
"intent" is inferred from consequence rather than from any record.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-082 Query search matches title, category, tags and the first 500 characters of the body | proposed | *no test* — owed at `test_search_specs.py#SearchCase.test_query_matches_title_tags_and_preview` (manual) |
| BEH-083 Tag, category, status and id filters are case-insensitive exact matches and compose as AND | proposed | *no test* — owed at `test_search_specs.py#SearchCase.test_filters_are_case_insensitive_and_compose` (manual) |
| BEH-084 A spec at exactly the threshold is excluded by `--below` and included by `--min-certainty` | proposed | *no test* — owed at `test_search_specs.py#CertaintyCase.test_below_excludes_threshold_min_includes_it` (manual) |
| BEH-085 A project that still keeps its specs in `docs/specs` is found and searched | proposed | *no test* — owed at `test_search_specs.py#DiscoveryCase.test_legacy_docs_specs_fallback` (manual) |
| BEH-086 An unparseable spec file warns on stderr and the remaining specs are still returned | proposed | *no test* — owed at `test_search_specs.py#DiscoveryCase.test_malformed_spec_warns_and_others_load` (manual) |

All five are owed a test in a file that does not exist yet
(`skills/freya-spec-manager/scripts/test_search_specs.py`). BEH-085 and BEH-086 are
the two that matter most: the fallback is an undefended compatibility promise, and
the warn-and-continue path is the only thing standing between one broken spec file
and a silently shortened corpus for every consumer of `load_all_specs`.

## Intentional Design Decisions

### Full-text search reads a 500-character body preview, not the whole spec

**Decision**: `parse_spec_file` collapses whitespace in the body and keeps the
first 500 characters as `content_preview`. `--query` searches that preview — not
the body. A term that appears only in a spec's *Intentional Design Decisions*
section, several hundred characters down, will not match.

**Rationale**: the preview is one field serving two purposes — it is also what
`--format json` emits per result, so search and output share a single bounded
snippet instead of the loader holding every spec body in memory.

**Security Scan Note**: `freya spec --query "<term>"` returning nothing is not
evidence that no spec discusses that term. Any check that concludes "undocumented"
from an empty search result is over-reading the tool; `grep` the corpus instead.

### `--max-certainty` / `--below` is exclusive at the threshold, `--min-certainty` is inclusive

**Decision**: `--min-certainty 70` keeps a spec with certainty exactly 70;
`--below 100` and `--max-certainty 100` both *drop* a spec with certainty exactly
100. The asymmetry is in one line of `search_specs.search_specs`.

**Rationale**: `--below` is the documented review query — "everything that is not
fully certain" — and `freya spec --sort-certainty --below 100` is what the skill
tells a reviewer to run. That query is only correct if 100 is excluded, so the
inclusive/exclusive split follows the meaning of the flag names rather than being
uniform.

**Security Scan Note**: this is not an off-by-one bug. A linter or reviewer
proposing to "make the bounds consistent" would silently break the review worklist
by putting every fully-certain spec back into it.

### A markdown file with no `id` is not a spec, and is skipped without a warning

**Decision**: `parse_spec_file` returns `None` when frontmatter carries no `id`,
and `load_all_specs` also skips any `README.md` by name. Neither prints anything.
A file that *has* an id but is otherwise malformed does warn (BEH-086).

**Rationale**: the specs tree legitimately holds non-records — the index README, and
whatever a project parks alongside it — and warning on each of them on every query
would train people to ignore the warnings channel that BEH-086 depends on.

**Security Scan Note**: a spec missing from search output may be missing its `id:`
field rather than missing from the tree.

**[NEEDS CLARIFICATION]** the two cases are indistinguishable to the author: a spec
that *should* have an id and lost it in an edit is dropped as quietly as a template
that never had one. Should a file with frontmatter but no `id` warn, while a file
with no frontmatter at all stays quiet?

### Discovery falls back to legacy `docs/specs`, then to a path that need not exist

**Decision**: the search order ends with `docs/specs` and the parent's
`docs/specs`, so an unmigrated project stays queryable. When none of the five
candidates exists, `find_specs_dir` returns `knowledge-base/specs` anyway —
a path that may not be there — and `load_all_specs` returns an empty list for it.
`freya spec` then prints "No specs found matching criteria." and exits 0.

**Rationale**: search is a read-only query, and the legacy fallback exists so that
adopting the knowledge-base layout is never a precondition for reading. Returning a
default path rather than raising keeps every consumer's call site free of a
not-found branch.

**Security Scan Note**: exit 0 from `freya spec` says nothing about whether a spec
corpus exists. Do not treat a clean search as evidence that a decision is
undocumented, or that the corpus was consulted.

**[NEEDS CLARIFICATION]** "no specs match your filters" and "this project has no
specs directory" produce the identical message and exit code. That is the
confidently-empty shape
`knowledge-base/decisions/ADR-005-repair-parsing-substrate-in-place.md` rules out
for the parsing substrate — was the read path deliberately exempted, or has it
simply never been asked the question?

## Related Specs

- [SPEC-016: ADR record integrity and index](./SPEC-016-adr-record-integrity.md) — the other
  reader of `frontmatter.py`; a bad ADR is an error there, a bad spec is a warning here
- [SPEC-018: Declared-intent gate](./SPEC-018-declared-intent-gate.md) — a consumer of
  `load_all_specs`, and the reason a silently shortened corpus would matter

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec (inferred) | Brownfield scan of `skills/freya-spec-manager/scripts/search_specs.py` |
