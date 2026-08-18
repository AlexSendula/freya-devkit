# Portability — Design Spec (01)

**Track A. Status: design — 2026-07-14; reviewed & corrected 2026-07-17; corrections appended 2026-08-18 after the track shipped.** Builds on [`00-vision.md`](00-vision.md); that file holds the *why* and the resolved high-level decisions. This file is the *how* — concrete enough to write implementation plans from. MVP targets **GitHub Copilot + Claude Code**.

> **How to read this file (2026-08-18).** It is a **design record**, not a live
> specification. Nine statements below turned out differently in implementation. Each
> keeps its original wording with a dated `> **Correction …**` block underneath, because
> the reasoning that led somewhere else is the useful part of a design record — silently
> rewriting it would leave the *why* unrecoverable. Where a correction and the original
> disagree, **the shipped code is the ground truth**, then the correction, then the
> original. Corrections live under: §1 (the `${CLAUDE_PLUGIN_ROOT}` counts), §2 and §4.1
> (`templates/AGENTS.md`, which was never built), Decision 1 and §7 and §10 (the PATH
> bootstrap, whose premise was wrong), Decision 2 (`--project`, never shipped),
> Decision 3 (who applies the `freya-` prefix — inverted), and §9 (the `wrap-up`
> validation criterion).

---

## 1. Current-state grounding (what is *actually* Claude-specific)

Verified against the code (2026-07-17):

- **The engine already self-locates.** Every script resolves its cross-skill dependencies from its own path — e.g. `behavior_graph.py` does `Path(__file__).resolve().parents[2] / "spec-manager" / "scripts"` and inserts it on `sys.path`; `run_behaviors.py`, `collect_status.py`, `drift.py`, `project_shape.py` all do the same. **No `.py` file uses `${CLAUDE_PLUGIN_ROOT}`.** Because `.resolve()` follows symlinks, a symlinked skill dir still resolves back to the canonical store where its siblings live. **Constraint:** this requires the `skills/<name>/scripts/` tree to stay intact as a unit (siblings under one `skills/`).

- **The Claude-specific surface is four things** (measured, not estimated):

  | # | Surface | Size | Nature |
  |---|---|---|---|
  | 1 | `${CLAUDE_PLUGIN_ROOT}` in SKILL.md | **83** (80 script invocations + 2 Workflow-engine refs + 1 prose) | mechanical |
  | 2 | `/freya-devkit:<skill>` slash refs | **172** in SKILL.md, **+33** in `docs/*.md` | mechanical |
  | 3 | LLM-fan-out orchestration prose | 3 flows | needs rewrite (§6) |
  | 4 | **Workflow-tool dependency** (`audit` mode) | 1 flow | re-hosted in our own driver (§6.1) |

  Per-skill `${CLAUDE_PLUGIN_ROOT}` counts: spec-manager 34, wrap-up 25, code-graph 9, behavior-graph 7, security-scan 3, behavior-runner 2, status 2.

  > **Correction (2026-08-18, after implementation).** That list sums to **82**, not the
  > 83 in the table above it. `security-scan` is **4**, not 3 — it has four occurrences on
  > three lines, and the line count was written down. Re-counted against `main`:
  > spec-manager 34, wrap-up 25, code-graph 9, behavior-graph 7, **codebase-security-scan
  > 4**, behavior-runner 2, status 2 = 83, which reconciles. Also: "**No `.py` file uses
  > `${CLAUDE_PLUGIN_ROOT}`**" is literally false — `skills/spec-manager/scripts/search_specs.py:34`
  > *mentions* it in a comment (84 occurrences under `skills/` in total, against 83 in
  > SKILL.md). The claim it was making is correct and is what mattered: no `.py` file
  > *depends* on the variable. The port is complete either way — zero occurrences remain
  > under `skills/`, enforced by conformance rule R1 with no exemptions.

  The three fan-out flows (surface 3): `codebase-security-scan` (parallel category scanners + parallel adversarial verification), `docs-manager` (coordinator + parallel doc-type workers), `spec-manager scan` (coordinator + parallel discovery agents).

  > **Note:** surface 2 is *larger than surface 1* — the slash-reference rewrite is the biggest mechanical chunk of this project, not the invocation rewrite. Plan accordingly.

