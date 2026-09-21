# Changelog

Format: one entry per released version. Dates are those of the development machine.
This project follows semantic versioning from 1.0.0 onwards; before that, the interface may change.

## 0.3.4 — 2026-09-21 — what the skill promised about security, now built and proven

- **Plugins are reviewed before a project is opened.** The skill told agents to stop on "a plugin
  that is not on the whitelist", and there was no whitelist. The kit now opens a project only when
  every plugin it enables is one it was proven with (the test bed's two, and the three Interchange
  plugins the engine enables itself) or one a person approved by name with
  `fluidunreal approve-plugins`, recorded in `state/approvals/plugins.json`. Anything else stops every
  engine operation before a task exists, `PERMISSION_REQUIRED`, naming them; `doctor` lists them.
  The kit never approves on its own, and a name the project does not enable cannot be approved.
- **Guards on the code itself**: the runtime parses as Python 3.11, imports only the standard
  library and `unreal`, starts no process and calls no `exec` or `eval`; nothing in the repository
  goes through a shell. Each guard is shown a planted offence, so a green one means something.
- **fluidblend is pinned on `v0.6.2`**, whose bundles are schema 1.1 and which reads any 1.x. The
  vendored `schemas/handoff-bundle.json` follows. The reference fixture stays 1.0 and is still read.
- **`bake_rigid_limbs` baked the wrong frames.** It built its `animation.bake` from the bundle's
  `frame_range`, which is the GLB's and starts at 0: the walk would have been baked over 0-47
  instead of 1-48 (found by fluidblend 0.6.2). It now uses `source_frame_range`, the range in
  Blender, and refuses a 1.0 bundle that does not name it rather than guess the offset.
- **Both skills in one agent project**: a test installs fluidblend and fluidunreal side by side with
  their own installers, checks each copy points at its own kit, and has each wrapper answer from
  its own catalogue. `not_run` without a fluidblend checkout.
- `docs/security.md`: the threat model, each line with its proof, and what is not verified. Found
  while writing it: every run starts a `CrashReportClient`, and neither `-nocrashreports` nor
  `-NoCrashReport` stops it on 5.8.2; each one exited with its run. `docs/roadmap.md`; the README
  says what the kit does today and does not do yet.

## 0.3.3 — 2026-09-21 — lot 4 starts: what a human saw becomes a warning

- The owner watched the reference walk and saw its arms held out. The bed had measured it all
  along, the distance between the hands unchanged while the feet move 5 to 9 cm, and said nothing.
  `game.smoke_test` now warns by name when a walk leaves the arms still, and U07 asserts it. It is a
  limit of the clip, not of the import. The same look confirmed the audit: the walk moves forward
  and snaps back each loop, so its in-place declaration is false.

## 0.3.2 — 2026-09-21 — lot 3: fourteen checks, one frame, someone else's project

- **All fourteen checks of `game.smoke_test` are measured.** The bed stands, walks until the clip
  has looped, and stands again. `idle_plays_nothing` reads the clip assigned and the feet holding
  still (`is_playing` is true with no clip at all on 5.8.2, so it is reported and not used);
  `back_to_idle` stops the clip once the character stands; the prop is attached to the right hand
  before the capsule meets it, and `holds_prop` requires the hand to have carried it.
- **Looking at a frame exposed four defects of the bed that fourteen green checks had not.** The
  mesh stood 88 cm above the floor while `stands_on_floor` measured the capsule, and it faced +Y, so
  the character walked sideways. `new_level` saved `SmokeBed.umap` into the project and, on the next
  run, built the bed in whatever map was open. Without a PlayerStart, PIE spawned its default pawn
  inside the character's capsule and threw it 2.7 m before any input, which `character_moves`
  counted as walking. The bed now builds in a blank map that is never saved, starts the default
  pawn behind the camera, lowers and turns the mesh by the facing it measures on the skeleton, reads
  the feet for `stands_on_floor`, and fails a walk that drifts more than 5 cm sideways.
- **`game.screenshot` is available.** One frame of the bed from the side, then the same frame
  without the character. Both go through a `SceneCapture2D` in the PIE world with fixed exposure:
  the second `take_high_res_screenshot` had rendered the editor's world, and reported a green
  27.7 %. A difference box wider than 60 % of the frame, or a share over 40 %, is refused. Without a
  GPU the answer is `MISSING_DEPENDENCY`. U08 passes at 2.1 %; with the character hidden from both
  frames the share is 0 and the run fails, which is its control.
