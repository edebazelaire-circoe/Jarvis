# Testing and quality

## Global doctrine

Every implemented Slice receives `qa-verification`; code changes receive `code-review`; user-visible/runtime changes receive `runtime-validation`; agent/tool/prompt changes receive `agent-trace-analysis` with real trace evidence. Current-Slice regressions block acceptance.

Automated tests and runtime harnesses use isolated data roots/ports and must not start, stop or mutate the user's live Jarvis instance.

## Required regression baseline

Before implementation, record the current status of the recently merged Remotion/presentation suite, especially:

- current Variants continuous playback and transport;
- presenter run/score/cues;
- scene-level Remotion Studio open/publish round trip;
- scene source edits/rollback;
- scene render/export;
- native authoring preview/write loop;
- sandbox/guard/security tests;
- old presentation fixture byte-stability.

The final gate must rerun all directly touched areas plus the previous task's release-critical real-runtime tests that remain applicable.

## Planner unit matrix

At minimum:

1. homogeneous 3-scene variant -> ready, deterministic plan/key;
2. order change -> different key/master ordering;
3. exact pin version change -> different key;
4. title-only change -> behavior matches documented key contract;
5. non-Remotion scene -> typed incompatible;
6. unknown/tampered pin -> typed incompatible;
7. mixed FPS -> either proven mapping or typed incompatible according to Slice 02 contract;
8. mixed dimensions -> same;
9. same public path + identical bytes -> deterministic de-dup if contract chooses it;
10. same public path + different bytes -> typed collision, no rewrite;
11. relative source imports survive namespacing;
12. props/data for each scene are preserved and validated;
13. bounds: file count/source size/public size/project duration.

## Real Remotion project proof

Materialize a multi-scene project under an isolated runtime and prove:

- bundler/compiler succeeds with the pinned Remotion version;
- master composition is discoverable by Remotion;
- frame 0 is scene 1 frame 0;
- each boundary enters the next scene at local frame 0;
- final frame/duration matches the plan;
- no source byte or public asset from another pin is accidentally substituted;
- at least one scene uses audio and at least one uses video/media where the current security contract supports it.

## Studio proof

With the real managed `remotion studio` process where environment permits:

- one explicit user action opens the full variant master project;
- Studio exposes the master composition and all intended project sources;
- it is no longer described as "Studio open on scene N" for the primary master entrypoint;
- switching to another variant changes project identity deterministically;
- current scene-only Studio route still works or is explicitly retained behind its compatibility entrypoint;
- local-only network, clean env, process guard, ack and idle lifecycle remain green;
- master unpublished edits are never overwritten silently.

## Whole-video render proof

Render a frozen multi-scene variant through the actual guarded render host:

- one MP4 covers the master composition duration;
- dimensions/fps match the master contract;
- video verification passes existing ffprobe/header gates;
- audio stream exists when authored media includes audio; validate expected channel/sample properties using the existing media-tool approach;
- sample frames before/after every scene boundary show the expected scene order;
- no per-scene 8-second/score target truncates authored video duration;
- the result is one `presentation_video` Artifact linked to the snapshot;
- current explicit scene export remains unchanged.

## Voice/agent real trace

Required real-model or product-realistic trace:

1. addressed user asks for a short multi-scene Remotion video;
2. agent creates a master-compatible variant;
3. agent inspects/knows master readiness without inventing paths;
4. on explicit user request, whole-video export is requested and completed through the real tool path;
5. user asks by voice/text to change one scene/content/design detail;
6. agent edits through the existing source/version path;
7. master key/digest changes and a second full export reflects the edit;
8. agent never needs Remotion Studio and never claims it edited arbitrary master files;
9. no avoidable tool retry loop or scene-only export is mislabeled as the whole video.

## Negative controls

Plant failures deliberately:

- incompatible FPS/dimensions according to the chosen contract;
- asset collision;
- missing/tampered source;
- Studio Core outage;
- render browser unavailable;
- source edit during/after a master plan refresh;
- unpublished master Studio file before rebuild/switch.

Each must fail visibly without mutating canonical presentation/source data.

## Human validation

Human checks cover what automation cannot establish well: native Studio usability/meaning, perceived audiovisual result, and the spoken workflow. Before each Human check, attach the strongest machine evidence already available.