- **Two lesser conformance issues:**
  - Non-standard **`compatibility:` frontmatter** in `codebase-security-scan` and `dependency-vulnerability-check`; the former also embeds Claude tool names (`Agent`, `Read`, …) and `/freya-devkit:` slash names.
  - **`askUserQuestion`** referenced by name in `codebase-security-resolver` — a Claude tool; genericize to "ask the user".

- **Latent bug the port fixes for free:** all 80 invocations call bare **`python`** (0 use `python3`). On many modern systems `python` does not exist. The launcher resolves the interpreter **once**, correctly, for every agent — see §3.

- **`.claude-plugin/`** (`plugin.json`, `marketplace.json`) is the Claude distribution manifest — kept for the Claude path (dual distribution), untouched.

**Implication:** the port is a bounded, mechanical-plus-orchestration job on the *skill layer*, not the engine. The scripts are already portable.

## 2. Architecture

```
                    canonical store  (the freya-devkit checkout — skills/ intact)
                    ├── skills/<name>/{SKILL.md, scripts/, references/}
                    ├── bin/freya            ← self-locating launcher
                    └── templates/AGENTS.md  ← optional, per-project (§4.1)
                          │  symlink (copy fallback), dirs prefixed freya-*
        ┌─────────────────┼──────────────────────┐
        ▼                 ▼                        ▼
  ~/.claude/skills/  ~/.copilot/skills/     ~/.agents/skills/   ← per-agent skill dirs
        │                 │                        │
        └───── SKILL.md invokes ──►  `freya <cmd> <args>`  (on PATH) ──► runs canonical script
```

Two new pieces: the **`freya` launcher** and the **installer**. The engine and the per-skill scripts are unchanged.

> **Correction (2026-08-18, after implementation).** `templates/AGENTS.md` in the diagram
> above **was never built**, and no `templates/` directory exists in the store. The
> phase-5 spec reversed the decision on purpose — see the correction under §4.1, which
> carries the reasoning. The rest of the diagram is accurate as shipped, with one naming
> detail: the per-agent directories hold `freya-<skill>` entries because the *store's*
> directories are named that way, not because the installer renames anything on the way
> in (see the correction under Decision 3).

## 3. The `freya` launcher (keystone)

A single stdlib-Python entrypoint that gives every agent one clean, self-locating command surface.

- **Location & self-location:** lives at `bin/freya` in the canonical store; resolves the suite root via `Path(__file__).resolve()`. No env var, no per-agent config.
- **Interpreter resolution:** the launcher runs under whichever Python invoked it and executes target scripts with **`sys.executable`** — eliminating the bare-`python` hazard (§1) across all agents and platforms.
- **Command surface:** `freya <command> [args…]`, where `<command>` maps to an invocable script via a small **command manifest** (checked-in `bin/commands.json`, or a table in the launcher):
  | Command | Runs |
  |---|---|
  | `freya code-graph …` | `code-graph/scripts/graph_ops.py` |
  | `freya behavior-graph …` | `behavior-graph/scripts/behavior_graph.py` |
  | `freya behavior-runner …` | `behavior-runner/scripts/run_behaviors.py` |
  | `freya status …` | `status/scripts/collect_status.py` |
  | `freya spec …`, `freya adr …`, `freya principles …`, `freya drift …`, `freya verify-intent …`, `freya verify-links …` | the matching `spec-manager/scripts/*.py` |
  Args after `<command>` pass through unchanged (so `freya behavior-graph --build --project .` → `<sys.executable> …/behavior_graph.py --build --project .`).
- **Built-in subcommands:** `freya install`, `freya update`, `freya doctor` (canonical store found, PATH ok, python ok, agents linked), `freya init` (optional per-project `AGENTS.md`, §4.1), `freya help`.
- **Invocation:** execs the target script, inheriting stdout/stderr/exit code. Because it runs the *canonical* script, `__file__`-based sibling resolution always works.

> **DECISION 1 — RESOLVED (2026-07-17): unify on `freya` everywhere, including Claude.** One SKILL.md set, `freya`-based, works on every agent — no per-agent variants, no drift, and the interpreter bug is fixed once. **Cost:** `freya` must be on `PATH` under Claude too, so the marketplace-plugin path needs a small first-run bootstrap that links `bin/freya` into a PATH dir (and `freya doctor` reports it if missing).

