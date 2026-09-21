# Security

What this kit protects against, how, and what proves it. A line that says **not verified** means the
kit does not claim it. Everything else names the test or the observation behind it.

## Inherited from fluidblend

| Threat | What the kit does | Proof |
| --- | --- | --- |
| A hostile path: `..`, a UNC share, a path outside the root, a link | Every `*_path` parameter is resolved inside the project root before a task exists; `bundle.accept`'s source, the one path allowed outside, is held to the checks that need no root | U10: 13 requests refused before execution, no task folder, no journal entry |
| A command smuggled in a parameter | `;`, `$` and backtick are refused in paths; every external command is an argument list; nothing goes through a shell | U10; `test_code_guards.py` walks every Python file for `shell=True` and `os.system`, and is shown a planted offence to prove it can fire |
| Two writers at once | One project lock, one `unreal-instance` lock; an editor already open on the project is a conflict, never a session to write into | `SCENE_CONFLICT` before launch; U09 |
| A write whose outcome is unknown | The task stays `unknown` (exit 5) and every retry is refused until `task reconcile` concludes it, removing only what that task provably wrote | U12, with a real editor killed mid-import |
| A secret in the repository or a log | The kit reads no `.env` or credential file. The test bed's `AndroidFileServer` generated a security token into `DefaultEngine.ini` in lot 0 and it was committed: the plugin is now disabled, the bed is materialised from a template, the history was rewritten, and a test fails on any committed file carrying such a token | `test_no_committed_file_carries_a_generated_credential` |

## Specific to Unreal

### The Python plugin runs arbitrary code inside the editor

Only the kit's runtime is ever passed to it: `-ExecCmds=py <kit>/unreal_runtime/entrypoint.py`, one
fixed token, never a generated script. The runtime tree is hashed before every launch
(`RUNTIME_MANIFEST.json`) and the hash is journalled with the run; the runtime refuses to run under a
host that expects another version. It reads its request from a file named in `FLUIDUNREAL_ENVELOPE`,
and every `PYTHON*` variable is stripped from the editor's environment. `test_code_guards.py` checks
that the runtime parses as Python 3.11, imports only the standard library and `unreal`, starts no
process, and calls no `exec`, `eval` or `compile`.

### A .uproject loads its plugins before the kit has any say

The kit opens a project only when every plugin it enables is one it was proven with (the test bed's
two, and the three Interchange plugins the engine enables itself) or one a person approved by name
with `fluidunreal approve-plugins`. Anything else stops every engine operation before a task exists
(`PERMISSION_REQUIRED`, exit 2), naming the plugins. The approval is recorded in
`state/approvals/plugins.json`; the kit never writes it on its own, a name the project does not
enable cannot be approved, and `doctor` lists what is waiting. `GLTFImporter`, which does not exist on
5.8 and aborts the editor, is reported as incompatible. Proof: `test_plugins.py`.

### Network

The test bed's `DefaultEngine.ini` turns editor analytics off, sets `bAgreeToCrashUpload=False` and
`bImplicitSend=False`, and disables `AndroidFileServer` and its network connection. The kit itself
opens no port and makes no request in P0/P1; `allow_network: false` is the default.

**Not verified**: that the editor makes no connection at all. The engine still mounts its telemetry
plugins (`EditorTelemetry`, `RuntimeTelemetry`, seen in every run's log), and no network capture was
made. In a project you bring, your own `.ini` governs, not the bed's.

### Child processes

`task cancel` and `task reconcile` kill a worker only when its pid is alive, is an editor, and carries
the `-fluidunreal-task=<id>` marker: a recycled pid is never taken for a task's editor. `taskkill /T`
takes its children with it. Proof: U12.

Every run starts a `CrashReportClient`, logged as `Started CrashReportClient (pid=…)`. Neither
`-nocrashreports` nor `-NoCrashReport` prevents it on 5.8.2 (tried 2026-09-21, three runs, the line
was there every time). Each one that the kit's runs started had exited with its run when checked.
Whether it would send anything after a real crash is **not verified**: no crash was provoked; upload
is off in the bed's `.ini` only.

### Your content

In a project you bring (`init --ue-project`), the kit writes under `Content/Fluid/**` and nowhere
else. Before a task exists it refuses another engine series, a disabled `PythonScriptPlugin` (it
gives the line to add and never edits your `.uproject`), a linked `Content/Fluid`, and anything there
it did not index. Around every engine run it compares the rest of the project by size and time and
reports any change by name: the engine added `Config/DefaultInput.ini` to a project that had none.
The test bed builds in a blank map it never saves. Proof: `test_user_project.py` and a real run into
a copy of someone else's project (`test_existing_project.py`).

## What the kit never does

No elevation. No change to the PowerShell execution policy. No port opened. No global install: the
kit and its tools live in its folder and in `%LOCALAPPDATA%\fluidblend\tools\`, shared with fluidblend.
It never changes `config/permissions.json` once `init` has written it, and never approves a plugin
on its own. Unit tests replace every process call, so no test can start, query or kill a real editor
while someone has one open.
