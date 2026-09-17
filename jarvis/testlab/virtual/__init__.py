"""The `virtual` execution profile: the production voice stack with controlled doubles.

Binding contract: `docs/testlab.md` ("Virtual profile"). This subpackage is the
productized async conversation harness (READINESS B4.1): production code cannot
import from `tests.`, so the reusable core lives here and
`tests/integration/async_conversation_harness.py` re-exports it unchanged.

Nothing here is imported by the pure Test Lab contract modules; the registry
(`jarvis.testlab.virtual.registry`) resolves the runners lazily so a supervisor
that never runs a virtual diagnostic never imports the voice stack.
"""

from __future__ import annotations

__all__ = ["PatchStack"]

from jarvis.testlab.virtual.patching import PatchStack
