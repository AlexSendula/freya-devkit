# Phase 6 Validation Plan — proving the port on a real machine

> **For agentic workers:** this is a *validation* plan, not an implementation plan. Nothing here is written test-first, because the artefact under test already exists and the question is whether it behaves on a real machine. Steps use checkbox (`- [ ]`) syntax for tracking. Record what actually happened, including partial or surprising results — a validation plan that only records successes has validated nothing.

**Goal:** Convert the five unproven claims the track rests on into evidence, or record precisely why each still cannot be proven.

**Approach:** Two parts, gated separately. **Part A** runs the whole install/update/init/doctor surface under a redirected `HOME`, on this Mac, at zero cost and with no effect on the user's working setup. **Part B** is the live-agent slice — it needs credentials inside the sandbox and spends real money, so it starts only after Part A passes and the user says go.

**Tech stack:** the shipped `install.sh` / `freya` CLI, real `git` against the real GitHub remote, Claude Code 2.1.220 and GitHub Copilot CLI 1.0.75 (both already on this machine).

## Context

Phases 1–5 are built and reviewed; nothing in the track has been executed against a live Copilot session, and `freya update` has never reached a real remote. The branch was pushed on 2026-08-14, so for the first time it *has* an upstream and `update` is testable end to end.

### The isolation mechanism, and its limits

Every path the toolkit writes is derived from `Path.home()` — verified at all six call sites: `~/.claude/skills`, `~/.agents/skills`, `~/.local/bin/freya`, `~/.freya`, plus the marketplace probe `doctor` reads. `Path.home()` honours `$HOME`, and so does Node's `os.homedir()` (checked empirically, which matters because both agent CLIs are Node programs).

**This is isolation by convention, verified by inspection — not an enforced boundary.** A program that called `getpwuid()` instead of reading `$HOME` would still find the real home. None of the toolkit's write paths do. The residual risk is therefore operator error — running one command without the prefix — which Task A0 and Task A8 exist to catch rather than assume away.

### What this phase cannot do

Windows. `install.ps1`, symlink privilege, and `--copy` under Windows stay unexercised, and no amount of sandboxing on a Mac changes that. Say so in the closeout rather than letting the phase imply otherwise.

## Global Constraints

- **Every command that touches the toolkit carries the sandbox prefix.** No exceptions, including "just checking something". The literal form used throughout:
  `HOME="$SANDBOX" …`
- **`SANDBOX=/tmp/freya-phase6/home`** and **`STORE=/tmp/freya-phase6/store`**. `/tmp` on macOS is a symlink to `/private/tmp`, which is a feature here: it exercises the exact path-resolution class that already caused a real bug in `uninstall_agent`.
- **Never run `install.sh`, `freya install`, `freya update` or `freya init` without the prefix.** The real `~/.claude/skills` currently holds the user's other skills (cmux-browser, the gsd-* family, and more) and must end this phase byte-identical.
- **Record the actual output**, not a paraphrase. A validation plan's value is its transcript.
- **Nothing is merged.** The branch is pushed; that is the only remote action authorised. No PR, no merge, no tag, no marketplace publish.
- **Part B does not start without explicit approval** — it spends money and requires signing in inside the sandbox.
- Commit messages end with:
  `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`

---

## Part A — mechanics, sandboxed, free

### Task A0: Baseline the real home, and build the escape detector

**Produces:** `/tmp/freya-phase6/baseline.txt`, re-generated identically in Task A8.

- [ ] **Step 1: Record the four real paths exactly as they stand**

```bash
mkdir -p /tmp/freya-phase6
{ echo "=== ~/.claude/skills ==="; ls -la ~/.claude/skills 2>/dev/null;
  echo "=== ~/.agents/skills ==="; ls -la ~/.agents/skills 2>/dev/null;
  echo "=== ~/.local/bin ==="; ls -la ~/.local/bin 2>/dev/null;
  echo "=== ~/.freya ==="; ls -la ~/.freya 2>/dev/null || echo "(absent)"; } > /tmp/freya-phase6/baseline.txt
wc -l /tmp/freya-phase6/baseline.txt
```
Expected: a non-empty file. `~/.freya` should read `(absent)`.

