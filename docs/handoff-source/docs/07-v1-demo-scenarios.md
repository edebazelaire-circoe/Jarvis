# 07 - V1 demo scenarios

## Scenario A - Normal voice turn

User holds PTT and says: `Jarvis, resume-moi le but de cette V1.`

Expected:

- listening state while held ;
- transcription state after release ;
- thinking state ;
- spoken answer ;
- visualizer pulses while speaking ;
- no sensitive content in default logs.

## Scenario B - Board presentation

User says: `Affiche trois objectifs de la V1 sur le board.`

Expected:

- agent emits a typed `board_present` tool call ;
- action is safe/no confirmation ;
- Barehands receives an authenticated command ;
- card appears ;
- user can move it with hand tracking.

## Scenario C - Memory write

User says: `Memorise que mon test Jarvis a fonctionne.`

Expected:

- agent proposes `memory_append` ;
- ActionBroker goes to awaiting_confirmation ;
- user approves through active PTT ;
- Markdown note is written ;
- index is refreshed ;
- confirmation is spoken.

## Scenario D - Restart persistence

Restart the process and ask: `Qu'est-ce que je t'ai demande de memoriser pendant le test ?`

Expected: information retrieved from memory backend, not conversation session.

## Scenario E - Component failure

Stop Barehands and ask a normal question.

Expected: voice loop still works. Asking to present on board yields a concise diagnostic rather than crashing the session.
