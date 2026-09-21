# First human review — 2026-09-21

Reviewer: the project owner, in the Unreal Engine 5.8.2 editor, on the demo project laid down by
`scripts/demo.ps1` (`C:\Tafor\Projet\fluidunreal-demo`).

## What was looked at, and what was seen

| Asset | What was done | Seen |
| --- | --- | --- |
| `A_vitruvian_walk-baked` | opened in the animation editor | the character walks |
| `SK_vitruvian` | dragged into the level | the character is visible in the scene |

The level the editor opens on is Unreal's own default landscape, not something the kit made: the
demo project carries no map, only the imported assets under `Content/Fluid/`.

## What it settles

The import carries the animation: a human watched it play. So the 0.0 cm that `game.smoke_test`
read in Play-In-Editor was not a broken import. It was the bed reading a local translation that
does not move (see `references/test-bed.md`).

## What it does not settle

Nothing here was seen playing in a game. Dragging a skeletal mesh into a level shows it, it does not
play it.

## What was found after it, and what to look at next

The walk that was seen walking travels. Every bone of the GLB moves 0.59 m forward over the clip,
and the bundle declares it in place. In the animation editor that shows as the character leaving its
origin and snapping back each time the clip loops; nobody was asked to look for it, so nobody saw
it. The audit had passed it by reading `CustomRig_Vitruvian_ProxyTrueRootJoint`, a joint the
importer adds, and now fails it at 57.5 cm.

Next look: scrub `A_vitruvian_walk-baked` in the animation editor with the grid visible, and say
whether the character stays over the origin (the audit is wrong) or walks away from it and pops
back (the audit is right).

## Second look, on the 0.3.2 demo

The owner ran `scripts/demo.ps1` on `C:\Tafor\Projet\fluidunreal-demo-032`, opened the frame and
the project, and played `A_vitruvian_walk-baked` in the animation editor.

| Looked at | Seen | What it settles |
| --- | --- | --- |
| `ue-frame.png` | the character is visible | the frame draws the character |
| the walk, looping | "a character that moves forward, arms held out, in a loop" | the clip travels and snaps back: the audit's failure of the in-place declaration is right. The arms do not swing: they hold the character's rest pose, an A-pose |

The arms had been measured all along (the distance between the hands does not change while the
feet move 5 to 9 cm) and reported by nobody. `game.smoke_test` now warns about it by name, and U07
asserts the warning. It is a limit of the clip, not of the import: fluidblend's walk recipe says
"no arm swing" in its own limits.
