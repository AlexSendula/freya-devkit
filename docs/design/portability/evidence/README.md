# Validation evidence

Raw extracts behind live-agent validation runs belong here — the load-bearing artifacts a
run's prose cites, at minimum the tool-invocation counts, the quoted prompt blocks, and one
full driver stderr transcript per adapter. Commit them before the prose that cites them, so a
later run can be diffed against an earlier one instead of re-purchased with fresh quota. The
convention comes from [`../phase-7-validation-log.md`](../phase-7-validation-log.md), whose
numbers were transcribed from logs that lived under `/tmp` and are gone.