- [ ] **Step 2: Confirm no freya-* entry exists in the real home yet**

```bash
ls ~/.claude/skills ~/.agents/skills 2>/dev/null | grep -c '^freya-' || echo 0
```
Expected: `0`. If it is not 0, stop — something from an earlier session is installed and the baseline is not clean.

---

### Task A1: Clean install from a fresh clone — the README path

This is the path the README actually tells a user to take, so it is the one that must work.

- [ ] **Step 1: Create the sandbox and clone from the real remote**

```bash
export SANDBOX=/tmp/freya-phase6/home STORE=/tmp/freya-phase6/store
mkdir -p "$SANDBOX"
git clone --branch feat/polyglot-portability https://github.com/AlexSendula/freya-devkit.git "$STORE"
```
Expected: a clone with 97+ commits. Record `git -C "$STORE" log --oneline -1`.

- [ ] **Step 2: Install for both agents**

```bash
HOME="$SANDBOX" "$STORE/install.sh" --agent claude --agent copilot
```
Expected: `linked` for ten skills per agent, then `launcher: linked <sandbox>/.local/bin/freya`, and a note that the directory is not on PATH. Record the full output.

- [ ] **Step 3: Verify the shape of what was created**

```bash
ls -la "$SANDBOX/.claude/skills" | head -12
ls -la "$SANDBOX/.agents/skills" | head -12
readlink "$SANDBOX/.claude/skills/freya-code-graph"
```
Expected: ten `freya-*` symlinks per agent, each pointing into `$STORE/skills/`.

- [ ] **Step 4: `doctor` on the sandboxed install**

```bash
HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya doctor; echo "exit=$?"
```
Expected: exit 0. `agents` names both with a mode (`claude (10, symlink), copilot (10, symlink)`), `orphaned entries: none`, `duplicate install: none` — the last one because the marketplace plugin lives in the *real* home, which this probe can no longer see.

- [ ] **Step 5: A real command end to end**

```bash
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya code-graph --help
```
Expected: the script runs through the launcher. This proves `sys.executable` dispatch works with no `python` on PATH assumptions.

---

### Task A2: Idempotency, and what `doctor` says about a `--copy` install

- [ ] **Step 1: Re-run the install unchanged**

```bash
HOME="$SANDBOX" "$STORE/install.sh" --agent claude --agent copilot; echo "exit=$?"
```
Expected: exit 0, every line `skipped`. A second install must be a no-op.

- [ ] **Step 2: A `--copy` install into a third target**

```bash
HOME="$SANDBOX" python3 "$STORE/bin/installer.py" --agent copilot --copy --force
ls -la "$SANDBOX/.agents/skills/freya-status" | head -3
cat "$SANDBOX/.agents/skills/freya-status/.freya-install"
```
Expected: real directories, each carrying a marker naming `$STORE/skills/<name>`. This is the Windows install mode, exercised as far as macOS allows.

- [ ] **Step 3: `doctor` distinguishes the modes**

```bash
HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya doctor
```
Expected: `copilot (10, copy)` alongside `claude (10, symlink)`. Phase 5 added this wording specifically; confirm it is true in the field.

---

### Task A3: `freya update` against the real remote — the claim that has never been tested

**This is the centre of the phase.** Every refusal is unit-tested; the success path against a live remote has only ever run against fixtures.

- [ ] **Step 1: Rewind the store five commits**

```bash
git -C "$STORE" reset --hard HEAD~5
git -C "$STORE" log --oneline -1
git -C "$STORE" status -sb | head -2
```
Expected: `## feat/polyglot-portability...origin/feat/polyglot-portability [behind 5]`.

- [ ] **Step 2: Update**

```bash
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya update; echo "exit=$?"
```
Expected: exit 0, `updated <old8> -> <new8> (5 commit(s))`, followed by re-link output. Record it verbatim — this line has never been produced against a real remote.

