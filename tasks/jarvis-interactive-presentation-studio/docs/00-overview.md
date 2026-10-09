# 00 - Overview

## Objective

Turn presentations into a first-class Jarvis artifact with two equally important properties:

1. Jarvis can create a high-quality first version from project context with minimal unnecessary questioning.
2. The artifact remains deeply and quickly editable, rehearseable and presentable through Jarvis afterward.

## Mental model

```text
sources / brief / project context
            |
            v
Presentation Authoring Planner
 narrative + DA + score + scenes
            |
            v
Presentation Artifact
  |- active presentation variant
  |- art direction profile
  |- ordered scenes
  |- presentation score / cues
  |- project/resource references
  |- autosaved authoring state
            |
            +---------------------------+
            |                           |
            v                           v
   Semantic Edit API              Playback Runtime
 variable / structure / source    cue state + role + timing
            |                           |
            v                           v
 Scene/Prefab Foundation       PRESENTATION ambient lane
 HTML/CSS/JS instances         explicit address / TTS
            |                           |
            +-------------+-------------+
                          v
                     Tool/UI layer
                          |
                          v
              fullscreen presentation surface
```

## Primary workflows

### A. One-shot information presentation

Jarvis researches/collects information, chooses a coherent representation and presents it with a script/score. The user should not be forced into edit mode.

### B. Directed presentation creation

The user wants a serious deliverable. Jarvis inspects context, asks only high-value missing questions, proposes/infers DA and narrative, then creates a near-presentable first version. User and Jarvis refine it through voice and GUI editing, then rehearse.

### C. Exploratory creation

The user is intentionally unsure. Jarvis creates several divergent directions or variants to stimulate decisions, with lighter initial completeness.

### D. User presents, Jarvis follows

The user speaks. Jarvis matches only armed score cues, performs the associated reversible presentation actions, remains silent unless the score or explicit address calls for speech, and can resume after detours.

### E. Jarvis presents

Jarvis follows its prepared speech/visual score and may execute locked deterministic sequences for exact synchronization.

## Scope

In scope: presentation artifact model, scene modules and controls, fullscreen host capability, semantic edits, scene-local hot reload, autosave/undo, DA, score/cues, authoring workflow, playback roles, rehearsal, variants, comparison, selective composition, template promotion, agent/voice operations, UI surfaces specific to this feature.

## Non-goals

Do not duplicate the existing Presentation ambient/runtime contracts or Scene/Prefab foundation. Do not implement general video generation. Do not invent a new Board/Session/Context model. Do not retain an unbounded chronological version history.
