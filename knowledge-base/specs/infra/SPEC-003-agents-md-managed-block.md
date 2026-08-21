---
id: SPEC-003
title: The managed AGENTS.md block written by `freya init`
category: infra
tags: [agents-md, init, project-scope, markers, atomic-write, safety]
status: implemented
certainty: 80
created: 2026-08-21
updated: 2026-08-21
related_code:
  - bin/agents_md.py
  - bin/freya_cli.py
  - bin/check_skill_conformance.py
  - bin/installer.py
intentional_decisions:
  - "Only a start-of-line marker outside a code fence delimits the managed block"
  - "Malformed markers refuse rather than being repaired"
  - "The file is replaced atomically through a temp file, resolving symlinks and copying mode but not stat"
  - "The skill table is rendered from each SKILL.md at run time, never from a shipped template"
behaviors:
  - behavior_id: BEH-013
    title: "`freya init` writes the block into a project's AGENTS.md and a second run leaves the file byte-identical"
    state: proposed
    level: integration
    adapter: unittest
    entry: bin/agents_md.py
    locator: bin/test_agents_md.py#InitTest.test_running_twice_leaves_the_file_byte_identical
  - behavior_id: BEH-014
    title: A malformed managed block is refused with exit 2 and the file is not touched
    state: proposed
    level: integration
    adapter: unittest
    entry: bin/agents_md.py
    locator: bin/test_agents_md.py#InitTest.test_a_malformed_block_refuses_without_touching_the_file
  - behavior_id: BEH-015
    title: A marker that is only being shown — in prose or inside a code fence — is not the managed block
    state: proposed
    level: unit
    adapter: unittest
    locator: bin/test_agents_md.py#MergeTest.test_a_fenced_example_of_the_markers_is_not_the_managed_block
---

# The managed AGENTS.md block written by `freya init`

## What

`freya init [<project>] [--dry-run]` writes one marker-delimited section into a
project's `AGENTS.md`: a fixed preamble explaining the `freya <command>` /
`freya-<skill>` distinction and the two-commit pattern, plus a table with one
row per installed skill, each row being the first sentence of that skill's
`SKILL.md` description.

The contract is about the *rest* of the file. No `AGENTS.md` means create one;
an existing file with no managed block means append, with existing prose never
rewritten; a managed block present means replace exactly the bytes between the
markers. Everything outside them survives byte for byte, including the file's
line endings, its permission bits and — where it is a symlink — the symlink
itself. A re-run over an unchanged store produces no diff at all.

It is a separate command run on request, not part of installing the suite, and
it installs nothing.

## Why

`AGENTS.md` is the cross-tool instructions standard read by ~30 agents and a
per-repository file by convention, so it has no home in a global install, and
writing into someone's repository unasked — or clobbering a file they already
have — is intrusive. That, and the rejection of a shipped `templates/AGENTS.md`,
is recorded in
[ADR-014](../../decisions/ADR-014-canonical-store-install-contract.md).

The reason the marker protocol is this careful is that every simplification of
it was tried and reverted. Treating a marker found anywhere in the file as the
managed block locked out any user who merely documented freya-devkit in prose or
showed the markers in a fenced example — and worse, deleted the body of that
example while reporting success. Writing straight to the target truncated a
user's file before a byte of the replacement existed. A block first written into
an empty file outvoted the surrounding CRLF prose forever. The rule that
survived all of them is the same one sentence: bytes outside the markers are the
user's, and are never rewritten.

**Certainty (80).** Lower than the other two infra specs by design. The intent
of the marker protocol and the atomic write is explicit in the module docstring
and in ADR-014, and each behavior below has a test named for the guarantee — but
several of the sub-rules (fence detection, the newline vote, `copymode` rather
than `copystat`) are recent corrections rather than an original design, so where
the line falls between "deliberate contract" and "the shape the last bug left"
is a judgement this scan is making from the outside.

## Behavior

| Behavior | State | Verified by |
|----------|-------|-------------|
| BEH-013 `freya init` writes the block into a project's AGENTS.md and a second run leaves the file byte-identical | proposed | `bin/test_agents_md.py#InitTest.test_running_twice_leaves_the_file_byte_identical` (unittest) |
| BEH-014 A malformed managed block is refused with exit 2 and the file is not touched | proposed | `bin/test_agents_md.py#InitTest.test_a_malformed_block_refuses_without_touching_the_file` (unittest) |
| BEH-015 A marker that is only being shown — in prose or inside a code fence — is not the managed block | proposed | `bin/test_agents_md.py#MergeTest.test_a_fenced_example_of_the_markers_is_not_the_managed_block` (unittest) |

