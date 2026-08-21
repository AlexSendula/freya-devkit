---
id: SPEC-014
title: Existing Documentation Detection
category: features
tags: [docs-manager, detection, knowledge-base, layout, reverse-sync]
status: implemented
certainty: 85
created: 2026-08-21
updated: 2026-08-21
related_code:
  - skills/freya-docs-manager/scripts/detect_project.py
  - skills/freya-docs-manager/scripts/test_detect_project.py
intentional_decisions:
  - "Documentation homes are searched in a fixed precedence order: knowledge-base/reference, then knowledge-base, then the legacy docs/"
  - "A candidate directory containing no markdown is not a documentation directory, however it is named"
  - "Only the first matching layout contributes its files; the others are not merged"
behaviors:
  - behavior_id: BEH-067
    title: A project that has adopted the knowledge-base layout is reported as documented, and its reference/ directory wins over a legacy docs/
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#ExistingDocsTest.test_knowledge_base_wins_when_both_exist
  - behavior_id: BEH-068
    title: A knowledge-base directory holding no markdown is not reported as a documentation directory
    state: proposed
    level: unit
    adapter: unittest
    locator: skills/freya-docs-manager/scripts/test_detect_project.py#ExistingDocsTest.test_a_knowledge_base_holding_only_settings_is_not_a_docs_dir
---

# Existing Documentation Detection

## What

Part of `freya detect-project`'s output: where this repository's documentation already lives.
The answer is three fields — `docs_dir` (an absolute path, or `null`), `layout` (`knowledge-base`
or `docs`, or `null`) and `files` (the markdown in that directory, plus any root-level
`README.md`, `CLAUDE.md`, `AGENTS.md`, `CONTRIBUTING.md`, `CHANGELOG.md`).

Candidate homes are tried in a fixed order — `knowledge-base/reference/`, then
`knowledge-base/`, then `docs/` — and the first one that exists **and contains markdown**
wins. Nothing is merged across layouts: a repo mid-migration reports its new home, not both.
Root-level documents are always reported, including when no documentation directory was found
at all, so a bare repo with a README is distinguishable from an empty one.

## Why

This is what tells docs-manager whether a run is a create or a reverse-sync. Getting it wrong
is not a cosmetic error: the detector used to look only at `docs/`, so any project that had
adopted the toolkit's own `knowledge-base/` layout — including this repository, once it moved
its own tree — was reported as having no documentation directory and no existing files, and
every run planned a from-scratch create over documentation that already existed. That was
found by running docs-manager against freya-devkit itself and fixed on 2026-08-21, together
with the test class that now pins it.

The "must contain markdown" rule comes from the same fix. `knowledge-base/` springs into
existence the moment code-graph writes `settings.json` into it, so an existence check alone
would have reported documentation on a project that has none — suppressing the create the
project actually needs, which is a worse failure than the one being repaired.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-067 The knowledge-base layout is found, and `reference/` outranks a legacy `docs/` | proposed | `test_detect_project.py#ExistingDocsTest.test_knowledge_base_wins_when_both_exist` (unittest) |
| BEH-068 A candidate directory with no markdown is not a documentation directory | proposed | `test_detect_project.py#ExistingDocsTest.test_a_knowledge_base_holding_only_settings_is_not_a_docs_dir` (unittest) |

Scenarios covered by neighbouring tests in the same class and folded into the two behaviors
above: `reference/` beating the knowledge-base root
(`ExistingDocsTest.test_reference_wins_over_the_knowledge_base_root`), the legacy `docs/`
layout still resolving (`.test_the_legacy_docs_layout_still_works`), and root-level documents
being reported with no docs directory at all
(`.test_root_documents_are_reported_with_no_docs_dir_at_all`).

## Intentional Design Decisions

### Precedence is fixed, and only one layout is reported

**Decision**: `DOC_DIR_CANDIDATES` is an ordered tuple, most specific first, and the loop
breaks on the first hit. A repository holding both `docs/architecture.md` and
`knowledge-base/reference/ARCHITECTURE.md` reports only the latter, and the legacy file does
not appear in `files`.

**Rationale**: A half-migrated repository is the normal case during adoption, and reporting
both homes would make docs-manager plan updates against documents it is in the middle of
replacing. Choosing the toolkit's own layout means adoption is a one-way door: once
`knowledge-base/reference/` has content, the old tree stops being consulted.

**Security Scan Note**: Not security-relevant. The omission of the legacy files from `files`
is deliberate, not a filtering bug.

### Only the top level of the chosen directory is listed

**Decision**: `files` is built from `os.listdir` on the chosen directory, not a recursive walk,
so markdown in subdirectories of `knowledge-base/reference/` is not listed and does not make an
otherwise-empty directory count as documented.

**Rationale**: The field answers "which documents does this project have", where a document is
one of the standard top-level reference files docs-manager writes. A recursive walk would drag
in specs, decisions and explanations, which have their own owners.

**Security Scan Note**: Not security-relevant. If a reviewer expects recursion here, the
non-recursive listing is the intended reading of "documentation directory", not an oversight.

## Related Specs

- [SPEC-013: Project Stack Detection](./SPEC-013-project-stack-detection.md) — the rest of the
  same `detect-project` output
- [SPEC-015: The Docs Graph](./SPEC-015-docs-graph.md) — what those documents cite

## Notes on Certainty

85, the highest of the three specs in this area. The intent is unusually well evidenced: the
module-level comment on `DOC_DIR_CANDIDATES` states the bug this replaced, the test class
docstring names how it was found, and the "empty directory is not a hit" test spells out why
the obvious simplification would be worse. Not higher because it is still inference — no human
has confirmed that the *precedence order itself* (rather than merging the two layouts) is the
intended long-term rule.

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred by brownfield scan | Behaviors recorded as `proposed`; no human has confirmed this intent yet |