> **Correction (2026-08-18, after implementation): the stated cost does not exist, and the bootstrap was correctly never built.**
>
> The premise — that a Claude marketplace-plugin install puts nothing on `PATH` — is
> **wrong**. Claude Code adds `<plugin-cache>/<plugin>/<version>/bin` to the `PATH` of
> every session, for every installed plugin. Verified empirically on 2026-08-18 (macOS):
> inside a Claude Code session `$PATH` contained
> `~/.claude/plugins/cache/freya-devkit/freya-devkit/0.1.0/bin`, alongside the same
> `…/<version>/bin` entry for every other installed plugin — and it was there *even
> though the cached 0.1.0 snapshot has no `bin/` directory at all*, which is what shows
> the entry is added by convention rather than discovered. `bin/freya` is mode `100755`
> in git, so from 0.2.0 on it resolves by bare name on that path with nothing to run
> first. The half of the sentence that stands is the last clause: `freya doctor` does
> carry a `freya on PATH` check, and it reports `warn … not found — run the installer or
> add bin/ to PATH` when the launcher is missing.
>
> **What this costs instead is a stated dependency.** The behaviour is *undocumented* by
> the host and nothing in this repo tests it — the CI install job exercises `install.sh`
> and `install.ps1`, not a marketplace install, which no runner can perform. So it is a
> real dependency on unversioned host behaviour: if Claude Code ever stops adding that
> directory, every `freya <command>` in every SKILL.md fails on the plugin path at once.
> The remedy is already shipped and needs no new code — run `install.sh` from the store
> (a `git clone`, or the plugin-cache checkout itself), which places the launcher in
> `~/.local/bin`. Worth re-confirming on each major Claude Code release; a `doctor` check
> cannot see it, because `doctor` only ever runs *through* the launcher it would be
> checking for.
>
> **Windows is the one gap on this path.** The store ships `bin/freya` extensionless, and
> Windows resolves a bare command name through `PATHEXT`, which an extensionless file is
> not in. The `freya.cmd` shim that makes `freya` runnable there is *generated by the
> installer*, not checked in, so a plugin-cache `bin/` on `PATH` does not by itself give
> a Windows user a runnable `freya`. On Windows, use `install.ps1`.

## 4. Install flow

`install.sh --agent <copilot|claude> [--project|--global] [--copy]` (an `install.ps1` mirror for Windows):

1. **Canonical store** = the checkout itself (from `git clone`, or a managed clone the installer places). Holds `skills/` intact.
2. **`freya` on PATH** — symlink `bin/freya` into a PATH dir (`~/.local/bin`), or print the line to add. `freya doctor` verifies.
3. **Link skills into the agent's dir** — for each skill, symlink (or `--copy`) the skill dir into:
   - **Claude:** `~/.claude/skills/` (personal). *(The marketplace plugin remains a valid alternative — §7.)*
   - **Copilot:** `~/.copilot/skills/` (personal) — or `.github/skills` with `--project`.
   - Prefer the cross-agent **`~/.agents/skills/`** as the link target where the agent honors it.
4. **Copy fallback** (`--copy`, auto on Windows without symlink privilege): materialize files instead of symlinking; `freya update` re-copies.

> **DECISION 2 — RESOLVED: default scope is personal/global** (`~/.copilot/skills`, `~/.claude/skills`), because freya-devkit is a general toolkit you want in every project, not vendored per-repo. `--project` (`.github/skills`, committed) is opt-in for teams.

> **Correction (2026-08-18, after implementation): `--project` was deferred and never
> shipped.** The installer defines `--agent`, `--copy`, `--force`, `--dry-run` and
> `--uninstall` (plus three suppressed test hooks); there is no `--project`, no
> `--global`, and no per-agent project-path table — so the `[--project|--global]` in §4's
> synopsis above will fail argparse with `unrecognized arguments`. The default scope
> shipped exactly as decided; only the opt-in half is missing. The deferral and its
> rationale are recorded in `docs/superpowers/plans/2026-07-30-installer.md`
> ("Deliberately not built here: `--project` scope"), which was the only place it was
> written down until now. Teams that want a vendored, committed install have no supported
> flag today.

