# Recovery

## Exit codes

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | success, dry-run, or an idempotent replay | deliver the files and the evidence |
| 1 | a known failure | read `errors[]`; the recovery line says what would help |
| 2 | blocked: permission, dependency, or an operation this lot does not have | stop and ask; never work around it |
| 3 | conflict: a reused `operation_id`, an occupied destination, a lock | read the conflict; do not force |
| 4 | invalid request | fix it against the schema; nothing was executed |
| 5 | uncertain write state | `fluidunreal task reconcile` before any retry |
| 6 | budget exceeded | report what was consumed; do not raise the budget alone |

## Idempotency

An `operation_id` is the identity of an attempt. Re-running it with the same parameters replays the
published result and creates nothing. Re-running it with **different** parameters is exit 3: use a
new one rather than making the first result ambiguous.

A task still marked running, validating or unknown blocks a retry with exit 5. That is deliberate:
repeating a write whose outcome is unknown is how a project ends up with two half-imports.

## Conflicts

- A destination under `reviews/` or `imports/` that already holds something is a conflict, never an
  overwrite.
- A `bundle_id` already accepted with different contents is a conflict. An identical one replays.
- An Unreal editor open on the project is a conflict. Report it and ask for it to be closed. Never
  close, save or reload someone's editor for them.

## When something did not run

`not_run` is a status of its own. It is never folded into a pass and never reported as a failure.
The acceptance report shows it in its own column, and the audit lists which measurements could not
be taken and why. If a run cannot prove something, the honest output is to say what it could not
prove.

## Reading what a run left behind

```powershell
fluidunreal inspect --project . --json
fluidunreal capabilities --project .
```

Every run's outputs are published under `reviews/<area>/<operation_id>/`, and the result names the
folder. The journal in `state/journal.jsonl` is append-only and shares its format with fluidblend,
so one reader understands both projects.
