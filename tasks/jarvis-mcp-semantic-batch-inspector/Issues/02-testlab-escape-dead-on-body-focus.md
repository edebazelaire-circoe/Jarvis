# Test Lab: Escape does nothing when focus sits on <body>

Found by the Slice 07 code review (2026-09-25), pre-existing, not caused by this task.

The Test Lab dialog handles Escape only through a keydown listener on its own root, and the page shortcut handler returns early while the dialog is open. After a click on a non-focusable area (header, strip) focus falls to `<body>` and Escape no longer closes the dialog until the user presses Tab.

Fix: same pattern as `control_center_timeline.js` (~2437) and, after Slice 07, the MCP inspector — a capture-phase `keydown` listener on `document` that closes the dialog on Escape while it is open.