> **DECISION 3 — namespace the installed skill dirs `freya-*`.** Claude's plugin install namespaced skills as `freya-devkit:<skill>`; a shared `~/.agents/skills/` has **no namespace**, and our roster includes very generic names — **`status`**, `code-graph`, `wrap-up`, `docs-manager` — that will collide with other installed skills and confuse discovery. So install directories (and the `name:` in the installed copy) as `freya-status`, `freya-code-graph`, … The *repo* keeps its current names; the installer applies the prefix. Cross-references inside SKILL.md must use the same prefixed names (§5).

> **Correction (2026-08-18, after implementation): the last sentence is inverted.** The
> *repo* carries the `freya-*` names and **the installer applies no prefix at all** — it
> symlinks (or copies) a `freya-<skill>` directory straight across, rewriting nothing.
> The reason is a spec constraint this design missed: the Agent Skills spec requires a
> skill's frontmatter `name` to equal its parent directory name, so a renamed directory
> with an unrenamed `name:` is non-conformant, and rewriting `name:` at install time
> would mean the installed copy diverges from the store on every update. Renaming the ten
> repo directories was the cheaper and more honest fix. Everything the decision was *for*
> holds unchanged — the installed names are `freya-status`, `freya-code-graph`, … and
> cross-references use them. Consequence for existing 0.1.0 users: invocation names
> changed, `/freya-devkit:wrap-up` → `/freya-devkit:freya-wrap-up`. See
> [`../../migrations/skill-rename.md`](../../migrations/skill-rename.md).

### 4.1 `AGENTS.md` — per-project, optional (not part of the global install)

`AGENTS.md` is a **per-repository** file by convention, so it has no natural home in a personal/global install, and writing into a user's repo unasked (or clobbering an existing `AGENTS.md`) is intrusive. Therefore:

- Ship a **template** in the canonical store (`templates/AGENTS.md`).
- **`freya init`** (run inside a project, explicitly) writes or **merges** a short freya-devkit section into that project's `AGENTS.md`.
- Content is deliberately small: what freya-devkit is, the `freya <command>` surface, and when to reach for `wrap-up` / `status`. Skill discovery already handles the rest — duplicating skill instructions here would bloat context for no gain.

> **Correction (2026-08-18, after implementation): there is no `templates/AGENTS.md`, and
> that is deliberate.** The block is **rendered, not copied**: the fixed prose is the
> `PREAMBLE` constant in `bin/agents_md.py`, and the skill table under it is generated
> from the store at run time. The phase-5 spec
> (`docs/superpowers/specs/2026-08-14-phase-5-update-init-design.md`) records the reversal
> — "a static template is a tenth place the skill list lives and goes stale on the next
> skill" — but this design was never amended, so a contributor looking for
> `templates/AGENTS.md` found nothing and no pointer. **To change what `freya init`
> writes, edit `bin/agents_md.py`.** The other two bullets shipped as written.

## 5. SKILL.md conformance (de-Claude-ify)

Mechanical, script-preserving edits across the skill layer:

- **Invocation (83 sites):** `python "${CLAUDE_PLUGIN_ROOT}/skills/<skill>/scripts/<script>.py" <args>` → `freya <command> <args>` (mapping per §3).
- **Slash refs (172 + 33):** `/freya-devkit:<skill>` → the prefixed skill name (`freya-<skill>`, per Decision 3) or the relevant `freya` command. This is the largest mechanical chunk — script it, then review.
- **Frontmatter:** reduce to the standard core (`name`, `description`); drop the non-standard `compatibility:` fields (fold any real requirement into the body prose).
- **Tool names:** replace `askUserQuestion` with agent-neutral phrasing ("ask the user").
- Scripts themselves: **unchanged.**

## 6. Portable orchestration

For `codebase-security-scan`, `docs-manager`, and `spec-manager scan`, rewrite the "spawn N agents in parallel (via the Task tool)" prose into an **agent-neutral pattern**:

1. **Coordinator step** (already agent-neutral): analyze → produce a list of **N independent worker tasks**, each self-contained (scope + what to analyze + what to return).
2. **Scheduling block** (new, portable): *"Run these N tasks. If your agent supports parallel subagents (Claude Task tool; Copilot delegation / `/fleet`; Cursor; …), dispatch them concurrently; otherwise run them sequentially. Then collect and merge results."* Note the ~7× token cost of parallel fan-out so the agent/user can choose sequential.
3. **Worker prompt** stays in the SKILL.md as a reusable task template.

