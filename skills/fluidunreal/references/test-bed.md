# Test bed and frame

`game.smoke_test` is available since 0.3.1: U07 plays the reference character in the real 5.8.2,
and its negative control fails on cue. `game.screenshot` is not built and answers
`UNSUPPORTED_CAPABILITY`.

Optional parameter: `clip_id`, the clip to play (the first one when absent). A clip that is named
and absent is not refused: the bed runs without it and fails the animation checks by name.

Examples: [request-game-smoke-test.json](../assets/request-game-smoke-test.json),
[request-game-screenshot.json](../assets/request-game-screenshot.json).

## The bed

A Blueprint-only project whose scene is built **in code** at test time: a floor, a wall, a prop, and
a `Character` carrying the imported skeletal mesh. No `.uasset` or `.umap` is committed. The
template is three text files, pinned by sha256.

## What lot 0 proved, and how

Headless Play-In-Editor is driveable from Python: 180 ticks at a fixed sixtieth of a second through
`register_slate_post_tick_callback`. Ten checks measured and passed, zero failed, four not measured
by that bed. One of the ten was passed by the wrong thing: see below.

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

## The check that was wrong three times

`walk_clip_moves_bones` asks whether the clip deforms the skeleton while the character stands still.
It is the check most easily passed by something else, and it was:

1. Lot 0 passed it by measuring the actor walking: its window overlapped the walk.
2. The next version read a big toe's offset from the reference pose: a local translation, constant
   for a bone that only rotates. It read 0.0 cm, which looked like a clip that does not play. Probe
   P6 read the player itself, its position advancing and `is_playing` true: the clip plays.
3. The next read bones relative to the actor and found every bone, spine and forehead included,
   moving the same 10 cm in 0.34 s. Unrelated bones moving by the same amount is the whole body
   moving, not deformation. The reference walk carries the body forward at 30 cm/s: it is declared
   in place and travels 0.58 m per loop, which the audit now fails.

It now reads the **distance between the two feet**, which no displacement of the whole body can
change. Over the window it varies by about 5 cm. The hands are read too and hold their distance:
this walk does not swing its arms, and its recipe says so in its limits. The negative control runs
the same bed with no clip: the feet's distance stays constant, and `walk_clip_found`,
`walk_plays_looping` and `walk_clip_moves_bones` fail by name.

`walk_plays_looping` reads the player: its position advances (0.84 s to 1.18 s over the window) and
it says it is playing. A successful `play_animation` call is not taken for playback.

## What passes, and what a pass does not say

Ten checks measured and passed, zero failed, four not measured: the world loads, the character
spawns in the PIE world with the bundle's 188 bones, rests on the floor, the clip plays and deforms
the legs, the character walks 356 cm, the wall stops it, and it comes within 2.4 cm of the prop.

The reference walk drifts inside its capsule, and the bed sees it: that is the uniform 10 cm. In a
game, a clip declared in place that travels slides ahead of the capsule and snaps back every loop.
None of the fourteen checks is about that, so the smoke test passes; the audit's
`root_motion_travel` fails. Read both.

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