- [ ] **Step 3: Already current**

```bash
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya update; echo "exit=$?"
```
Expected: exit 0, `already up to date`.

- [ ] **Step 4: Each refusal, in the field**

```bash
# dirty tree
echo "scratch" >> "$STORE/README.md"
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya update; echo "exit=$?"
git -C "$STORE" checkout -- README.md

# no upstream
git -C "$STORE" checkout -b local-only
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya update; echo "exit=$?"
git -C "$STORE" checkout feat/polyglot-portability

# not a git checkout
mkdir -p /tmp/freya-phase6/notgit && cd /tmp/freya-phase6/notgit
HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya update; echo "exit=$?"
```
Expected: exit 2 each time, with the specific message — uncommitted changes / no upstream + the `--set-upstream-to` hint / not a git checkout. Note that the third runs against the *store the launcher resolves to*, not the current directory; record what it actually says, since that distinction has never been observed live.

- [ ] **Step 5: The offline path**

Disable networking (Wi-Fi off is sufficient), then:

```bash
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya update; echo "exit=$?"
```
Expected: exit 2 and `could not fetch`, **not** `already up to date`. This is the failure the pre-implementation review predicted and a mutation reproduced; observing it live closes the loop. Time it — the fetch bound is 60 s, and how long a real failure actually takes is unknown.

Re-enable networking before continuing.

- [ ] **Step 6: A missing link is restored**

```bash
rm "$SANDBOX/.claude/skills/freya-status"
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya update
ls -la "$SANDBOX/.claude/skills/freya-status"
```
Expected: `claude: linked freya-status` and the link exists again. This simulates a skill added upstream — the trigger is manufactured, the code path is the real one. Say so in the record.

---

### Task A4: The notify check, observed rather than mocked

- [ ] **Step 1: Make the store stale and clear the throttle**

```bash
rm -f "$SANDBOX/.freya/update-check.json"
git -C "$STORE" reset --hard HEAD~2
```

- [ ] **Step 2: Run an ordinary command and watch stderr**

```bash
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya code-graph --help 2>/tmp/freya-phase6/notice.txt >/dev/null
cat /tmp/freya-phase6/notice.txt
cat "$SANDBOX/.freya/update-check.json"
```
Expected: the notice on **stderr only**, and a state file recording `behind: true`. Time this invocation — it is the one that pays for `ls-remote`.

- [ ] **Step 3: The throttle holds**

```bash
cd "$STORE" && time HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya code-graph --help >/dev/null
```
Expected: the notice again, but instantly — served from cache with no network call.

- [ ] **Step 4: The opt-out, and the commands that skip it**

```bash
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" FREYA_NO_UPDATE_CHECK=1 freya code-graph --help 2>&1 >/dev/null | head -2
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya help 2>&1 >/dev/null | head -2
```
Expected: silence from both.

- [ ] **Step 5: An update clears the notice**

```bash
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya update >/dev/null
cat "$SANDBOX/.freya/update-check.json"
cd "$STORE" && HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya code-graph --help 2>&1 >/dev/null | head -2
```
Expected: `behind: false`, and no notice on the next command.

---

### Task A5: Move the checkout — the failure `doctor` was taught to see

- [ ] **Step 1: Relocate the store**

```bash
mv "$STORE" /tmp/freya-phase6/store-moved
HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" python3 /tmp/freya-phase6/store-moved/bin/freya_cli.py doctor; echo "exit=$?"
```
Expected: `orphaned entries: warn` naming an entry and the path it points at, with the remedy. This is the phase-3 gap phase 5 closed; it has never been seen outside a temp-dir test.

- [ ] **Step 2: Repair**

```bash
HOME="$SANDBOX" /tmp/freya-phase6/store-moved/install.sh --agent claude --agent copilot --force
HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" python3 /tmp/freya-phase6/store-moved/bin/freya_cli.py doctor; echo "exit=$?"
mv /tmp/freya-phase6/store-moved "$STORE"
```
Expected: `--force` replaces the stale links; `doctor` returns to `orphaned entries: none`. Then restore the path for later tasks and re-run the install once more so the links point back at `$STORE`.

