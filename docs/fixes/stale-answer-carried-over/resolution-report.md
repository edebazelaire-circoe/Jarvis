# La réponse à la première question mourait en silence — 2026-09-19

Symptôme signalé, deux fois dans la même journée
(`retours-utilisateur/1789824166/` puis `retours-utilisateur/1789828800/`) :
l'utilisateur pose une question, reparle avant la réponse, et la réponse à la
première question n'est jamais dite. Ses mots au second signalement : « c'est
pas possible que le brain envoie des données qui ne sont pas interprétées par
Jarvis derrière ».

Arbitrage tranché par l'utilisateur le 19/09 : « Une réponse sans retard faut
qu'elle soit dite si c'est cohérent avec le contexte […] il manque vachement de
gestion de contexte entre ce qui doit être dit, ce qui va être dit. […]
normalement le brain est censé être capable de faire cette distinction ».

## Constat

Deux règles mécaniques d'ancienneté, aux deux bouts de la chaîne, enterraient la
réponse sans que personne n'en juge le contenu.

1. `SpeechScheduler._eligibility` : si le couple `(intent_id, intent_epoch)`
   d'une parole n'était plus celui de la source courante, elle devenait
   `SUPERSEDED` pour les kinds transitoires et **`DEFERRED`** sinon, motif
   `stale_source`. `_deferred` n'est vidé que si cette intention-là redevient
   courante — or `intent_id == turn_id` (`jarvis/adapters/sqlite_state.py`) et
   l'époque ne recule jamais. Une intention ne revient pas : l'entrée était une
   tombe muette. Mesure sur `runtime/trace.jsonl` : **22 élocutions du cerveau
   ont connu `deferred / stale_source`, une seule a fini par être prononcée.**
   L'incident du 19/09 13:27:27 UTC s'y lit ligne à ligne (`age_ms: 3`).

2. `BrainOrchestrator._take_stale_replies` : à chaque nouvelle intention, Core
   invalidait **en bloc** la dépendance de toute parole déjà émise et pas encore
   dite (`JARVIS_SUPERSEDE_STALE_REPLIES`, défaut `1`). C'est un retrait sans
   désignation, que la Décision 35 interdit explicitement (« retirer du travail
   se fait par désignation, jamais en bloc »).

Le commentaire de `speech_scheduler.py:1068` promettait, depuis le 16/09, que
« le cerveau la redira sur l'intention courante depuis son contexte de travail ».
La fiche du 19/09 a montré que la promesse n'était pas tenue : la réponse à la
seconde question ne contenait pas ce qui avait été demandé dans la première.

## Correctif

- **La parole durable d'une intention passée est reportée, pas enterrée.** Un
  `result`, une `error` ou une `question` deviennent `ELIGIBLE` avec le motif
  `carried_over` : elles sont dites, après ce que l'intention courante a déjà en
  file. Une parole transitoire (`progress`, `ack`) reste `SUPERSEDED` : sa
  vérité s'évapore avec l'instant qu'elle décrit.
- **L'autorité vient de l'intention, pas de l'heure de rédaction**
  (`SpeechScheduler._may_supersede`) : une parole de l'intention courante
  remplace une parole reportée qui occupe le même emplacement (même
  `supersedes_key`, même `work_id`) ; jamais l'inverse — un retardataire
  n'efface pas le travail courant.
- **Core ne périme plus en bloc.** `_take_pending_replies` reprend les réponses
  encore muettes et les **remet au cerveau** comme contexte de son tour suivant
  (`BrainContext.pending_replies`, rendu dans le brief de l'agent par
  `render_pending_speech`). C'est la « gestion de contexte entre ce qui doit être
  dit et ce qui va être dit » : le cerveau ne les répète pas, et il peut les
  retirer.
- **Le retrait est nommé.** L'agent écrit `[[jarvis:retire <work_id>]]` seul sur
  une ligne ; le backend le retire du texte et émet
  `BrainEventKind.SUPERSEDED`, seule voie de retrait reconnue. Un identifiant
  que Core ne lui a pas remis est ignoré.
- **Rien ne meurt en silence.** Une parole durable retirée sans avoir été tentée
  émet `voice.speech.abandoned` en `warning`, avec son texte et la raison, et
  remonte en `attention` dans les événements de fond.
- `JARVIS_SUPERSEDE_STALE_REPLIES=1` rétablit l'ancienne règle telle quelle.

## Doctrine touchée

- `tasks/jarvis_voice_architectures_handoff/docs/01-decision-log.md`, Décision 08
  — amendée : la fraîcheur ne vaut que pour la parole transitoire.
- `docs/handoff-realtime-brain/docs/01-decision-log.md` — Décision 47 ajoutée.
- `docs/ARCHITECTURE.md`, section « Speech, interruption and work ».

## Preuve

- `tests/unit/test_speech_presentation_scheduler.py` : la réponse durable d'une
  intention passée est `carried_over` puis prononcée ; celle que le cerveau
  retire est soldée par `voice.speech.abandoned` en `warning`. Les deux
  échouaient avant le correctif.
- `tests/unit/test_brain_delegation.py` : bout à bout orchestrateur →
  ordonnanceur vocal, la réponse qui attendait derrière la phrase en cours est
  dite sans rien couper ; le cerveau la retire en la nommant.
- `tests/integration/test_voice_replay_regressions.py` : sur la trace réelle du
  tour lent de 85,7 s, la réponse du tour doublé est désormais prononcée.
- `tests/integration/test_live_two_questions_each_get_answered.py` : contre le
  vrai OpenAI Realtime et le vrai agent Claude, deux questions posées coup sur
  coup — la seconde partant pendant que le cerveau réfléchit encore à la
  première — obtiennent chacune leur réponse à voix haute.
