# Reconstructed source session


This is a faithful reconstruction of the decisions relevant to implementation, not a verbatim transcript.


The user initiated the audit because MCP capabilities were technically possible but sometimes ergonomically wrong. The motivating example was hiding a whole constellation: a human means one operation, not repeated star-by-star calls.


Audit conclusions carried forward:
- current MCP scene batches reduce model calls but remain best-effort per-object Core loops;
- constellation semantics differ between MCP and UI in runtime-signal ownership edge cases;
- UI can visually drag multi-selections while MCP lacks relative group translation;
- generic settings tools are already semantically dense and should stay generic;
- future Bare Hands and MCP should consume the same semantic action substrate.


The user explicitly agreed: « oui je suis totalement d'accord avec cela, c'est même l'intention de cet audit, d'implémenter ce genre de comportement : batcher les calls et obtenir une sémantique plus claire ».


Then the user requested this task and a clean human MCP inspector: an MCP button in the existing button list, readable descriptions, parameters with optional markers, compact and detailed modes, output schemas, and tabs such as General, Stars and Settings. Example names like `get_star()` or `change_audio_volume()` are semantic examples, not a mandate to explode the wire surface into micro-tools.