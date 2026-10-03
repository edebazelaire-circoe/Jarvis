# One library per data root.

Found by: Slice 00 audit (2026-10-03). Status: open.

Worktrees and `jarvis-dst` have separate data roots, so prefabs saved during agent sandbox runs never reach the live JARVIS. An export/import (or promote-to-package) workflow is a follow-up.
