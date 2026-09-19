# Bare Hands V1 — Overview

## Goal

Deliver a dependable webcam-only Bare Hands interaction subsystem for Jarvis Control Center/Constellation with modular tracking, gestures, manipulation and semantic target resolution.

## Scope

- standard webcam only;
- Jarvis UI only;
- MediaPipe Hand Landmarker remains the default tracker;
- two hands;
- OFF/SLEEP/ACTIVE lifecycle and C wake gesture;
- primary and secondary pinch;
- semantic DOM/component target resolver;
- optional pre-target feedback;
- frame edges/corners with one-hand move and two-hand constrained resize;
- independent simultaneous interactions on different objects;
- context-sensitive BODY interactions;
- Bare Hands Tools and Bare Hands Settings surfaces;
- explicit calibration overlay and separate tutorial overlay;
- derived-profile persistence and diagnostics hooks;
- tests and benchmark scaffolding.

## Non-goals

- system-wide app control;
- OCR/OmniParser/accessibility APIs for third-party apps;
- mandatory permanent cursor;
- Ultraleap/depth-camera implementation;
- custom fine-tuned image model;
- personalized neural gesture classifier;
- continuous auto-learning;
- copying upstream AGPL Barehands code into native Jarvis.

## Mental model

Webcam -> HandTracker -> HandTrackManager -> PointerFilter/Motion Features -> GestureEngine + PinchIntentEngine + TargetResolver -> InteractionEngine -> Jarvis Components, with CalibrationProfile feeding the pipeline.

The tracker estimates geometry. GestureEngine recognizes semantic hand states. PinchIntentEngine recognizes contact-like primary/secondary manipulation. TargetResolver knows what Jarvis objects/regions exist. InteractionEngine combines these streams into stable user actions.