Guarantees already covered by tests but left without a behavior record here, for
want of ids: `--dry-run` predicting the failure a real run would hit and
removing its own temp file, a CRLF file surviving byte for byte outside the
markers, a symlinked `AGENTS.md` being written through rather than replaced, and
a store with no discoverable skills refusing instead of emptying the table.

## Intentional Design Decisions

### Only a start-of-line marker outside a code fence delimits the managed block

**Decision**: `_line_start_positions` counts an occurrence of `BEGIN`/`END` only
when it starts a line *and* sits outside a closed code fence. A mid-line mention
in prose and a fenced example are ignored entirely — not counted as ambiguity —
so a file containing both an example and a real block updates only the real one.
An *unclosed* fence does not open a block for this purpose.

**Rationale**: the naive substring search locked out any user who documented
freya-devkit in their own `AGENTS.md`, and treating their fenced example as the
region deleted its body and wrote the managed section inert inside the fence
while reporting "updated". Counting a fenced example as a *duplicate* instead
would refuse forever, which is no better. The unclosed-fence carve-out exists
because hiding a real block from every future run makes each run append another
one — a file that grows forever, which is worse than the defect being fixed.

**Security Scan Note**: parsing a user's markdown with a hand-rolled fence
scanner rather than a markdown library is deliberate — the module has no
dependencies and only needs to answer "is this occurrence the real marker".
Getting it wrong fails closed (refuse, or append) rather than deleting content.

### Malformed markers refuse; nothing is repaired

**Decision**: an unpaired marker, `END` before `BEGIN`, or either marker present
at the start of more than one line raises, and `freya init` exits 2 having
changed nothing. The message names the *target* file, never the store.

**Rationale**: guessing where a half-written block ends is how you eat someone's
notes. Two genuine markers — one left by a previous malformed run, one fresh —
cannot be told apart from the outside, so refusing and asking the human is the
only safe answer. Best-effort repair was explicitly rejected in ADR-014.

**Security Scan Note**: an error path that exits 2 without attempting recovery
is the intended behavior for this command, not an unhandled case. The separate
`except` clauses around the store read and the target merge exist so each fault
names the file actually at fault; collapsing them makes the message point at the
wrong file.

### The write is atomic, resolves symlinks, and copies mode but not stat

**Decision**: content goes to a `tempfile.mkstemp` file (mode 0600, `O_EXCL`) in
the target's directory, the original's permission bits are copied onto it with
`shutil.copymode`, and it is then `os.replace`d onto the **resolved** target
path. `--dry-run` performs all of that except the swap and then removes the temp
file. A failed write removes its own temp, restoring the write bit first.

**Rationale**: `open(target, "w")` truncates before writing a byte, so any
mid-write failure leaves the user's file empty — the exact opposite of this
module's one rule. Replacing an *unresolved* path would unlink a symlinked
`AGENTS.md` and leave a plain file in its place. `copymode` and not `copystat`,
because `copystat` also carried `st_flags` (making the temp of an immutable file
immutable, so `os.replace` failed and even the cleanup could not delete it) and
`st_mtime` (making a file whose contents had just changed still look untouched
to editors, `make` and `rsync`).

**Security Scan Note**: `mkstemp` + `chmod`-by-copymode + `os.replace` in a
directory the user owns is intentional and is the safe form of this write, not a
TOCTOU race: the temp is created exclusively with a random name and 0600, so the
replacement is never world-readable while it is being written.

### The skill table is rendered from the store at run time

**Decision**: rows come from `installer.discover_skills` plus the first sentence
of each `SKILL.md` description, read through the block-scalar frontmatter reader
in `check_skill_conformance`. Nothing is templated, and a store with no
discoverable skills refuses rather than writing a header-only table. Pipes in a
description are escaped so a cell cannot be split.

**Rationale**: a static template would be a tenth place the skill list lives and
would go stale on the next skill added; a bare pointer teaches a reading agent
nothing about when to reach for what. The refusal on an empty store exists
because the alternative is silently deleting every row from the user's file and
reporting "updated".

**Security Scan Note**: content from `SKILL.md` files in the store is
interpolated into a file in the user's repository. The source is the installed
store, the extraction is limited to the description's first sentence, and the
only injection vector into a markdown table — `|` — is escaped.

## Related Specs

- [SPEC-001: The `freya` launcher command surface](./SPEC-001-freya-launcher-command-surface.md) — `init` is a launcher built-in, and its argument handling lives there
- [SPEC-002: Canonical-store install contract](./SPEC-002-canonical-store-install-contract.md) — why this write is per-project and deliberately not part of the install

## Change History

| Date | Change | Reason |
|------|--------|--------|
| 2026-08-21 | Initial spec, inferred from code and tests by the brownfield scan | `freya-spec-manager bootstrap` — all behaviors `proposed`, none reviewed by a human yet |
