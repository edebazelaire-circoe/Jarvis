# Independent critical boundary QA — Escape bridge

PM is independent of S03 implementer. Reviewed exact message parser, current-frame source/origin lookup and new focused-ready/generation/staged/rate guards, shim trusted/plain-key/init/teardown guards and local callback failure path. Existing five bridge scenarios cover spoof origin/source, extra fields/arbitrary keys, before-ready, unfocused/stale/paused/staged/unmounted frames, absent callback and visible/logged callback failure. Independent live Chromium proof is in pm-review.md (15 combined tests passed).

Ran qa/mutations.py with main venv Python in mov. It copies JavaScript into a unique temporary root, points the existing pytest fake-host seam to those copies via plugin and starts fresh Node processes. Repository product files are never edited. Unmutated copied baseline:5 passed in3.53s. Four targeted mutations all killed at intended assertions:
- focused-frame guard removed;
- non-Escape key guard removed;
- extra escape payload accepted;
- rate limit removed.

Raw results in mutation-results.json; all failing processes return1 with target AssertionError, no collection/syntax error counted as a kill. git diff --exit-code -- jarvis is clean. Initial harness invocation had an incorrect repository-parent index; corrected before baseline/mutation evidence, no product changes involved.

No blocking finding. Message is a UI close notice, not a new authority/control plane; no arbitrary keyboard/text payload, Core mutation or Fullscreen state write. PM disposition: S03 critical bridge + UI QA accepted. Remaining release polish is the selected-layout visual aid noted in pm-review; actual scene/content/action convergence remains S05/S06.

