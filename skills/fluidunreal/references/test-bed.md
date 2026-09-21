# Test bed and frame

**Not available yet.** `game.smoke_test` and `game.screenshot` are lot 3. They answer
`UNSUPPORTED_CAPABILITY`. What follows is what lot 0 proved on the real engine, which is what they
will be built from.

Examples: [request-game-smoke-test.json](../assets/request-game-smoke-test.json),
[request-game-screenshot.json](../assets/request-game-screenshot.json).

## The bed

A Blueprint-only project whose scene is built **in code** at test time: a floor, a wall, a prop, and
a `Character` carrying the imported skeletal mesh. No `.uasset` or `.umap` is committed. The
template is three text files, pinned by sha256.

## What lot 0 proved, and how

Headless Play-In-Editor is driveable from Python: 180 ticks at a fixed sixtieth of a second through
`register_slate_post_tick_callback`. Ten checks measured and passed, zero failed, four not measured
by that bed.

Four things had to be right, and each was wrong first:

- **`editor_request_begin_play`, not `editor_play_simulate`.** Simulate-In-Editor left the pawn at
  the origin with zero velocity for 180 ticks. It looked alive and measured a statue.
- **The measured actor lives in the PIE world.** The editor actor never moves; the simulation runs
  on a duplicate.
- **`add_movement_input` needs `force=True`** and a possessed pawn, or the input is dropped.
- **The PIE duplicate does not inherit the clip.** Playback has to be re-armed on it, with
  `play_animation`; there is no `anim_to_play` property on this series.

Measured afterwards: the capsule rests 2.15 cm above the floor because the movement component parks
it there, so the tolerance is 3 cm and the reason is written down rather than the number fudged.

## The fourteen checks

The bed's own four (idle state and prop attachment) are `not_run` until the kit builds them. A
check that was not measured is listed as such. The report is written **before** the editor quits: a
run that writes no report proves nothing, and the kit refuses it rather than inferring a pass.

## The frame

`game.screenshot` renders off-screen and reports `rendered_share`, the part of the frame the
character covers, against a frame without it as the negative control.

**Lot 0 refused its own number.** The share read 69 % three times. Opening both PNGs showed the
second frame was a different scene entirely, so the number measured the view changing, not the
character. The probe now refuses any share above 40 % and reports `not_run`. Destroying the
auto-spawned default pawn ends the PIE session, and the second capture falls to another viewport.

Two consequences the kit keeps: `take_high_res_screenshot` is **latent**, so waiting for the file in
a sleep loop stops the engine ticking and nothing is ever written; and the capture has to be aimed
at the bed's camera, because it takes the game viewport.

**Open `ue-frame.png` and say you looked at it** before judging how the character looks. A share
that nobody looked at is not evidence. That is not a formality here: the 69 % of lot 0 was green,
repeatable, and meaningless.

## What this bed never proves

It is the kit's test bed, not your game. One character, one clip. Input is injected through
`add_movement_input`, not through a keyboard. Headless means no image at all from the smoke test.
No frame rate and no GPU figure is ever reported: only `wall_time_ms` and the machine.
