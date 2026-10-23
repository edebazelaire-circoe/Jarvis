# 07 - Reference Image Interpretation

## Reference 1 - `architecture-ui-reference.png`

### Keep

- Dark blurred Jarvis background.
- Neon blue/cyan/purple glass cards with restrained accent colors for brain identity.
- Large central 2D architecture workspace.
- Audio input/output shown as endpoints.
- Explicit arrows/labels rather than a decorative constellation.
- Distinct line styles and lock/toggle semantics.
- Brain-specific floating configuration panel over the graph.
- Compact supporting status/legend panels around the graph.

### Correct/override

- The final graph must be generated from actual runtime topology; positions and labels in the image are illustrative.
- Do not assume any pictured link is locked/editable until the runtime contract says so.
- Do not hard-code pictured model names.
- Do not add a separate Brain tab.

## Reference 2 - `subagents-ui-reference.png`

### Keep

- Same neon/glass visual family.
- Dense but readable role rows/cards with model/fallback/tool information.
- Clear role identity using accent/icon tokens.
- Global delegation/routing policy summary.
- Routing matrix/overview can be useful if it is a projection of the same policy.

### Correct/override

- Remove the `Brains` tab shown in the image; final page has only Architecture + Sous-agents.
- The five visible example roles are not the canonical role roster. Use all roles from `subagent_roles.py`.
- Model names and provider counts are placeholders.
- The pictured delegation-policy switches (intent analysis, load awareness, automatic fallback, result validation) and global rules (cost, timeout, knowledge access, collaboration) are visual/product candidates, not permission to fabricate settings. Surface only those backed by a canonical runtime setting; otherwise omit or keep them for a later task.
- Do not add generic creativity/personality controls from the mockup; those are out of scope.

## Global composition rules

- Overall page composition should feel squared-off and aligned even when internal cards have heterogeneous sizes.
- Use a consistent spacing/grid unit so floating panels do not create accidental edge misalignment.
- Neon/glow supports hierarchy; it must not reduce text/control readability.
- No quote/inspirational text blocks.
- If the new Settings shell has the circular profile avatar in the upper right, retain it consistently here.