---

### Task A6: `freya init` on a real project

- [ ] **Step 1: A fresh project**

```bash
mkdir -p /tmp/freya-phase6/project && cd /tmp/freya-phase6/project
HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya init
cat AGENTS.md
```
Expected: the managed block with **ten rows, each carrying a readable one-line summary** — no empty cells, no bare `|`.

- [ ] **Step 2: Idempotency, for real**

```bash
cd /tmp/freya-phase6/project && cp AGENTS.md /tmp/freya-phase6/agents-before.md
HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya init
diff /tmp/freya-phase6/agents-before.md AGENTS.md && echo "byte-identical"
```
Expected: `already up to date` and an empty diff.

- [ ] **Step 3: Someone else's file survives**

```bash
cd /tmp/freya-phase6/project
printf '# My project\r\n\r\nNotes about freya-devkit:begin in prose.\r\n' > AGENTS.md
HOME="$SANDBOX" PATH="$SANDBOX/.local/bin:$PATH" freya init
file AGENTS.md; head -4 AGENTS.md
```
Expected: the prose survives, the block is appended, and `file` still reports CRLF line terminators. Both properties were fixed late in phase 5 and neither has been seen outside a test.

---

### Task A7: Uninstall leaves nothing of ours behind

- [ ] **Step 1: Plant something that is not ours**

```bash
mkdir -p "$SANDBOX/.claude/skills/freya-not-ours"
echo "someone else's" > "$SANDBOX/.claude/skills/freya-not-ours/SKILL.md"
```

- [ ] **Step 2: Uninstall**

```bash
HOME="$SANDBOX" python3 "$STORE/bin/installer.py" --agent claude --agent copilot --uninstall
ls "$SANDBOX/.claude/skills" "$SANDBOX/.agents/skills"
ls "$SANDBOX/.local/bin" 2>/dev/null
```
Expected: every `freya-*` entry we created is gone, the launcher is gone, and `freya-not-ours` **is still there** — the installer removes only what it created.

---

### Task A8: The escape audit

- [ ] **Step 1: Re-baseline and diff**

```bash
{ echo "=== ~/.claude/skills ==="; ls -la ~/.claude/skills 2>/dev/null;
  echo "=== ~/.agents/skills ==="; ls -la ~/.agents/skills 2>/dev/null;
  echo "=== ~/.local/bin ==="; ls -la ~/.local/bin 2>/dev/null;
  echo "=== ~/.freya ==="; ls -la ~/.freya 2>/dev/null || echo "(absent)"; } > /tmp/freya-phase6/after.txt
diff /tmp/freya-phase6/baseline.txt /tmp/freya-phase6/after.txt && echo "REAL HOME UNCHANGED"
```
Expected: **no differences.** If there are any, stop and report before doing anything else — that is an isolation failure and it matters more than any result in this phase.

- [ ] **Step 2: Record Part A**

Write the transcript to `docs/design/portability/phase-6-validation-log.md` — every command's actual output, each expectation met or missed, and anything surprising. Commit it:

