# Phase 5 — `freya update`, the notify check, `freya init`, and a doctor that sees orphans

**Portability Track A, phase 5. Status: design — 2026-08-14.** Builds on
[`../../design/portability/01-design.md`](../../../design/portability/01-design.md) §8 and
[`00-vision.md`](../../../design/portability/00-vision.md) §4.4. Phases 1–4b are built and
reviewed; this is the last build phase before validation (phase 6).

---

## 1. Problem

Three commands the design promises do not exist — `freya update` and `freya init` both
exit 2 with `unknown command`, and nothing ever tells a user their store is stale. Phase 3
also left one specific gap here: **relocating the checkout orphans every install link**,
and `doctor` has the information to say so but doesn't.

## 2. Scope

In scope:

1. `freya update` — fetch the store and re-link.
2. A throttled, notify-only update check on ordinary `freya` invocations.
3. `freya init` — write or merge a freya-devkit section into a project's `AGENTS.md`.
4. `doctor` warns about orphaned links (moved store, deleted skill).
5. A multi-agent install becomes all-or-nothing across agents, not just within one.

Out of scope: auto-apply updates (rejected in vision §4.4 — the `stable`-branch escape
hatch stays documented, unbuilt); any change to how the store is first obtained; phase 6
validation.

## 3. Decisions

| Decision | Choice | Why not the alternative |
|---|---|---|
| Update mechanism | Git-only: `fetch` + `merge --ff-only` in the existing checkout, then re-link | A tarball fallback means writing a destructive replace path that can't be tested offline; a managed clone under `~/.freya` would overturn phase 3's shipped "the checkout is the store" model |
| Notify check | Synchronous `git ls-remote` with a hard 2s timeout, cached ~24h | A detached background probe never blocks but adds orphaned children and a cache race, and reports news one run late; reading the already-fetched ref costs nothing and would almost never fire |
| `AGENTS.md` content | Fixed preamble + a skill list generated from `SKILL.md` frontmatter | A static template is a tenth place the skill list lives and goes stale on the next skill; a bare pointer teaches a reading agent nothing about when to reach for what |

## 4. Architecture

Two new modules, two touched. Each has one job and is testable without the others.

| File | Role |
|---|---|
| `bin/updater.py` *(new)* | git interrogation, the update itself, the throttled notify check |
| `bin/agents_md.py` *(new)* | render and merge the `AGENTS.md` block |
| `bin/freya_cli.py` | wire `update` / `init`, invoke the notify check, extend `doctor_checks()` |
| `bin/installer.py` | new `audit_agent()`; plan every agent before mutating any |

### 4.1 `installer.audit_agent(store, agent, target_dir=None)`

The keystone addition. `plan_agent()` iterates the skills present **in the store**, so an
entry in the agent's directory whose skill no longer exists in the store is invisible to
it — which is exactly the orphan case both new callers care about. `audit_agent` scans the
**agent directory** instead and classifies every `freya-*` entry:

| Status | Meaning |
|---|---|
| `ok` | symlink into this store, or a copy whose `MARKER` names this store |
| `stale-store` | our-shaped link or marker pointing at a path that is not this store — the checkout moved, or a second store exists |
| `orphan-skill` | points into this store's `skills/`, but that skill no longer exists |
| `foreign` | a `freya-*` symlink we cannot account for |
| `occupied` | a real file or directory that is not ours |

`update` uses it to prune; `doctor` uses it to warn. One function, both callers, one
definition of "ours" — the ownership rules stay exactly those `classify()` already
enforces, including that a real directory is only ever ours if it carries the marker.

## 5. `freya update`

`freya update [--dry-run]`.

**Preconditions**, evaluated before anything is fetched or written; each failure exits 2
with its own actionable message:

1. The store is a git work tree (`git rev-parse --show-toplevel` resolves to the store).
   A non-git store is told to re-clone rather than guessed at.
2. The current branch has an upstream.
3. The working tree is clean — local changes in the store are never merged over.

**Then:** `git fetch <remote>`, `git merge --ff-only <upstream>`. A diverged branch refuses
and says so; no rebase, no merge commit, no stash. Report the old and new SHA and the
number of commits, or "already up to date".

**Then re-link.** This is not a no-op even in symlink mode: an existing link picks up file
edits for free, but a **newly added** skill has no link at all and a **deleted** one leaves
a dangling link behind. Via `audit_agent`, for every agent that currently holds at least
one of our entries:

- missing links for skills now in the store → created, in the mode that agent is already
  installed in (symlink, or copy detected by marker);
- `orphan-skill` entries → removed;
- `ok` copy entries → re-copied, since a copy tracks nothing;
- `stale-store`, `foreign`, `occupied` → left alone and reported, never silently replaced.

Finally, stamp the notify-check state so an update does not immediately re-announce itself.

`--dry-run` reports the preconditions, whether the remote has moved (via `ls-remote`, which
writes nothing locally), and the re-link plan.

## 6. The notify check

State lives in `~/.freya/update-check.json`: the last-checked epoch and the last verdict.
It runs on ordinary commands and is skipped for `help`, `update`, `install`, `uninstall`.

- **Throttle:** a cache under ~24h old is printed from and no network is touched.
- **Network:** otherwise `git ls-remote <remote> <branch>` under a 2s timeout, compared
  against local `HEAD`. The message says the remote has moved and to run `freya update` —
  it deliberately does not claim a commit count, which would need a real fetch.
- **It cannot break a command.** The entire check is wrapped so any exception is swallowed;
  it never alters the exit code and never prints a traceback.
