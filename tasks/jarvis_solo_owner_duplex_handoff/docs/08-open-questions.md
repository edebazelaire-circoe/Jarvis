# 08 — Open Questions

These are intentionally not treated as locked implementation facts.

1. Which speaker-verification engine wins the local benchmark?
2. What owner threshold/evidence duration gives the best false-accept vs latency trade-off?
3. Is 2500 ms the best ring-buffer default on the target workstation, or should it be 1500/3000+ ms?
4. Should owner profiles be encrypted at rest and, if so, with which platform/key mechanism?
5. Should Solo Owner refuse activation when verification is unavailable, or allow an explicitly confirmed temporary fallback? Current recommendation: refuse and explain.
6. How should a future multi-user mode assign authority to other recognized speakers?
7. Which work-state changes should wake the brain proactively versus simply update Core/UI?
8. Which external/commercial speaker engine is worth integrating after evidence is collected?
