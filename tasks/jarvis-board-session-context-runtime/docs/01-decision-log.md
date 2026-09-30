# 01 - Decision log

1. Session and Board are separate concepts.
2. Closed Sessions are immutable history.
3. New Session keeps Board/task state but creates a clean interactive conversation on the active Board.
4. One Session may traverse several Boards; returning to a Board in the same Session reuses that Board's conversation binding.
5. Voice connects directly to the active Board Brain; no global reasoning Brain.
6. Exactly one Board has speech authority.
7. Inactive Boards may remain background-running for unfinished work but cannot speak.
8. Existing alerts become global and Board-attributed.
9. Interaction mode is persisted per Board.
10. MCP parity is mandatory.
11. Galaxy/minimap UI is deferred.
12. Existing single-workspace state migrates into a default Board.
