# Principles

> The project's constitution: project-wide rules that sit **above** every spec and decision.
> When a spec, decision, or change conflicts with a principle, the principle wins (or the
> principle must be consciously amended). Keep this short — a handful of durable rules, not a
> style guide.

## How these are enforced

- **Soft (context injection):** this file is auto-injected into the working context of
  brainstorming, planning, and wrap-up, so design happens with the constitution in view.
- **Checkpoint:** wrap-up and code-review diff the change against these principles and raise a
  finding on violation.

A principle that is cheaply testable *may* additionally be promoted to a guard scenario, but
promotion is never required.

## Principles

<!-- Replace these examples with your project's real rules. Each principle is one rule plus a
     one-line rationale. Delete the examples you don't need. -->

1. **Authenticated by default.** Every endpoint requires authentication unless a spec explicitly
   documents and justifies a public exception.
   _Why: a forgotten auth check should fail closed, not open._

2. **No secret in source.** Secrets come from the environment/secret store, never committed to the
   repo.
   _Why: committed secrets are effectively permanent once in history._

3. **Single source of truth.** A generated projection of one source is allowed; two hand-maintained
   copies that can drift are not.
   _Why: duplicated truth silently diverges._