- **An Unreal project you already have** (`init --ue-project`). Before a task exists, the kit checks
  the engine series, that `PythonScriptPlugin` is enabled (it gives the line to add and never edits
  a `.uproject`), that `Content/Fluid` is not a link, and that nothing under it was written by
  anyone else. Around every engine run, files outside `Content/Fluid` and the engine's working
  folders are compared by size and time and any change is reported by name: the engine added
  `Config/DefaultInput.ini` to a project that had none. A real run imports, plays and shoots into a
  copy of someone else's project and finds their files untouched.
- **U12**: the real editor killed mid-import, through a test-only pause after the staging is on
  disk. Exit 5, retry refused, `task reconcile` removes the staging and publishes nothing, and the
  retry imports `v001`.
- **U14**: fluidblend bakes and exports, this kit accepts, imports, audits (technical pass: the
  bundle from fluidblend 0.6.1 declares the walk as the 0.6 m walk it is), plays and shoots; the
  `reexport_unreal` request runs in fluidblend as written and its bundle is accepted.
  `make_fixture_bundle.py --build-only` builds that studio without touching the fixture.

- **`fluidunreal task status|cancel|reconcile --project <p> --id <task_id>`.** The skill and the
  recovery messages named these, and none of them existed. `reconcile` takes the project
  lock, stops the task's editor if it still runs, removes what the task provably wrote, and
  concludes it `failed` so the same `operation_id` can run again. Provably means two things: the
  importer's staging folder, named after the task; and the version folder the task's envelope was
  given, when it has no `FLUID_CONTENT.json`. Everything else it finds is reported and left alone.
  A removal that fails keeps the task `unknown` (exit 5) rather than orphan the file. `cancel` kills
  the editor and leaves the task `unknown`, for reconcile to judge what the kill left. An editor is
  identified by its pid and the `-fluidunreal-task=<id>` marker, never by its name.
- **`fluidunreal resume --project <p>`** rebuilds the state from the journal and lists every task
  left queued, running, validating or unknown, with the exact reconcile command for each and
  whether its editor still runs. Exit 5 while anything is left.
- **Budgets are checked before execution.** An editor-backed run is estimated before its task
  folder or its editor exists, and refused with exit 6 over `max_task_minutes`, over
  `max_new_disk_gib`, or when the drive holding the content root has less free space than it needs.
  Time is the mean of the recorded runs of that operation plus the start `doctor` measured; with
  nothing measured, a stated 120 s plus `unreal_startup_timeout_s`, 12 minutes by default. Disk is
  the bundle times a stated factor of 4 for an import. Every number says where it came from. Each
  finished run records `unreal_elapsed_s` in `state/metrics.json`; a timed-out one does not, since
  it measures its timeout. Dry runs are held to the same check.
- **`fluidunreal plan --project <p> --operation <request.json>`** prints that estimate, its sources
  and a verdict after the runner's own gates, and executes nothing: exit 0 within budget, 6 over it.
  The plan is fluidblend's `Plan` plus `estimate` and `verdict`; `schemas/plan.json` changes.
- **Paths are judged before a task exists.** A `..`, a UNC share or a path outside the root was
  refused by the handler, after the task folder and its journal entry had been written, and a `;`,
  `$` or backtick in a path was not refused at all. Both are now refused in preflight.
  `bundle.accept`'s source, the one path allowed outside the root, is held to the checks that need
  no root.
- `doctor` records `warmup_seconds`, the probe's wall time. The environment reference already said
  it did.
- The envelope counted versions for the bundle's first instance when a request named its asset in
  `parameters.asset_id`, which the runtime reads first. It now counts them for that asset, so the
  version a task was told to create is the one reconcile can attribute to it.
- Recovery messages print the exact command with the project's path. Two of them lacked
  `--project` and would not have parsed.
- U09 (idempotence), U10 (escaping paths and commands) and U11 (budgets) pass without Unreal. U09
  replays a version-creating import through a fake editor that drives the real runner. Unit tests
  now replace every process call in the adapter, so none can start, query or kill a real editor.

## 0.3.1 — 2026-09-21 — the test bed plays, and the audit stops passing a false claim