This preserves the coordinator+worker *design* while making the *scheduling* the host's choice — parallel where available, sequential fallback everywhere (Aider, Gemini CLI, older Copilot).

### 6.1 `audit` mode — port it by owning the orchestration (Decision 4)

`codebase-security-scan audit` runs on the Claude **Workflow tool** (`workflows/codebase-security-audit.js`). Copilot has multi-agent orchestration (declarative `.agent.md` subagents, `/fleet`, VS Code multi-agent, concurrency/depth limits) but **no deterministic *scripted* primitive**: decomposition is model-driven, and there is no schema-validated structured return. Audit's rigor lives precisely in the deterministic parts — loop-until-dry, cross-round dedup, N-skeptic majority voting — so mapping it onto model-driven delegation would turn guarantees into suggestions.

**Decision: invert the dependency.** Re-implement the audit engine as **our own driver** — a plain Python script in the suite (`freya security audit`) that owns all control flow, and calls the host agent **headlessly** as a worker for each LLM task. Reading the existing workflow confirms this is mostly a relocation, not a redesign: ~90 % of that file is ordinary logic (`while` loop, `Set` dedup, `upheld * 2 > total` vote math, disposition branching); only the `agent(...)` call is Claude-provided.

**Agent adapter** — the only per-agent surface (~20 lines each), verified 2026-07-17:

| Need | Claude Code | Copilot CLI |
|---|---|---|
| Headless prompt | `claude -p "…"` | `copilot -p "…"` (or piped stdin) |
| Clean output | `--output-format text\|json\|stream-json` | `-s` (silent; suppresses session metadata) |
| Structured JSON | `--output-format json` (session envelope only) | *(none)* |
| Read-only enforcement | `--allowedTools "Read Grep Glob"`, `--disallowedTools "Write Edit"` | `--allow-tool='read'`, `--deny-tool=write` (**deny always beats allow**) |
| Suppress clarifying questions | implicit with `-p` | `--no-ask-user` |
| Model pin | `--model` | `--model` |

**Consequences the driver must own:**

