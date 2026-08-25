#!/usr/bin/env python3
"""Guard the shipped skill layer against agent-specific constructs.

Phase 2 of the portability track removed ${CLAUDE_PLUGIN_ROOT} invocations,
/freya-devkit: slash references, /loop slash-command mentions, and "plan mode"
prose from skills/**/*.md (and, for the substring checks, skills/**/*.py).
This checker is what keeps them out: it is a regression gate, not a one-off
migration script. R14 rides along: same shape, but a secrets rule, not portability.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

#: Launcher subcommands that are not in the command manifest.
BUILTIN_COMMANDS = frozenset({"install", "update", "doctor", "init", "help"})

#: The Agent Skills specification (https://agentskills.io/specification) defines
#: exactly these frontmatter keys. `name` and `description` are required; the rest
#: are optional. Anything else is a client-specific extension and hurts portability.
ALLOWED_FRONTMATTER = frozenset(
    {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
)

RULES = {
    "R1": "${CLAUDE_PLUGIN_ROOT} is Claude-only — use a `freya <command>` invocation",
    "R2": "/freya-devkit: is Claude-only — use the prefixed skill name freya-<skill>",
    "R3": "unknown freya command — add it to bin/commands.json or fix the name",
    "R4": "agent-specific tool name — use agent-neutral phrasing",
    "R5": "frontmatter key outside the Agent Skills spec (name, description, license, "
          "compatibility, metadata, allowed-tools)",
    "R6": "/loop is a Claude Code slash command — describe the schedule instead",
    "R7": "'plan mode' names a Claude-specific mode — describe presenting a plan for approval",
    "R8": "SKILL.md `name` must equal the parent directory name (Agent Skills spec)",
    "R9": "fan-out without a portability clause — say what to do when the agent "
          "has no subagents (include the phrase \"if your agent supports subagents\" "
          "*and* a sequential fallback, e.g. \"one at a time\")",
    "R10": f"frontmatter value over the Agent Skills length limit — a host that "
           f"enforces it drops the skill silently",
    "R11": "SKILL.md must declare a non-empty `description` (required by the "
           "Agent Skills spec — a host with nothing to match on never loads the skill)",
    "R12": "SKILL.md `name` is outside the Agent Skills grammar — lowercase "
           "letters, digits and single hyphens only",
    "R13": "Claude-only location — `~/.claude`, `.claude/`, `.claude-plugin` and "
           "CLAUDE_* env vars do not exist under another agent",
    "R14": "a skill that sends a worker at secret-bearing material must state the "
           "redaction rule — \"never write a real secret value\" *and* the placeholder to "
           "write instead ([REDACTED], <redacted ...>) — and restate it in a copied-source slot",
}

#: Length limits from the Agent Skills specification. These are not advisory:
#: phase 6 validation found GitHub Copilot silently omitting a skill whose
#: description ran to 1251 characters, while Claude Code loaded it happily. The
#: skill was installed, linked and invisible — no error anywhere. R5 checks which
#: keys are present and never looked at how long their values were.
FRONTMATTER_LIMITS = {"description": 1024, "compatibility": 500, "name": 64}

#: Matches both the braced form (`${CLAUDE_PLUGIN_ROOT}`) and the bare form
#: (`$CLAUDE_PLUGIN_ROOT`, no braces) — both are Claude-only. Alternation order
#: matters: the braced form is tried first so it is consumed as one match
#: instead of the bare-form alternative matching just its prefix.
PLUGIN_ROOT = re.compile(r"\$\{CLAUDE_PLUGIN_ROOT\}|\$CLAUDE_PLUGIN_ROOT\b")
SLASH_REF = "/freya-devkit:"
#: A `/loop`-style slash command. The lookbehind excludes a preceding word
#: character or `/` so this doesn't fire inside a path segment (e.g.
#: `workflows/loop.js`) or a URL (`http://loop.example.com`); the trailing
#: `\b` excludes a longer token like a hypothetical `/loops`.
LOOP_SLASH = re.compile(r"(?<![\w/])/loop\b")
#: The Claude-specific mode named in prose, case-insensitive. The `EnterPlanMode`
#: *token* (no space) is a distinct construct already caught by R4 — this rule
#: is for the prose form only.
PLAN_MODE_PROSE = re.compile(r"\bplan mode\b", re.IGNORECASE)
FRONTMATTER_KEY = re.compile(r"([A-Za-z_][A-Za-z0-9_-]*):")

#: Tool names that exist under one agent only.
#:
#: Three shapes, because the names split three ways. Compound identifiers have
#: no plain-English reading, so a bare token is enough. The single-word names
#: are the commonest verbs in English, so they need context — either a ` tool`
#: suffix or an instruction verb in front. `read the file` must stay legal
#: prose; `Use Read` must not.
CLAUDE_ONLY_TOKENS = (
    r"askUserQuestion|AskUserQuestion|EnterPlanMode|ExitPlanMode|TodoWrite"
    r"|WebSearch|WebFetch|MultiEdit|NotebookEdit|SlashCommand|BashOutput"
    r"|KillShell|subagent_type"
)
#: Names that are also ordinary English words: only flagged with context.
AMBIGUOUS_TOOLS = r"Read|Write|Edit|Glob|Grep|Bash|Task|Agent|Skill|Workflow"
#: Verbs that turn a capitalised tool name into an instruction. `Bash`, `Agent`,
#: `Skill` and `Workflow` are deliberately excluded from this form: "run Bash",
#: "with Agent Skills" and "the Skill directory" are all portable English.
INSTRUCTED_TOOLS = r"Read|Write|Edit|Glob|Grep|Task"
#: Markdown emphasis a name may be wrapped in: `Read`, **Task**, *Grep*. The old
#: pattern required the name bare and the following space literal, so backticking
#: it — the default way to write a tool name in markdown — evaded R4 outright.
MARKUP = r"[`*_]*"

AGENT_TOOL_NAMES = re.compile(
    rf"\b(?:{CLAUDE_ONLY_TOKENS})\b"
    rf"|{MARKUP}\b(?:{AMBIGUOUS_TOOLS})\b{MARKUP}\s+tools?\b"
    rf"|\b(?:[Uu]se|[Uu]sing|[Ii]nvoke|[Cc]all|[Vv]ia|[Pp]refer)\s+(?:the\s+)?"
    rf"{MARKUP}\b(?:{INSTRUCTED_TOOLS})\b{MARKUP}"
    # The retired audit engine was referred to as "Workflow-powered" as often as
    # "Workflow tool", and the ` tool` alternation above missed every one of them.
    # Case-sensitive on the capital W so ordinary prose ("wrap-up workflow") is fine.
    r"|\bWorkflow[- ](?:tool|powered|engine|script|runtime|file)\b"
)

#: Markdown-only additions. Capitalised, `Glob` and `Grep` are only ever Claude's
#: tools — the shell utilities are lowercase — so in prose they need no context
#: at all ("Scans codebase structure (Glob for key patterns)" shipped clean).
#: They are markdown-only because a per-agent adapter has to name that agent's
#: own tools in an argv: audit_adapter.py's `--allowedTools "Read Grep Glob"` is
#: data handed to the `claude` binary, not an instruction to a model, and that
#: is the one place a Claude tool name is correct by construction.
AGENT_TOOL_NAMES_PROSE = re.compile(
    AGENT_TOOL_NAMES.pattern + rf"|{MARKUP}\b(?:Glob|Grep)\b{MARKUP}"
)

#: Claude-only filesystem locations and environment variables. No rule looked at
#: paths at all, which is how a review fixture ending "Reports land in
#: ~/.claude/skills/." scanned clean: R1 covers `${CLAUDE_PLUGIN_ROOT}` and
#: nothing covered the rest. `CLAUDE_PLUGIN_ROOT` is excluded by lookahead so a
#: single `${CLAUDE_PLUGIN_ROOT}` reports once, as R1, rather than twice.
#: `.claude-plugin/` is this repo's own manifest directory — real, and still not
#: something anything under skills/ may point an agent at.
#:
#: `CLAUDE.md` is deliberately *not* here. It is a file in the user's own
#: project, not a Claude-only construct the skill layer depends on, and both
#: places skills/ names it (docs-manager's root-doc detection, and its DEVELOPER
#: worker's context list) are reading whatever the project happens to have next
#: to README.md and AGENTS.md. Flagging it would make the suite worse on the
#: projects it already works on.
CLAUDE_ONLY_PATHS = re.compile(
    r"~/\.claude\b|\.claude-plugin\b|(?<![\w.])\.claude[/\\\"']"
    r"|\bCLAUDE_(?!PLUGIN_ROOT\b)[A-Z][A-Z_]*\b"
)

#: A CLI invocation is `freya` + whitespace + a command word. The whitespace is
#: load-bearing: `freya-code-graph` is a skill name, not a command, and must not match.
FREYA_COMMAND = re.compile(r"\bfreya[ \t]+([a-z][a-z0-9-]*)")

INLINE_CODE = re.compile(r"`([^`]+)`")

#: A fan-out instruction: telling the agent to run N workers, or advertising that
#: the skill does. Wide enough to catch an indefinite/each/per article between
#: the verb and the noun (`spawn a worker`, `launch each scanner`, `create 12
#: subagents`), `concurrently`/`simultaneously`, the `parallelized`/`parallelised`/
#: `parallel processing`/`parallel validation`/`parallel pass` family, and
#: `delegate ... to a/an/each/every/the (sub)?agent`. It still must not match
#: `re-inference fan-out`, a `dispatch key`, or the literal `spawn\(` regex the
#: security scanner documents as a detection pattern — those stay unmatched
#: because the verb clause requires whitespace after the verb and a mandatory
#: trailing worker/agent/subagent/scanner/task noun, neither of which those three
#: strings supply.
FANOUT = re.compile(
    r"\b(?:spawn|launch|dispatch|create)\w*\s+"
    r"(?:(?:the|these|per|each|every)\s+)?"
    r"(?:\d+\s+|one\s+|a\s+|an\s+)?"
    r"(?:parallel\s+|specialized\s+|following\s+)*"
    r"(?:worker|discovery|coordinator|security|area)?\s*"
    r"(?:agent|subagent|worker|scanner|task)s?\b"
    r"|\bin parallel\b"
    r"|\bparallel\s+(?:sub)?agents?\b|\bparallel\s+workers?\b"
    r"|\bparallel\s+(?:discovery|security)\b"
    r"|\bparallel\s+(?:processing|validation|pass(?:es)?)\b"
    r"|\bparallelized\b|\bparallelised\b"
    r"|\bconcurrently\b|\bsimultaneously\b"
    r"|\bdelegat\w*\b.{0,60}?\bto\s+(?:a\s+|an\s+|each\s+|every\s+|the\s+)?(?:sub)?agents?\b",
    re.IGNORECASE,
)

#: The exact phrase that makes a fan-out portable. Skills must state the fallback
#: for agents without subagents; an unconditional "run these in parallel" has no
#: defined meaning there.
SUBAGENT_SENTINEL = "if your agent supports subagents"

#: ...and the fallback itself has to be spelled out. The sentinel alone says
#: *when* to fan out and never says what to do instead, which is how phase 7's
#: update-mode fan-outs shipped carrying no scheduling guidance at all: one
#: sentinel anywhere in the file satisfied every fan-out in it.
SEQUENTIAL_FALLBACK = ("one at a time", "one by one", "sequentially", "in sequence")

#: The Agent Skills grammar for `name`: lowercase letters, digits and single
#: hyphens. R8 only ever compared the name to its directory, so a directory and
#: a name that agreed on `Freya_Demo--X` passed both.
NAME_GRAMMAR = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: Material a worker can only have got by reading somebody's real secrets.
#:
#: Two skills send a worker at it and then have that worker write a git-tracked
#: document about what it saw. The security scan's report template took an
#: unconstrained `{code snippet}`, and for a Secrets-category finding the
#: vulnerable code *is* the credential. The docs-manager ENVIRONMENT worker was
#: asked for a "complete environment variable reference" built from
#: `.env.example`, configuration files and the project's secrets-management
#: approach, and nothing in the file forbade transcribing a value. `freya-wrap-up`
#: commits both outputs, so a key that lived only in a gitignored file becomes a
#: blob that outlives rotating the key.
#:
#: Deliberately not a secret *detector*: it matches the prose that describes
#: reading secrets, not the secrets. `\btokens?\b` and `\bpasswords?\b` are
#: excluded for the usual reason — "7× the tokens of a sequential pass",
#: "token validation", "No Password Fallback" are all ordinary sentences in
#: three other skills, and a rule that fires on them is a rule someone turns off.
SECRET_MATERIAL = re.compile(
    r"\.env\b"
    r"|\bhardcoded\s+(?:secret|credential|api[- ]?key|password|token)"
    r"|\bexposed\s+secrets?\b"
    r"|\bapi[- ]keys?\b|\bprivate\s+keys?\b"
    r"|\bsecrets?\s*(?:&|and)\s*sensitive\s+data\b"
    r"|\bsecrets?\s+(?:management|scanning|detection)\b"
    r"|\b(?:secret|credential|password|token)\s+values?\b",
    re.IGNORECASE,
)

#: The prohibition itself, stated where the writer will read it. A prose rule
#: cannot import a redaction helper; what binds the writer is the rule being in
#: the file the writer is handed, so this is what the gate can check.
REDACTION_SENTINEL = "never write a real secret value"

#: ...and what to write instead. Same lesson as SEQUENTIAL_FALLBACK above: a bare
#: "don't include secrets" says what not to do and leaves the writer to invent
#: the alternative, and an evidence block left empty loses the finding it was
#: evidence for. A delimiter is required so ordinary prose ("the value is
#: redacted") does not satisfy the rule — what has to appear is the token the
#: writer types. Three of them, because the two writers legitimately differ: the
#: docs template shows `[REDACTED]`, the security report a fingerprint
#: `<redacted len=44 prefix='sk-p' sha256=9f2c1ab4>`.
REDACTION_PLACEHOLDER = re.compile(r"[\[<{]redacted", re.IGNORECASE)

#: A template slot the writer fills by copying source out of the scanned project.
#:
#: This is the half of R14 that can tell a rule from an echo. Stating the rule
#: *somewhere* is satisfiable by a paragraph three sections away from the place
#: the writer is actually typing, and SEC-009 was exactly that shape: the report
#: template's evidence block took a bare `{code snippet}`, and for a Secrets
#: finding the vulnerable code *is* the credential. So the reminder has to be in
#: the slot, not merely in the file.
#:
#: Narrow on purpose, and measured. Over the ten shipped `SKILL.md` files at
#: `f61cfbd`: 33 lines are a `{...}` slot standing on a line of its own, and
#: exactly one of them names copied source — the security scan's evidence block,
#: which is the finding itself. The other 32 take no verbatim source: they
#: prompt for a description or a command, mark a template branch, or are JSON in
#: a fenced example. A rule that cries wolf gets switched off.
#:
#: `.*` rather than `[^{}]*` inside the braces, so the fixed line still matches:
#: the remediation spells the fingerprint out as `<redacted len={n} ...>`, which
#: nests braces one deep, and a slot that stops being checked the moment somebody
#: fixes it is a gate that only ever guards the past.
COPIED_SLOT = re.compile(
    r"^\s*\{.*\b(?:code|snippet|secret|credential|literal)\b.*\}\s*$",
    re.IGNORECASE,
)


def code_spans(lines):
    """Yield (lineno, text) for text an agent reads as a command.

    That is every line inside a fenced block, plus every inline `code` span
    outside one. Prose is excluded so ordinary sentences mentioning freya do
    not register as command invocations.
    """
    in_fence = False
    for lineno, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            yield lineno, line
        else:
            for span in INLINE_CODE.findall(line):
                yield lineno, span


def frontmatter_keys(lines):
    """Yield (lineno, key) for each top-level YAML frontmatter key.

    Indented lines are block-scalar content (e.g. the body of `description: |`),
    not keys, so the pattern is deliberately anchored at column zero.
    """
    if not lines or lines[0].strip() != "---":
        return
    for lineno, line in enumerate(lines[1:], 2):
        if line.strip() == "---":
            return
        match = FRONTMATTER_KEY.match(line)
        if match:
            yield lineno, match.group(1)


def frontmatter_value(lines, key):
    """Return a top-level frontmatter value, or None if the key is absent.

    Handles both forms this repo uses. `name:` is an inline scalar; every
    `description:` is a block scalar (`|` followed by indented lines), which a
    reader written only for inline values reports as the literal "|" — ten empty
    table cells, and nothing to tell you why.

    One layer of YAML quoting is stripped: some formatters add it on their own,
    and a quoted inline value must not read as a mismatch against whatever it's
    compared against (e.g. a quoted `name` against its directory).

    A block-scalar `name` resolves to its content, not the `|`/`>` marker,
    because that content is what the value means to a real YAML parser. This is
    a deliberate change from the earlier inline-only reader, which returned the
    marker itself and made R8 fire on a well-formed name.

    A *plain* (unmarked) scalar folds too: YAML continues it onto every
    following indented line. Reading only the first line was a total evasion of
    R10 — a description of 1774 characters, 750 over the spec limit, spread over
    six indented lines measured 53 and passed as "skill layer is conformant."
    That is the exact shape phase 6 watched Copilot drop in silence, so the miss
    was the whole rule.
    """
    if not lines or lines[0].strip() != "---":
        return None
    prefix = key + ":"
    for index, line in enumerate(lines[1:], 1):
        if line.strip() == "---":
            return None
        if not line.startswith(prefix):
            continue
        value = line.split(":", 1)[1].strip()
        # Only the plain markers are handled: no indentation indicator or
        # chomping variant (|2, |+, >+, ...). Nothing in this repo uses them,
        # and this is deliberately narrow rather than an oversight.
        block = value in ("|", "|-", ">", ">-")
        if not block:
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                # A quoted scalar closed on its own line cannot continue.
                return value[1:-1]
        body = [] if block else [value]
        for follow in lines[index + 1:]:
            if follow.strip() == "---":
                break
            if follow.strip() and not follow.startswith((" ", "\t")):
                break  # an unindented line ends the value: it is the next key
            body.append(follow.strip())
        # `|` keeps its line breaks; a plain scalar folds them to spaces (and
        # cannot contain a blank line, so empties drop out). Either way the
        # length R10 measures is the length a host's parser would see.
        if block:
            return "\n".join(body).strip()
        return " ".join(part for part in body if part).strip()
    return None


def frontmatter_name(lines):
    """Return the value of the top-level `name:` key, or None if absent."""
    return frontmatter_value(lines, "name")


def check_file(path, rel, allowed, markdown=True):
    """Return a list of (rel, lineno, rule_id, excerpt) violations for one file.

    R1/R2/R4/R6/R7 are substring/prose checks and run on every scanned file.
    R3 (freya command validity), R5 (frontmatter keys) and R8/R11/R12 (the
    SKILL.md frontmatter contract) are markdown-specific — a `.py` script has
    neither fenced command examples nor YAML frontmatter in the sense these
    rules check — so they're skipped when markdown=False. R4 runs everywhere but
    in its wider, prose-only form on markdown; see AGENT_TOOL_NAMES_PROSE.
    """
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    violations = []
    tool_names = AGENT_TOOL_NAMES_PROSE if markdown else AGENT_TOOL_NAMES

    for lineno, line in enumerate(lines, 1):
        for _ in PLUGIN_ROOT.finditer(line):
            violations.append((rel, lineno, "R1", line.strip()))
        for _ in range(line.count(SLASH_REF)):
            violations.append((rel, lineno, "R2", line.strip()))
        for match in tool_names.finditer(line):
            violations.append((rel, lineno, "R4", match.group(0)))
        for match in CLAUDE_ONLY_PATHS.finditer(line):
            violations.append((rel, lineno, "R13", match.group(0)))
        for match in LOOP_SLASH.finditer(line):
            violations.append((rel, lineno, "R6", match.group(0)))
        for match in PLAN_MODE_PROSE.finditer(line):
            violations.append((rel, lineno, "R7", match.group(0)))

    if not markdown:
        return violations

    for lineno, span in code_spans(lines):
        for command in FREYA_COMMAND.findall(span):
            if command not in allowed:
                violations.append((rel, lineno, "R3", f"freya {command}"))

    for lineno, key in frontmatter_keys(lines):
        if key not in ALLOWED_FRONTMATTER:
            violations.append((rel, lineno, "R5", f"{key}:"))
        limit = FRONTMATTER_LIMITS.get(key)
        if limit is not None:
            value = frontmatter_value(lines, key) or ""
            if len(value) > limit:
                violations.append(
                    (rel, lineno, "R10", f"{key}: {len(value)} chars > {limit}")
                )

    if path.name == "SKILL.md":
        declared = frontmatter_name(lines)
        expected = path.parent.name
        if declared != expected:
            violations.append((rel, 1, "R8", f"name: {declared!r} != directory {expected!r}"))
        # R5 policed which keys were *allowed* and never asked whether the two
        # the spec requires were there. A skill with no description is not a
        # narrow spec violation: description is the only thing a host matches a
        # request against, so the skill is installed and unreachable.
        if not (frontmatter_value(lines, "description") or "").strip():
            violations.append((rel, 1, "R11", "description: missing or empty"))
        if declared is not None and not NAME_GRAMMAR.match(declared):
            violations.append((rel, 1, "R12", f"name: {declared!r}"))

    if path.name == "SKILL.md":
        lowered = text.lower()
        # Both halves, not either: the sentinel alone says when to fan out and
        # never says what to do instead.
        portable = SUBAGENT_SENTINEL in lowered and any(
            phrase in lowered for phrase in SEQUENTIAL_FALLBACK
        )
        if not portable:
            for lineno, line in enumerate(lines, 1):
                if FANOUT.search(line):
                    violations.append((rel, lineno, "R9", line.strip()))
                    break  # one violation per file: the clause fixes them all at once

    # SKILL.md only, and not because reference files are safe. SKILL.md is the
    # one file the Agent Skills spec guarantees a host loads, so it is the only
    # place a stated rule is certain to reach the writer. Widen this to every
    # markdown file under skills/ and `references/templates.md` alone trips the
    # rule on 18 lines (15 of them a `.env` mention, 17 mentions in all) —
    # scaffolding inside a fenced template, instructing nobody. The keyword on
    # its own means nothing anywhere: measured at `f61cfbd` over
    # `skills/**/*.py`, all three hits are names rather than instructions — a
    # `.env` entry in an extension list (project_shape.py:145) and a
    # `.env.local` graph fixture with the comment explaining it
    # (test_graph_ops.py:2090, :2095) — and all three are already out of scope
    # at the markdown-only return above. A rule that cries wolf gets switched
    # off, which is worse than no rule.
    if path.name == "SKILL.md":
        reads_secrets = [
            lineno for lineno, line in enumerate(lines, 1) if SECRET_MATERIAL.search(line)
        ]
        stated = (
            REDACTION_SENTINEL in text.lower()
            and REDACTION_PLACEHOLDER.search(text) is not None
        )
        if reads_secrets and not stated:
            first = reads_secrets[0]
            # one violation per file: one clause covers every mention
            violations.append((rel, first, "R14", lines[first - 1].strip()))

        # ...and the rule has to be where the writing happens. `stated` is a
        # presence check over the whole file, so on its own it cannot tell a rule
        # from an echo of one: the security scan's SKILL.md states it twice, and
        # before this clause existed, reverting the evidence block to a bare
        # `{code snippet}` and deleting the whole `### Redaction` section each
        # left the gate at exit 0. This clause closes the first — measured
        # 2026-08-23 on a tree copy, that revert now reports `SKILL.md:871: R14`.
        # **The second still passes**, because the sentinel inside the slot keeps
        # `stated` true; counting surfaces is not something a presence gate can
        # do. Not conditioned on `stated` — prose elsewhere is the SEC-009 excuse.
        if reads_secrets:
            for lineno, line in enumerate(lines, 1):
                if not COPIED_SLOT.match(line):
                    continue
                if REDACTION_PLACEHOLDER.search(line):
                    continue
                if REDACTION_SENTINEL in line.lower():
                    continue
                violations.append((rel, lineno, "R14", line.strip()))

    return violations


def load_allowed_commands(root):
    """Return every valid `freya <command>` word: manifest entries plus builtins."""
    manifest = json.loads((root / "bin" / "commands.json").read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise ValueError("bin/commands.json must contain a JSON object")
    return set(manifest) | set(BUILTIN_COMMANDS)


def scan(root, rules=None):
    """Scan every markdown and Python file under root/skills. Returns sorted violations."""
    allowed = load_allowed_commands(root)
    violations = []
    for path in sorted((root / "skills").rglob("*.md")):
        violations.extend(check_file(path, str(path.relative_to(root)), allowed, markdown=True))
    for path in sorted((root / "skills").rglob("*.py")):
        violations.extend(check_file(path, str(path.relative_to(root)), allowed, markdown=False))
    if rules is not None:
        violations = [v for v in violations if v[2] in rules]
    return sorted(violations)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Check the shipped skill layer for agent-specific constructs."
    )
    parser.add_argument("--root", type=Path, default=None, help="Suite root (default: this checkout)")
    parser.add_argument(
        "--rule", action="append", choices=sorted(RULES), help="Only report these rules (repeatable)"
    )
    args = parser.parse_args(argv)

    root = args.root if args.root is not None else Path(__file__).resolve().parents[1]

    try:
        violations = scan(root, rules=set(args.rule) if args.rule else None)
    except (OSError, ValueError) as exc:
        print(f"check-skill-conformance: {exc}", file=sys.stderr)
        return 2

    for rel, lineno, rule, excerpt in violations:
        print(f"{rel}:{lineno}: {rule}: {excerpt}")

    if violations:
        counts = {}
        for _, _, rule, _ in violations:
            counts[rule] = counts.get(rule, 0) + 1
        print(file=sys.stderr)
        for rule in sorted(counts):
            print(f"  {rule} ({counts[rule]}): {RULES[rule]}", file=sys.stderr)
        print(f"\n{len(violations)} violation(s).", file=sys.stderr)
        return 1

    print("skill layer is conformant.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
