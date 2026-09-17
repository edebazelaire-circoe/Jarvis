# Reconstructed planning session — Settings and model catalog UX

> Reconstructed faithfully from the current discussion; this is not a verbatim transcript.

The user rejected the current “Aiguillage” product surface and asked to remove it. The useful control should instead live in the agent/CLI configuration area: a compact Auto vs Dupliqué switch for how sub-agents are used, plus more technical customization options. Technical controls should come first; personality controls such as verbosity and politeness should follow. The user also asked for a real catalog of agents/models with sorting, filtering, price/capability information, usage tags and short recommendations, and a distinction between models currently loaded/usable and models that could be added. The same comparison concept should be reused for voice models.

The user finds the current voice model page overloaded and explicitly asked for a top navigation band of sub-tabs/categories. Repository inspection shows that live provider model discovery, CLI catalogs and routing are already implemented, and a recent commit added the “Aiguillage” UI. This task therefore preserves backend policy while replacing the product IA.