- **Schema validation moves to us.** Neither CLI enforces a *content* schema (Claude's `json` is a session envelope; the payload is still text). So the driver does: prompt-level JSON contract → extract JSON from stdout → validate against the schema → **bounded retry on invalid**. This restores exactly what the Workflow tool's `schema:` provided — for *both* agents.
- **Parallelism is ours.** `parallel()` becomes a bounded worker pool over subprocesses (stdlib `concurrent.futures`), with a configurable concurrency cap.
- **The no-writes boundary is preserved.** Today enforced by `agentType: 'Explore'`; now enforced by the adapter's tool flags on both agents.
- **Degradation:** if no supported agent CLI is found/authenticated, `audit` reports that clearly and points to `scan` / `update` (which remain fully portable and are what `wrap-up` uses). Nothing in the core workflow depends on `audit`.
- **One implementation everywhere** — the JS workflow is retired, consistent with Decision 1. Bonus: the driver is unit-testable with a mocked `ask_agent()`, which the Workflow version never was.

### 6.1.1 Spike results — **executed 2026-07-27, decision confirmed**

Run against a fixture (`/tmp/freya-spike/src/login.js` with SQL injection, hardcoded secret, plaintext password compare, forgeable token), Copilot CLI **1.0.75** + Claude Code, identical prompt with a JSON contract.

**✅ Feasible — both agents returned schema-valid findings.** All documented flags confirmed present (`-p/--prompt`, `-s/--silent`, `--no-ask-user`, `--allow-tool`, `--deny-tool`, `--allow-all*`, `--model`).

**Output shapes differ — the driver must normalize per adapter:**

| | Copilot (`-p … -s`) | Claude (`-p … --output-format json`) |
|---|---|---|
| Envelope | none — plain text | **array of session events**; payload at the `type=="result"` element's `.result` |
| Payload purity | **narration precedes the JSON** → needs salvage-extraction | clean JSON → direct parse |
| Telemetry | none exposed | `total_cost_usd`, `num_turns`, `duration_ms`, `usage`, `permission_denials` |
| This run | 5 findings, ~62 s | 8 findings, ~26 s, $0.396 |

The prototype `extract_json()` (strip fences → direct parse → else brace-balanced scan for the first `{"findings"…}`) handled **both** cleanly, and a stdlib schema check passed with zero errors on each. This validates the extract → validate → bounded-retry design; `-s` alone is **not** a JSON guarantee.

**🔴 Read-only enforcement — the allowlist is load-bearing (important):**

| Config | Result |
|---|---|
| Claude `--allowedTools "Read Grep Glob" --disallowedTools "Write Edit"` | **Held.** It attempted `Bash` 3× (shell redirection) — all denied (`permission_denials: [Bash×3]`). |
| Copilot `--allow-tool='read' --deny-tool=write` | **Held.** Both the write tool *and* an explicit shell-redirect attempt failed. Still able to discover files under `src/`. |
| Copilot `--allow-all-tools --deny-tool=write` | **❌ BYPASSED — file was created via a shell command.** |

**Consequence:** GitHub's "deny beats allow" applies to the *write tool*, **not** to writes performed *through* the shell tool. The adapter must therefore use an **explicit allowlist that excludes shell** (`--allow-tool='read'`), with `--deny-tool=write` only as defense-in-depth. Never `--allow-all-tools` for audit workers.

**Also observed:** the two agents differ in granularity (5 vs 8 findings on the same file — Claude split finer, e.g. constant-time compare, rate limiting). Not a defect, but cross-agent finding counts won't match, so the dedup key and severity normalization carry real weight.

## 7. Dual distribution & compatibility

- **Claude:** keep the marketplace plugin *and* support `freya install --agent claude`. Both use the same `freya`-based SKILL.md (Decision 1); the plugin path additionally bootstraps `freya` onto PATH.
- **Everyone else:** `freya install --agent <x>`.
- **Migration:** existing Claude users keep working after a one-time `freya`-on-PATH step; `.claude-plugin/` and all scripts are untouched.

> **Correction (2026-08-18, after implementation).** Two of these three need amending.
>
> - *"the plugin path additionally bootstraps `freya` onto PATH"* — there is no bootstrap
>   and none is needed: Claude Code already puts the plugin's own `bin/` on `PATH`. Full
>   reasoning and the empirical check under Decision 1.
> - *"existing Claude users keep working after a one-time `freya`-on-PATH step"* — they do
>   **not** keep working, but for an unrelated reason this line did not anticipate. Every
>   skill was renamed (Decision 3's correction), so `/freya-devkit:wrap-up` and its nine
>   siblings stop resolving on `/plugin update`. That is a breaking change, and it is what
>   the 0.2.0 version bump and
>   [`../../migrations/skill-rename.md`](../../migrations/skill-rename.md) exist to
>   signal. `.claude-plugin/` is no longer untouched either — `plugin.json`'s `version`
>   moved, which is the only signal a marketplace consumer gets.

## 8. Updates (from §4.4 of the vision)

`freya update` re-fetches the canonical store to latest and re-links (symlinks auto-propagate; copy mode re-copies). A throttled (~daily) **notify-only** check on any `freya` call prints "update available — run `freya update`". No auto-apply.

## 9. Validation (definition of done for the MVP)

On both **Copilot (VS Code)** and **Claude Code**, from a clean install:
- `freya doctor` passes; `freya code-graph build` / `impact` works.
- Skills are discoverable under their prefixed names and resolve to the canonical store.
- `spec scan` runs its discovery flow (parallel where supported; sequential when forced).
- `wrap-up` runs end-to-end incl. Phase 3.5 (`behavior-graph --check`) and the governance gates.

  > **Correction (2026-08-18, after validation): this criterion is only *partly* met, and
  > the second half of it has never been exercised on a non-Claude agent.** The one live
  > `wrap-up` run is `phase-7-validation-log.md:144-167` (Copilot). What it demonstrates
  > is real and is the bulk of the flow: no code commit when `src/` is unchanged, a real
  > dependency graph, one artifact commit of five files, a findings-derived `BACKLOG.md`,
  > source untouched, clean tree. What it does **not** touch is Phase 3.5 —
  > `behavior-graph --check`, the declared-intent gate (G1), the principle checkpoint
  > (G2), the contradiction check (G3) and the declarative-drift check (P4b) — none of
  > which the log mentions. That is a property of the fixture, not a failure: it had no
  > specs, no principles, no ADRs and no behaviors, and `wrap-up`'s own prose says the
  > gate skips with no `.intent-last-verified` baseline (the run *created* that baseline
  > as one of its five artifacts). So the gates did not fail; they had nothing to run on.
  >
  > These are the parts of `wrap-up` that are pure model judgment rather than script
  > output, which makes them exactly the parts most likely to behave differently on a
  > different host — and they remain unproven off Claude. Closing this needs one run
  > against a fixture carrying at least one accepted behavior, one principle, one ADR and
  > an existing `.intent-last-verified`. Until then, treat the criterion as **met for the
  > deterministic spine, unproven for the governance gates.**
- `codebase-security-scan scan`/`update` fan-out runs (parallel + sequential-fallback).
- `freya security audit` runs on **both** agents via the headless adapter: schema-validated findings, loop-until-dry terminates, majority voting matches the current engine's dispositions, and no worker writes a file. With no agent CLI available it degrades with a clear message.
- `freya update` refreshes without reinstalling.

## 10. Risks / open implementation details

- **Windows:** symlink privilege, `PATH`, and a `.ps1` installer — copy fallback + PowerShell path are the mitigation; needs a real test.
- **`freya` on PATH for existing Claude-plugin users** (Decision 1's cost) — needs the first-run bootstrap.
  > **Correction (2026-08-18): closed, and it was never open.** Claude Code adds
  > `<plugin-cache>/<plugin>/<version>/bin` to `PATH` itself — see Decision 1's
  > correction for the empirical check. The residual risk is not "no bootstrap" but "an
  > undocumented, untested host behaviour we now depend on", plus Windows, where an
  > extensionless `bin/freya` is not runnable through `PATHEXT` and the `.cmd` shim comes
  > from the installer rather than the store. What *did* break existing plugin users is
  > the skill rename, which this risk list never contemplated.
- **Copilot subagent specifics** (preview/version-gating) — instruction-based orchestration is the safe baseline.
- **The 172-site slash rewrite** — script it, but review by hand; wording differs (`/freya-devkit:status` as a *command* vs as a *skill reference*).
- **Command-manifest naming** — the friendly names in §3 are a starting point; finalize in the plan.
- **Canonical store: managed clone vs shallow snapshot** — drives `freya update` internals.
- ~~Audit driver assumptions unverified~~ — **resolved by the spike (§6.1.1).** Residual: Copilot exposes no cost/usage telemetry, so budget guards must be driven by call counts there rather than spend.
- **💰 Audit cost is the real risk.** One finder worker measured **$0.396** on a *trivial* fixture. The engine's budget is 6 categories × up to `MAX_ROUNDS` 5 rounds, plus 3 skeptics per finding — plausibly ~90 agent calls on a real repo, i.e. **tens of dollars per audit**, and higher on large codebases. Mitigations to design in: a cheaper `--model` for finders, hard caps on rounds/findings, an upfront cost estimate with confirmation, and reusing the existing `K_EMPTY`/`MAX_ROUNDS` guards. Audit is on-demand/pre-release, not part of `wrap-up`, which bounds the blast radius.
- **Headless worker latency** — each worker is a fresh session (~26–62 s each in the spike); wall-clock depends on the concurrency cap.
- **Prompt-contract drift across agents** — differing granularity (5 vs 8 findings for the same file) means the dedup key and severity normalization need care.

## 11. Rough phases (each → its own implementation plan)

1. **`freya` launcher** — self-location, interpreter resolution, command manifest, dispatch, `doctor`. (Unit-testable in isolation.)
2. **SKILL.md de-Claude-ify** — invocation (83), slash refs (172+33), frontmatter, tool names; keep Claude working.
3. **Installer** — `install.sh` (+`.ps1`): canonical store, PATH, per-agent link/copy with `freya-*` prefixing.
4. **Portable orchestration** — rewrite the three fan-out flows.
4b. **Audit driver** — spike the headless adapter (install/verify Copilot CLI), then port `codebase-security-audit.js` → Python driver + adapter; retire the JS workflow.
5. **`freya update`** + notify-only check + `freya init` (per-project `AGENTS.md`).
6. **Validate on Copilot + Claude** (§9).

## Sources
Carried from [`00-vision.md`](00-vision.md) §Sources.
