# `polyglot/` — working record for Track B

**Temporary. This directory is deleted when the feature ships.**

Track B is the polyglot substrate: making `code-graph` see languages beyond TS/JS/Python/Go,
adding a resource graph for config-as-code, and making the whole toolkit framework-agnostic.
The brief lives in [`../backlog.md`](../backlog.md) under *Next initiative*; this directory is
the scratch record of doing it.

## Why it exists

At the end of the feature, four things have to be updated, and each needs different input:

| Target | Needs |
|---|---|
| [`../decisions/`](../decisions/) | Every fork where a real alternative was rejected → one ADR each. Staged in [`decisions.md`](decisions.md), already in ADR shape |
| [`../backlog.md`](../backlog.md) | What stayed deferred, what got discovered, what shipped |
| `../*.md` | Factual changes: new commands, new paths, changed behaviour |
| [`../explanations/`](../explanations/) | Narrative for the site, and one entry per reversal for `evolution.html` |

Reconstructing that from a diff at the end does not work — the *rejected* alternative and the
*reason* are never in the diff. So they get written down as they happen, here, and distilled
when the feature lands.

## Start here

[`explainer/index.html`](explainer/index.html) — **the short version**: where the work stands,
what needs deciding, and what was decided without asking. Every claim links through to
[`explainer/details.html`](explainer/details.html), which carries the measurements, the
rejected alternatives and the review findings in full.

Open either in a browser; they are self-contained and work over `file://`.

## The lifecycle, and why it is enforced

0. **Orient:** [`explainer/`](explainer/) is the readable summary;
   [`spec.md`](spec.md) is the design; [`architecture.html`](architecture.html) is
   the same thing with diagrams.
1. **During:** record decisions in [`decisions.md`](decisions.md) — already in ADR shape, so
   closing the feature is transcription rather than archaeology. Record reversals and
   measurements in [`log.md`](log.md) as they happen.
2. **At the end:** distil into ADRs, update the markdown and the site, add the reversals to
   `evolution.html`.
3. **Then delete this directory.** Git history keeps it.

Step 3 is the point. `docs/design/` accumulated 19 per-feature records and `docs/superpowers/`
31 executed plans, because nothing ever removed them — the reasoning stayed scattered across
dated files nobody read, and the live docs drifted from it. That is what the 2026-08-19
restructure cleaned up ([ADR-016](../decisions/ADR-016-prove-it-against-the-real-thing.md)).
A working directory that outlives its feature recreates the problem.

The related convention: a phase no longer gets its own explainer page. It updates the relevant
section of the site and adds one entry to the evolution chapter.

## What belongs in the log

- **Decisions** — the fork, what was chosen, what was rejected and why. These become ADRs, so
  capture the rejected branch properly; it is the part that cannot be recovered later.
- **Reversals** — a plan that turned out wrong, and what replaced it. These are the highest
  value entries: they become `evolution.html`, and they stop the same wrong path being taken
  twice.
- **Measurements** — anything obtained by running something. Carry the number and its honest
  limits.
- **Doc impact** — "this changes `skill-reference.md`" noted at the moment it becomes true,
  so the end-of-feature sweep is a checklist rather than an archaeology exercise.

Not: task lists, status updates, or anything already in the code. Those rot, and the backlog
already owns outstanding work.