- **A failure still stamps the timestamp**, so an offline machine goes quiet for a day
  rather than paying the timeout on every invocation.
- **Output goes to stderr**, keeping stdout clean for agents parsing command output.
- **Opt-outs:** `FREYA_NO_UPDATE_CHECK=1`, and any store that is not a git checkout.

`doctor` reports the same status as a normal check line, but unthrottled — paying 2s in a
diagnostic is the point of a diagnostic.

## 7. `freya init`

`freya init [<project>] [--dry-run]`, defaulting to the current directory. It writes
`AGENTS.md` only; it installs nothing.

(This spec originally called the argument `--project PATH`; the shipped CLI takes it as a
positional `<project>` instead and rejects `--project` with exit 2 — the line above has been
corrected to match what shipped, in the final review fix wave, 2026-08-14.)

The managed region is marker-delimited:

```markdown
<!-- freya-devkit:begin (managed by `freya init` — edits inside are overwritten) -->
## freya-devkit

<preamble: what the toolkit is; `freya <command>` is the CLI and `freya-<skill>` is a
skill name; commands are run through the launcher, not through per-agent paths; the
two-commit pattern separates code changes from generated artifacts>

| Skill | Use it for |
|---|---|
| `freya-code-graph` | <first sentence of its SKILL.md description> |
| … | … |
<!-- freya-devkit:end -->
```

**Merge rules:**

| Existing state | Behaviour |
|---|---|
| No `AGENTS.md` | Create it containing the block |
| Exists, no markers | Append the block; existing prose is never rewritten |
| Exists, markers present | Replace between the markers; every byte outside them is preserved, so a second run produces no diff |
| Markers malformed (unpaired, or `end` before `begin`) | Refuse, exit 2, change nothing |

Skills come from `installer.discover_skills(store)` — the store is the source of truth, and
`init` runs from it. Each row's text is the first sentence of the skill's `description`,
whitespace-collapsed; the frontmatter reader is a small extension of the one already in
`bin/check_skill_conformance.py`, which parses keys and `name` but not values.

`update` and `init` are already members of `BUILTIN_COMMANDS` in the conformance checker,
so documenting them does not trip R3.

## 8. Doctor and the partial-install gap

1. **Orphan warning.** Using `audit_agent`, `doctor` warns when any entry is `stale-store`
   or `orphan-skill`, naming the path it points at and the fix: the checkout moved — re-run
   `freya install --force`, or `freya update`.
2. **Honest wording.** The current line says "no agent is linked"; a copy install is not
   linked but is installed. Report per agent as `claude (10, symlink)` / `copilot (10, copy)`.
3. **All-or-nothing across agents.** `apply_plan` already raises before mutating anything —
   but per agent. `installer.main()` loops agents and applies each in turn, so
   `--agent claude --agent copilot` with a blocker under the second leaves the first fully
   linked. Fix: plan every agent, collect blockers across all of them, and raise before the
   first mutation. The guarantee becomes per-invocation.

## 9. Error handling

Every failure is a message and an exit code, never a traceback. Exit 2 for a refusal
(non-git store, dirty tree, diverged branch, malformed markers, blocked install); exit 1
for a `doctor` that found a `fail`; exit 0 for "already up to date". The notify check is the
one component that must never fail loudly — its exceptions are swallowed by design, and that
is the single place in this phase where a bare `except` is correct.

## 10. Testing

**Real git in temp directories** for `updater`: an origin repo plus a clone, covering
fast-forward, dirty refusal, missing upstream, non-git store, and a diverged branch. Phase
4b's finding was that mocks model a well-behaved dependency and leave the failure paths
unexamined; git is free and deterministic, so there is no reason to repeat that here. Tests
skip cleanly if `git` is absent.

**Injected runner** for the notify check — a hang cannot be produced honestly any other way.
Cases: fresh cache makes no network call; stale cache does; timeout and non-zero exit both
stay silent *and* stamp the timestamp; `FREYA_NO_UPDATE_CHECK` short-circuits; a non-git
store short-circuits; a raising runner does not change the command's exit code.

**Tmpdir fixtures** for `init` (create, append, idempotent replace, malformed markers,
dry-run writes nothing), `audit_agent` (dangling link, moved store, orphaned skill, copy
install, foreign entry), and the all-or-nothing install (a blocker under the second agent
leaves the first untouched).

Suites are stdlib `unittest`, run as `cd bin && python3 -m unittest test_updater -v`,
matching the existing `bin/test_*.py` layout.

## 11. Definition of done

- `freya update` fast-forwards a clean checkout, re-links, and refuses each precondition
  failure with its own message.
- A stale store prints one notify line to stderr, at most once a day, and never changes an
  exit code.
- `freya init` is idempotent on a second run and never rewrites prose outside its markers.
- `freya doctor` names an orphaned link and the command that fixes it.
- `python3 bin/check_skill_conformance.py` exits 0; every `bin/test_*.py` suite passes.
- README and `docs/skill-reference.md` document both new commands.

## 12. Deliberately not fixed here

- The `mitigated` disposition is still unreachable (pre-existing; faithfully ported).
- R9 remains file-scoped.
- Concurrent installs still race between classify and link; non-destructive, unlocked.
- `uninstall` is absent from `BUILTIN_COMMANDS` while `install` is present, and
  `CONTRIBUTING.md` still advertises the `workflows/` deep-audit engine deleted in
  `39dfbea`. Both are one-line fixes, noted here so they are not lost.
