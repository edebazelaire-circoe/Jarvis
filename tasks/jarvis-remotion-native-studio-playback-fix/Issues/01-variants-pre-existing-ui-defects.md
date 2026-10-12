# Issue 01 — Variants UI defects found by Slice 10 QA, present before Slice 10

Found by the independent QA of Slice 10 (2026-10-12, on 2972e4be). Each one also shows on the
Slice 10 base (33015379) or is not attributable to Slice 10. Filed by agent 0; candidates for
Slice 15 (cleanup) or Slice 16 (release sweep).

| # | Defect | Evidence | Where to look |
| --- | --- | --- | --- |
| I2 | During a run, the composition slider shows no thumb or fill (e.g. at 0:02 / 1:14). | Visible in the Slice 10 « before » run screenshot too. | run-mode slider, `control_center_presentation_studio_explorer.js` |
| I3 | Tab never reaches the header's « Plein écran » / « Fermer »: from « Archiver » focus goes to the page body, then back to the tree. | QA Tab-order probe at 800x600, 1280x720, 1920x1080. | `onDocKey` in the explorer (unchanged by Slice 10) |
| I4 | `test_variants_media_fullscreen_browser.py` failed once in a full-file run, then passed alone and 7/7 on a full rerun. | QA run on 2972e4be; failing check not identified. | letterbox check of the media fullscreen browser test |

I1 of the same QA (the « ⋯ » menu invisible in stage fullscreen) was fixed with the Slice 10
rework (4ce22d1e), because it shares the cause of the blocking finding B1.

## Added after the Slice 11 QA (2026-10-12, on 8573e6f5)

| # | Defect | Evidence | Where to look |
| --- | --- | --- | --- |
| I4 (again) | `test_variants_media_fullscreen_browser.py` flaky under load: 6/7 then 5/7 at HEAD (one 120 s `variants_ready` timeout, one `audio and image within 200 ms`); the audio/image test alone 3/4. Host had < 1 GB free RAM with two agents. | Slice 11 QA; comparison at 873e0cc0 inconclusive (ran past 590 s). | media fullscreen browser test timing bounds |
| I5 | For a scene the user wrote, the shared `confirmSpec` puts focus on the confirm button: a held or repeated Enter on the « Remotion Studio » door can confirm at once. Same behaviour as the MCP card. | Slice 11 QA code reading. | `JarvisRemotionStudioCore.confirmSpec` default focus |