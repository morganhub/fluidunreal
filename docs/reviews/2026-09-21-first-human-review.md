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
