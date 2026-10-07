# Implementation TODO

Start with Slice 00 and do not dispatch implementation before the Project Manager reaches READY.

Execution order:  
- 00-project-manager  
- 01-memory-contracts  
- 02-canonical-store-provenance  
- 03-hybrid-retriever  
- 04-consolidation-pipeline  
- 05-v2-brain-memory-integration  
- 06-tencent-memorycore-adapter  
- 07-wiki-knowledge-assets  
- 08-codegraph  
- 09-skills-loadouts  
- 10-memory-settings-backend  
- 11-memory-settings-ui  
- 12-memory-center-ux  
- 13-critical-user-agent-validation  
- 14-e2e-rollout-documentation

Parallelism is allowed only when dependencies permit it. Every implementation Slice receives qa-verification; code receives code-review; runtime/user-visible behavior receives runtime-validation; memory injection, agent loadouts and prompt/tool changes receive agent-trace-analysis.  