- **`asset.audit` passed a false in-place claim, and now fails it.** It read root motion on bone 0,
  which is `<node>_ProxyTrueRootJoint`, a joint the importer adds and no clip animates: 0.0 cm, pass.
  Its control, a thigh at 57.5 cm, was taken for a swing; a thigh's head goes where the pelvis goes,
  so the 57.5 cm was the travel. Root motion is now read on every bone hanging from the proxy (75 on
  the reference fixture), as the median of their horizontal travel, with the largest excursion
  within the clip as the control on the reader. The reference walk, declared in place, fails at
  57.5 cm. Read from the GLB without Unreal, it travels 0.59 m: the audit is right. Declared as the
  0.6 m walk it was made from, the same clip passes; declared as 0.5 m, it fails. A declared stride
  is now scaled to the span actually read (46 frames of 48: one frame short of a loop, and one
  frame Unreal does not sample), or a correct walk fails by 2.5 cm. **Breaking**:
  `audit-report.json` loses `root_bone` and gains `root_motion_read_on`.
- **The defect is on the fluidblend side.** fluidblend 0.6.0's `animation.bake` writes its manifest
  without a `root_motion`, so every baked clip reaches the bundle as `in_place`, whatever it does.
- **`game.smoke_test` is available.** The clip does play in headless PIE: the 0.0 cm was the bed's
  reader, a local translation that a bone which only rotates keeps constant. `walk_plays_looping`
  now reads the player's position and `is_playing`; `walk_clip_moves_bones` reads the distance
  between the two feet while the actor stands still, which no displacement of the whole body can
  change. U07: 10 checks measured and passed, 4 not measured. Negative control: with a `clip_id`
  that does not exist, the bed runs without a clip and fails three checks by name. A failed run's
  report path is in the error's recovery, since a failed run publishes nothing.
- `scripts/demo.ps1` runs the smoke test too. The first human review, and what it did not see, are
  in `docs/reviews/`. Probe P6 (playback in PIE) is kept in `scripts/lot0/`.

## 0.3.0 — 2026-09-21 — the hand-off closes the loop; the test bed is held back

- **`handoff.request`.** When the import or the audit shows something that belongs in Blender, the
  kit writes a complete fluidblend request and prints the exact command, rather than touching a
  source it does not own. The catalogue of templates is closed, and every request is validated with
  fluidblend's own `validate_request` before it is written: what is handed over is something that
  kit accepts, not something this one believes it should. U13 covers all four templates.
- **`game.smoke_test` is built, runs, and stays unavailable.** Nine of its ten measurable checks
  pass against the real 5.8.2: the world loads, the character spawns in the PIE world with the
  bundle's 188 bones, rests on the floor, walks 326 cm, is stopped by the wall, and passes within a
  centimetre of the prop.

  The tenth reads exactly 0.0 cm of bone travel over fifteen consecutive samples while the
  character stands still. `play_animation` returns successfully on the PIE component and the clip
  does not advance. **Lot 0 reported that check as passing and was wrong**: its measuring window
  overlapped the window in which the character was walking, so it measured the actor translating
  rather than the skeleton deforming. `walk_plays_looping` is `not_run` for the same reason, since
  a successful API call is not playback.

  An operation that cannot pass is not shipped as available. `docs/compatibility-matrix.md` and the
  test-bed reference say so.
- The runtime gained an explicit deferred path: an operation that finishes on the editor's tick
  says so, instead of a handler blocking on a wait that stops the ticking it waits for.

## 0.2.0 — 2026-09-21 — lot 2, import and audit

The engine backend, proven against Unreal Engine 5.8.2. U05 and U06 pass.

- **`asset.import`.** One dedicated editor per operation, driven through an envelope that names
  every path the runtime may touch. The bundle imports through Interchange, the kit reads back what
  the editor created, compares it to what the bundle claimed, and only then publishes
  `/Game/Fluid/<asset_id>/vNNN/` with deterministic names. A failed check publishes nothing.
- **`asset.audit`.** Measurements with their space, unit and tolerance. Five reference bones land
  within a millimetre of the bundle's metres, and falsifying that pose by ten centimetres fails all
  five. The root bone is bone 0, and a control bone that must move is read the same way: without
  it, a root travel of zero proves nothing. A measurement that could not be taken is `not_run`.
- **Versions.** `FLUID_CONTENT.json` lists every file of a version with its hash, and the revision
  points at that, so a `.uasset` edited by hand is caught. A second import makes `v002` and leaves
  `v001` verifiable.
- **Unknown beats wrong.** An editor that writes no result leaves an unknown write state, not a
  failure: calling it failed would guess in the direction that loses work.

