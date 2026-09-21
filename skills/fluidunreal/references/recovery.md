# Recovery

## Exit codes

| Code | Meaning | What to do |
| --- | --- | --- |
| 0 | success, dry-run, or an idempotent replay | deliver the files and the evidence |
| 1 | a known failure | read `errors[]`; the recovery line says what would help |
| 2 | blocked: permission, dependency, a path outside the root, or an operation this lot does not have | stop and ask; never work around it |
| 3 | conflict: a reused `operation_id`, an occupied destination, a lock | read the conflict; do not force |
| 4 | invalid request | fix it against the schema; nothing was executed |
| 5 | uncertain write state | `fluidunreal task reconcile` before any retry |
| 6 | budget exceeded, refused before anything started | report the estimate and where it came from; do not raise the budget alone |

## Idempotency

An `operation_id` is the identity of an attempt. Re-running it with the same parameters replays the
published result and creates nothing: no task folder, no editor, no version, no revision, and a
`replayed` line in the journal. Re-running it with **different** parameters is exit 3: use a new one
rather than making the first result ambiguous.

A task still marked queued, running, validating or unknown blocks a retry with exit 5. That is
deliberate: repeating a write whose outcome is unknown is how a project ends up with two
half-imports.

## An interrupted task

```powershell
fluidunreal resume --project .
fluidunreal task status --project . --id <task_id>
fluidunreal task cancel --project . --id <task_id>
fluidunreal task reconcile --project . --id <task_id>
```

| Command | What it does | Exit |
| --- | --- | --- |
| `resume` | rebuilds `state/state.json` from the journal and lists every task left queued, running, validating or unknown, with the exact reconcile command and whether its editor still runs. Writes `state/resume-report.json` | 0 when nothing is left, 5 otherwise |
| `task status` | what the task recorded, the tail of its `unreal.log`, whether its editor still runs, and the next command | 0; 4 for an unknown task id |
| `task cancel` | kills the task's editor and leaves the task `unknown` | 5, reconcile next; 0 if it had already finished |
| `task reconcile` | stops the editor if it still runs, removes what the task provably wrote, and concludes it `failed` | 0 once concluded; 5 while it cannot conclude |

Run `resume` first after anything went wrong: it names every task that needs a decision. The task
commands print JSON whether or not `--json` is given.

**The editor is identified by its pid and by the `-fluidunreal-task=<task_id>` marker on its
command line**, never by its name. A pid that Windows has recycled, or an editor someone opened
themselves, is never touched.

**What reconcile removes, and nothing else:**

- the importer's staging folder, `Content/Fluid/_staging/<task_id>/`;
- the version folder `Content/Fluid/<asset_id>/vNNN/`, only when it has no `FLUID_CONTENT.json` **and**
  `NNN` is the `next_version` recorded in the task's envelope, `state/tasks/<task_id>/request.json`.

That number is one past every version folder that existed when the task started, so nothing older
can carry it, and a folder without its index was never published. Everything else reconcile finds is
listed under `kept` with the reason and left alone: another task's staging folder, an unindexed
version with another number, a published version, a folder holding anything that is not a `.uasset`
or `.umap`, a link. The report goes to the journal (`reconciled`) and to
`state/tasks/<task_id>/reconcile.json`.

Afterwards the same `operation_id` runs again. One exception, stated in the task's error: a task that
stopped while publishing already has outputs under `imports/` or `reviews/` for that id, and a retry
under it is refused at publication. Use a new one.

Reconcile answers 5 and changes nothing when another `fluidunreal` process holds the project (a run
still in progress: `task cancel` stops its editor), when the editor could not be stopped, or when a
file it proved was the task's could not be removed. Removing some and concluding would leave the
rest attributed to no one; run it again once nothing holds the file.

`cancel` leaves the task `unknown` rather than `cancelled` for the same reason: a killed import may
have left a staging folder or half a version, and a retry must not start over them unseen.

## Budgets, before anything starts

```powershell
fluidunreal plan --project . --operation requests/asset-import.json
```

An operation that starts the editor is estimated before its task folder or its editor exists, and
refused with `BUDGET_EXCEEDED` (exit 6) when the time exceeds `budgets.max_task_minutes`, when the
disk it needs exceeds `budgets.max_new_disk_gib`, or when the drive holding the content root has
less free space than it needs. `run --dry-run` is held to the same check.

| Number | Where it comes from |
| --- | --- |
| the run | the mean of the last eight finished runs of that operation on this project (`state/metrics.json`, key `unreal.elapsed_s.<operation>`). With none: 120 s, a stated default, three times the longest run lot 3 measured |
| the editor's start | `warmup_seconds`, the wall time of the last `doctor` probe. Without it: nothing when runs were measured, since each includes a start; otherwise `config/local.json` `unreal_startup_timeout_s` (600 s by default) |
| the disk needed | for an import, the accepted bundle times 4, a stated factor: no import has been weighed yet. 64 MiB for anything else |
| the free space | the drive that holds `Content/Fluid` |

With nothing measured, an import is estimated at 12 minutes. A run that timed out is not recorded:
it measures its timeout, not the operation, and would push every later estimate over the budget.
`doctor` then measures the start, and each finished run replaces a default with a figure.

`plan` prints the estimate, where each number came from, and a verdict (`within_budget`,
`over_budget`, `blocked`), after the same gates `run` applies. It executes nothing and saves the plan
to `state/plans/<operation_id>.json`. Exit 0 within budget, 6 over it, 2 or 4 for what `run` would
refuse first. A host operation is estimated but never refused on the estimate; `bundle.accept`
checks the bundle's declared size against `max_new_disk_gib` itself.

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
fluidunreal resume --project .
```

Every run's outputs are published under `reviews/<area>/<operation_id>/`, and the result names the
folder. The journal in `state/journal.jsonl` is append-only and shares its format with fluidblend,
so one reader understands both projects.
