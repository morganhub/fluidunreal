"""Entry point of the fluidunreal runtime, executed inside the Unreal editor.

Launched by the engine as:
    UnrealEditor-Cmd.exe <project.uproject> "-ExecCmds=py <this file>" ...

The envelope's path arrives in FLUIDUNREAL_ENVELOPE, not on the command line. Lot 0 measured that
`-ExecCmds` loses inner quotes on the way to CreateProcess, so a value containing a space is split
and the editor runs a bare `py` that does nothing at all, silently, until the timeout.

Standard library and `unreal` only. The editor embeds Python 3.11, not the 3.13 the engine runs on.
"""

import os
import sys


def main():
    envelope = os.environ.get("FLUIDUNREAL_ENVELOPE")
    if not envelope:
        raise SystemExit("FLUIDUNREAL_ENVELOPE is not set: nothing to run")
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    import fluidunreal_runtime

    fluidunreal_runtime.main(envelope)


main()