Three defects found by running it rather than reading it: a failure while recording the worker left
the editor orphaned; `delete_directory` left the staging folder on disk; and the root motion
measurement was reading the first animation track, which is a thigh. The control bone is what
exposed the last one, by reporting the same 57.5 cm as the root.

## 0.1.1 — 2026-09-21 — the editor's generated credentials stay out

A secret scanner flagged an AndroidFileServer token in the test bed's
`Config/DefaultEngine.ini`. The editor writes it the first time it opens a project, and the file
was tracked, so it was committed and then pinned with the token already in it.

The token opens nothing: it authenticates a debug file-transfer server to an Android build of that
throwaway project, over USB, with `bIncludeInShipping` false. There is no Android target, no build,
no service. The defect was tracking a file the editor writes into.

- The lot 0 bed is materialised from the pinned template into an ignored working copy, refreshed on
  every run. Nothing the editor writes is committed.
- `AndroidFileServer` is disabled in both `.uproject` files, so no token is generated. Verified by
  re-running P1: it passes and leaves the config clean.
- Two tests refuse the class of mistake: no tracked file may carry a generated credential, and the
  lot 0 bed may not be tracked.

The token is still in the history of `aa01702` and `fa5f7f3`. Removing it there needs a history
rewrite and a force push.

## 0.1.0 — 2026-09-21 — lot 1, the host side

Everything that happens without starting the editor, and the refusals that keep the rest honest.

- **Contracts.** `Target` and `OperationRequest` subclass fluidblend's rather than copying them,
  so the envelope stays one definition; `bundle_id` is this kit's extension and the sibling kit
  still refuses a target it cannot read. A `Measurement`'s `passed` is three-valued: an unmeasurable
  check that defaults to false reads as a defect, and one that defaults to true is a lie.
- **Project.** `init` is idempotent and keeps the creation date rather than restamping it. An
  existing Unreal project must be a real absolute path: a symlink or junction would let a write
  escape the recorded root. `inspect` reports `Saved`, `Intermediate` and `DerivedDataCache` sizes
  without counting them against the disk budget.
- **Test bed.** Laid down by `init`, pinned by sha256. It asks only for the Python plugins: lot 0
  proved that requesting `GLTFImporter` on 5.8 kills the editor before any script runs, and that
  Interchange is enabled by the engine itself.
- **Doctor.** Finds the editor through the registry and the default install, reads the series from
  `Engine/Build/Build.version` without launching anything, and hashes the binary. `available` is
  never claimed from an exit code: lot 0 watched the editor start, return zero and run nothing.
- **Bundles.** `bundle.accept`, `bundle.wrap` and `bundle.inspect`, with a stdlib GLB reader that
  parses only the JSON chunk. A bundle without a readable licence is refused: it is a
  redistribution format.
- **Runner.** The twelve-step flow trimmed to this kit, with fluidblend's exit codes and file
  formats unchanged, so one reader understands both projects. Operations that need the editor are
  refused by name with the lot they land in.
- Acceptance scenarios **U01 to U04 pass**. The engine backend, the test bed run and the hand-off
  request are lots 2 and 3, and the catalogue says so.

## 0.0.1 — 2026-09-21 — lot 0, feasibility on Unreal Engine 5.8.2

No kit yet. Five throwaway probes run against the real engine so that nothing is designed on a
guess. Raw output in `docs/lot0/`, findings in `docs/compatibility-matrix.md`.

- **Locked series: 5.8** (observed 5.8.2). Embedded Python is **3.11.8**, not the 3.13 the engine
  runs on: the runtime has to stay 3.11-compatible.
- The `GLTFImporter` plugin **no longer exists** in 5.8 and requesting it aborts the editor at
  startup; glTF import lives in Interchange, which the engine enables itself.
- The GLB imports in 5.5 s. **Scale is measured, not assumed**: five deform bones land within 1 mm
  of the bundle's reference pose, and falsifying that pose by 10 cm fails all five.
- Unreal rewrites dots to underscores in bone names and adds a proxy root joint, so the audit maps
  names and counts the bundle's bones rather than the engine's total.
- Headless Play-In-Editor is driveable from Python: 10 checks measured and passed, 0 failed, 4 not
  measured by that bed. Only `editor_request_begin_play` actually simulates.
- The off-screen frame renders, but its coverage number does not survive being looked at: it read
  69 %, and the two frames turned out to show different scenes. Refused, and left `not_run`.
- An in-place clip's root travels 0.0 cm, and the same call on a thigh returns 57.5 cm, so the zero
  is a real zero.
