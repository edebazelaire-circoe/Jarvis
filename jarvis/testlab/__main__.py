"""`python -m jarvis.testlab`: the Category 2 Test Lab command line.

Binding contract: `docs/testlab.md` ("Native API, CLI and HTTP"). A module entry point
rather than a new `jarvis/app.py` subcommand, so the Test Lab adds nothing to the
application's own command surface (READINESS, conflict zones).
"""

from __future__ import annotations

import sys

from jarvis.testlab.cli import main

if __name__ == "__main__":
    sys.exit(main())