```bash
git add docs/design/portability/phase-6-validation-log.md
git commit -F - <<'EOF'
docs(validation): part A — the mechanics, observed on a real machine

<one paragraph on what held and what did not>

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Part B — the live-agent slice (gated: needs approval, credentials, and money)

> Do not start Part B until Part A is complete, its diff is clean, and the user has said go. Every task here requires signing into an agent CLI **inside the sandbox home**, which is a fresh, empty profile. The user's real sessions keep their own credentials and are unaffected.

### Task B1: Skills resolve on Claude Code

- [ ] Start Claude Code with `HOME="$SANDBOX"`, sign in, and confirm the ten skills appear under their **prefixed, un-namespaced** names (`freya-code-graph`, not `/freya-devkit:freya-code-graph`) — the marketplace plugin is invisible from this home, so any namespaced name would mean something unexpected.
- [ ] Invoke one deterministic skill end to end (`freya-status`) and record the output.

### Task B2: Does a re-linked skill get picked up without a restart?

**The question that decides whether `freya update` is useful or merely correct.**

- [ ] With a Claude session running, remove one skill link, run `freya update` to restore it, and ask the same session to use that skill.
- [ ] Record which it is: picked up live, picked up after a new session, or not until a full restart.
- [ ] Repeat on Copilot. If either caches per session, that is a finding for the docs, not a defect — but it must be written down.

### Task B3: Copilot discovery and fan-out

- [ ] Confirm Copilot reads `~/.agents/skills` from the sandbox home and lists the suite.
- [ ] Run one fan-out skill (`freya-docs-manager update` on a small fixture) and record **whether Copilot actually delegates in parallel or narrates the tasks sequentially**. The design assumed the documented lever works; nobody has watched it.

### Task B4: `freya security audit` on both adapters — the money step

- [ ] Create a tiny fixture repo (a handful of files with one obvious issue).
- [ ] Run with hard caps on Claude: `freya security audit --project <fixture> --agent claude --max-findings 3 --dry-run` first, confirm the printed estimate, then without `--dry-run`.
- [ ] Repeat with `--agent copilot`.
- [ ] Record: does a live worker return schema-valid findings; does loop-until-dry terminate; does majority voting produce sane dispositions; **does any worker write a file** (it must not).
- [ ] Re-run the read-only bypass probe against Copilot CLI 1.0.75 — the same version the guard was proven against, so this confirms rather than re-derives.

**Cost control:** one worker measured ~$0.40 on a trivial fixture. With `--max-findings 3` the ceiling is small, but stop and report if the estimate exceeds what was agreed before running.

### Task B5: `wrap-up` end to end

- [ ] Run `freya-wrap-up` on the fixture repo under each agent, including the phase 3.5 behavior-graph check and the governance gates.
- [ ] Record where it stops if it stops.

---

## Definition of done

- The real `~/.claude/skills`, `~/.agents/skills`, `~/.local/bin` and `~/.freya` are byte-identical to the Task A0 baseline.
- A clean `git clone && ./install.sh` installs both agents; a second run is a no-op; `doctor` exits 0 and names the mode per agent.
- `freya update` fast-forwards from the real GitHub remote, reports the commit count, re-links, and says `already up to date` on the second run.
- Every refusal (dirty, no upstream, not a checkout, offline) is observed live with its own message and exit 2 — and the offline case says `could not fetch`, never `already up to date`.
- The notify check is seen on stderr, exactly once per day, silenced by the opt-out, and cleared by an update.
- A moved checkout produces `doctor`'s orphan warning, and `--force` repairs it.
- `freya init` writes ten readable rows, is byte-identical on a second run, and preserves a CRLF file with a marker mentioned in prose.
- Uninstall removes only what the installer created.
- Part B, if run: recorded verdicts on skill pickup, Copilot parallelism, schema-valid live findings on both adapters, and the read-only probe.

## Closeout — not optional

- [ ] **Update the explainer.** `docs/explanations/portability-explainer/`: the status page's scoreboard and its "what has never been proven" section (several cards should finally be retired or sharpened), `index.html` counts, and a `phase6.html` page in the same shape as `phase5.html`. This is a standing requirement for every phase, not an afterthought — it is in this plan because phase 5's plan omitted it and the omission had to be caught by hand.
- [ ] **Record what is still unproven** — Windows above all — as its own section rather than a footnote.
- [ ] Update `README.md` if anything observed contradicts what it currently promises.
- [ ] Two commits: the validation log and the explainer, separately.

## Carried forward regardless of outcome

- `install.ps1`, `--copy` on Windows, and symlink privilege — no macOS run can touch these.
- The 60 s fetch timeout, unless the offline test in A3 happens to sit through it.
- `freya_cli.main`'s catch-all reporting unrelated failures as "cannot read the command manifest".
- The marketplace release: `.claude-plugin/plugin.json` still reads `0.1.0`, and the published plugin predates the entire track.
