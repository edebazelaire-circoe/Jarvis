# I-003 — Réflexion du cerveau visible dans sa réponse ; tours lents quand `summary.md` est réécrit

Statut : **ouvert**, hors Slice 03 (consigné à la demande de l'agent 0, reprise QA S03). Non bloquant.

## 1. « 💭 … » dans le texte de réponse du cerveau
- Constat (trace de l'implémenteur S03, `scratchpad\v12s03\evidence\trace.jsonl`, 11:17:25) : le texte du tour du
  cerveau commence par « 💭 L'agent est lancé ; une phrase de lancement suffit. » puis la vraie réponse. La
  réflexion fuit dans ce qui est relayé (et serait lu à voix haute).
- Hypothèse non vérifiée : bloc de réflexion rendu en texte par le CLI ou par le modèle, et non filtré par
  l'extraction du texte de réponse (`ClaudeLocalAgent`, résultat du tour). À reproduire et à filtrer à la source,
  pas par un nettoyage du texte au hasard.

## 2. Tours lents quand le cerveau réécrit `summary.md` en plein tour
- Constat (QA S03) : `agent.turn_over_budget` (`brain_inline_work`) sur 4 tours sur 4 ; le cerveau fait
  `board_memory_read` puis `board_memory_write replace` de `summary.md` dans son tour (règle S02). Reprise S03 :
  même schéma (11:59:45-11:59:51, ToolSearch + read `memory_not_found` + create avant « D'accord. »).
- Pistes : n'écrire le condensé qu'en fin de tour ou en tâche éphémère, ou tolérer ce travail dans le budget du
  tour ; relève de la Slice 02 (continuité), à arbitrer par l'agent 0.

## Autre observation
- `agent.declared` est émis deux fois par lancement, la seconde ligne sans champs (QA S03). À examiner avec le
  relais des déclarations.
