# 00 - Overview

Board is the persistent workspace/context boundary. Session is one human/Jarvis conversation episode and may traverse several Boards. A (session_id, board_id) binding identifies the interactive Brain conversation for that Board in that Session. Jarvis Runtime is global and deterministic; there is no global LLM Brain.

V1 includes Board persistence, default-Board migration, Session tracking, Board switching/Voice binding, MCP parity, a simple top-right Boards selector, Board-scoped interaction mode, and Board-attributed global notifications. Galaxy navigation and deep semantic inter-Board querying are out of scope.
