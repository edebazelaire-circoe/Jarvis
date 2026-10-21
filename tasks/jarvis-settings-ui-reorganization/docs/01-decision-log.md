# Decision Log

1. **2026-10-20** - Settings are reorganized around user goals rather than implementation modules.
2. **2026-10-20** - Target top-level navigation is exactly six categories: `Voix & audio`, `Agents & modeles`, `Memoire & connaissances`, `Interface & interactions`, `Connexions`, `Avance & diagnostic`.
3. **2026-10-20** - `Mot d'eveil` becomes a section of Voice, not a top-level page.
4. **2026-10-20** - `Prompts` moves out of normal Settings into Advanced.
5. **2026-10-20** - `Agent / CLI` is split: user-facing agent/model behavior remains normal; CLI command/path/permission/runtime details move to Advanced.
6. **2026-10-20** - `API Keys` becomes `Connexions`, with provider-centric status and credential management.
7. **2026-10-20** - All keyboard shortcuts have one canonical editable home under Interface & interactions, including the wake/send/interrupt key currently edited from Voice.
8. **2026-10-20** - `Memoire` stays a first-class category and is renamed `Memoire & connaissances`.
9. **2026-10-20** - `Apparence` is folded into Interface & interactions.
10. **2026-10-20** - `Experimental` is dismantled: ordinary Bare Hands preferences/calibration move to Interface; diagnostics, benchmark, recording, scene test controls and developer tooling move to Advanced.
11. **2026-10-20** - Backend capability is preserved when it leaves the normal Settings surface.
12. **2026-10-20** - The Settings redesign uses a more spacious dark Jarvis shell; the current boxed dense modal is the before-state, not the target.
13. **2026-10-21** - The live `main` audit found a newly landed top-level `Sous-agents` page. It is absorbed into `Agents & modeles`; it does not change the six-category decision.
14. **2026-10-21** - Sub-agent role identity, mission/capability facts and ordinary role instructions belong with Agents & models. Work Method candidate promotion is treated as an advanced/operator action unless Slice 00 finds a stronger product contract.
15. **2026-10-21** - New Settings features must register sections into the canonical registry instead of mutating the top-level `TABS` array.
16. **2026-10-21** - The user requested that the task be reimplemented because the first publication was incomplete. This handoff supersedes the partial publication while retaining the same task identity.
