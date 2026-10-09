# Target Architecture

Jarvis Brain -> Context Assembler -> Memory Retriever + Knowledge Loadout.

CanonicalMemoryStore owns durable human-readable memory. DerivedMemoryIndex owns lexical/vector indexes and may be discarded/rebuilt. MemoryConsolidator converts raw/session evidence into candidate atomic memories, scenarios and stable profiles under policy. KnowledgeAssets expose Wiki, CodeGraph and Skills. AgentMemoryPolicy selects private/shared scope and per-agent loadout. Optional TencentMemoryCoreAdapter mirrors/queries derived intelligence without becoming authority.

Recall must be bounded by count, token and time budgets. Stable context should be separated from turn-dynamic recall when practical for prompt caching. Every recalled item carries provenance and identity sufficient to inspect why it appeared.  
