# Slice 11 - Authoring Planner and First-Draft Quality

## Goal
Teach Jarvis to conceptualize a presentation before rendering and to choose the correct authoring workflow for one-shot, directed or exploratory requests.

## Context
The user wants high-quality one-shot output when enough context exists, but also wants Jarvis to generate inspiring alternatives when the brief is intentionally vague.

## Canonical Concepts
Authoring mode, discovery, narrative plan, DA plan, score plan, first-draft quality gate.

## Scope
### In Scope
- Detect one-shot information display vs directed presentation vs exploratory creation.
- Inspect available files/repos/data/resources before asking the user.
- Ask only high-leverage missing questions.
- Build narrative + DA + scene plan + score together.
- Generate a near-presentable first draft for directed work.
- Generate several intentionally divergent directions for exploratory work.
- Record source/resource provenance.

### Out of Scope
- New file search/repository connectors.
- Generic research agent architecture.

## Dependencies
- `09-art-direction-profile`
- `10-presentation-score-cues`
- `04-presentation-scene-control-contract`

## Implementation Steps
1. Add a planning policy/module or reusable skill only where repository conventions support it.
2. Reuse existing agent tools for project context discovery.
3. Define first-draft completeness checks: content, narrative, DA, scenes, score, cues, transitions/timing.
4. Add exploratory branching policy.
5. Ensure missing information causes targeted questions, not an automatic questionnaire.

## Files Likely Touched
Brain/agent presentation-authoring module or skill, prompts/contracts, tests.

## Architecture Constraints
Do not conflate "no explicit DA supplied" with "must block and ask for DA". Infer/generate when appropriate.

## Automated Validation
Agent trace scenarios for rich brief, missing context, linked DA source, vague exploratory prompt, one-shot report and serious final deliverable.

## Acceptance Criteria
Jarvis can produce a complete coherent first draft from a realistic brief without forcing an unnecessary edit/discovery loop.

## Documentation Updates
Authoring workflow and decision policy.

## Handoff Notes
Use `/caveman` and `/coding-guideline`; agent behavior requires real trace evidence.
