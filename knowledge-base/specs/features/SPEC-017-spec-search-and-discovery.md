---
id: SPEC-017
title: Spec search and corpus discovery
category: features
tags: [search, specs, discovery, cli, spec-manager]
status: implemented
certainty: 70
created: 2026-08-21
updated: 2026-08-24
related_code:
  - skills/freya-spec-manager/scripts/search_specs.py
  - skills/freya-spec-manager/scripts/frontmatter.py
  - bin/commands.json
  - skills/freya-spec-manager/SKILL.md
intentional_decisions:
  - "Full-text search reads a 500-character body preview, not the whole spec"
  - "--max-certainty/--below is exclusive at the threshold while --min-certainty is inclusive"
  - "A file with no frontmatter is quietly not a spec; a record whose frontmatter carries no id is an alarm"
  - "load_all_specs raises rather than answering a corpus it knows is short"
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
skipped by name, and a file that claims to be a record and cannot be read is an
**alarm**: `load_specs` returns it in a second list, `load_all_specs` raises
`SpecCorpusError` rather than hand back a corpus it knows is short, and
`freya spec` prints the results, names the files on stderr and exits non-zero.
Until 2026-08-24 all four of those cases were dropped — some with a `Warning:`
line on a stream no skill-to-skill caller reads, the missing-`id` case with
nothing on any stream at all.

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

### A file with no frontmatter is not a spec; a record that lost its `id` is an alarm

**Decision**: the discriminator is the frontmatter block, not the `id`.
`parse_spec_file` returns `None` — silently — when `parse_frontmatter` gives back
an empty mapping, which is what a file that never opens a `---` fence looks like,
and `load_specs` also skips any `README.md` by name. A file that *does* open a
fence and then carries no `id:`, or whose frontmatter is outside the grammar, or
whose `certainty:` is not a number, raises `SpecCorpusError` instead.

**Rationale**: the specs tree legitimately holds non-records — the index README, a
prose note, a template — and alarming on each of them on every query would train
people to ignore the channel the real case depends on. But a record that lost its
`id` to a hand edit or a merge conflict is not a non-record, it is a spec the
corpus is missing, and the two Tier-1 gates then certify its `accepted` behaviors
without reading them (ADR-005: never confidently empty).

**Security Scan Note**: a spec missing from search output is now a non-zero exit
and a named file, not an absence to be inferred. An empty `--query` result is
still not evidence of anything (see the preview decision above), but a *short
corpus* is no longer silent.

~~**[NEEDS CLARIFICATION]** ... Should a file with frontmatter but no `id` warn,
while a file with no frontmatter at all stays quiet?~~ **Answered 2026-08-24, and
promoted past "warn".** The question was right and its two halves are now exactly
the two branches above. It was closed as an alarm rather than a warning because of
what the silence bought downstream: `verify_intent` and `verify_links` both read
this loader, and both printed their success sentence at exit 0 over a spec that had
left the corpus.

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
| 2026-08-24 | Answered the third decision's `[NEEDS CLARIFICATION]` and rewrote the decision around the answer: the discriminator is the frontmatter block rather than the `id`, and an unreadable record is an alarm rather than a warning. Added the `load_all_specs` raises/`load_specs` reports split as a fourth decision, and rewrote the Discovery paragraph to match. | A security finding against `parse_spec_file`'s silent-drop path. A dropped spec is a spec whose `accepted` behaviors both Tier-1 gates certify without reading — measured by deleting one `id:` line and watching `verify_intent`, `verify_links` and `--advance` all report success. |
