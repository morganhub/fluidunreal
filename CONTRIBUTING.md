# Contributing

The rules this kit is built on. They are not style preferences: each one exists because breaking it
produces a claim nobody can check.

- **An operation is available only if it is implemented, tested against the real locked engine and
  documented.** Otherwise it answers `UNSUPPORTED_CAPABILITY` and says so. No simulated success, no
  weakened validator, no test deleted to announce a pass.
- **The skill guides, it computes nothing.** Everything goes through the CLI. Never an improvised
  script in the editor.
- **A narrow scope with a stated refusal beats a broad promise.**
- **Technical evidence is not artistic approval.** A measurement that comes back green, or exactly
  zero, is checked against a render and a negative control before it is believed. Measure, then
  look. Lot 0 produced two examples: a 69 % coverage that turned out to compare two different
  scenes, and a root travel of exactly 0 cm that only means something because the same call on a
  moving bone returns 57.5 cm.
- **A measurement that could not be taken is `not_run`**, listed, and never counted as a pass.
- **An interface gets tested by a human.** Every defect found becomes an assertion.
- The kit installs nothing globally, never writes `config/permissions.json`, builds every external
  command as an argument list, and refuses any path outside the root, UNC, `..`, a reparse point or
  a protected one.
- **Deliver files, evidence, limits, and the next useful decision.**

## Working on it

```powershell
uv sync --python 3.13
uv run ruff check . ; uv run ruff format --check .
uv run pytest tests/unit -q          # no Unreal Engine needed
uv run pytest tests -q --acceptance-report docs/acceptance-reports/lot1
```

Commits are short and in English: `x.y.z: keyword`. The repository is English-only.

## The sibling kit

The reusable core is imported from `fluidblend`, pinned to a published tag, never copied. Its
`docs/architecture.md` lists what may be imported and promises those modules change only with a
CHANGELOG entry marked **breaking for fluidunreal**. If you need something outside that list, ask
for it to be added there rather than copying it here.
