# Le réflexe n'est pas coupé quand la réponse du cerveau arrive, et cette réponse est perdue

- **Date** : 2026-09-19
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain` (`voice.stack` : `openai_realtime`,
  voix `cedar`, `surface_reflex_only: true`, `analysis_model: null`)
- **Session** : `retours-utilisateur/1789824166`, Control Center lancé à 15:22:45
  (13:22:45 UTC). Trace : `runtime/trace.jsonl`, lignes 24772 → 26390.

## Comportement constaté

L'utilisateur signale le défaut à l'oral, pendant la session, à 13:28:36 UTC :

> « Alors euh ce que je disais c'est que il y a un gros problème, t'as t'as skip euh un
> des retours cerveau, la réponse réflexe euh n'a pas été interrompue par le message
> cerveau qui pourtant normalement a la priorité sur euh ce que tu racontes. »

Deux symptômes, tous deux reproduits dans la trace du tour de 13:27:12 :

1. Un retour du cerveau — 852 caractères, « J'ai relu l'écran. Il y a une vingtaine
   d'objets affichés… » — n'a **jamais été dit**. Il a été écarté 3 ms après sa naissance
   et n'est jamais entré dans la file de parole.
2. Le réflexe (la phrase d'attente) a joué **18 secondes en entier**, dont 9,9 s
   *après* que la réponse du cerveau était prête. Rien n'a tenté de l'arrêter.

## Comportement attendu

Quand le cerveau rend sa réponse alors que le réflexe est encore en train de parler, le
réflexe s'arrête net et la réponse du cerveau est lue à sa place, sans être perdue.

## Contexte

### La chronologie du tour fautif (UTC)

| Heure | Événement |
| --- | --- |
| 13:27:12.698 | `voice.transcript` — « OK est-ce que tu peux me faire un petit résumé d'où on est là, qu'est-ce qu'il y a d'afficher à l'écran ? » → intention **A**, `item_EPpNi6O9e4C8a2bkdcmRI` |
| 13:27:12.773 | `voice.reflex.decided` — `wait` / `user_speaking` |
| 13:27:17.524 | `voice.transcript` — « Et rappelle-moi un peu les tâches terminées récemment. » → intention **B**, `item_EPpNw0Bw7YBBMgocwzO1n` |
| 13:27:18.808 | `voice.reflex.started` — préambule, `output_id: e6d6b92f…`, motif `brain_silent_wait` |
| 13:27:20.302 | `voice.latency.first_audible_write` — `source: surface.reflex` → **le réflexe est audible** |
| 13:27:27.077 | le cerveau rend **A** (14,3 s) |
| 13:27:27.080-081 | `voice.speech.presentation_decided` × 3 — `status: deferred`, `reason: stale_source`, `age_ms: 3` (`d1358966…`, `12cdb6ee…`, `02ef94a2…`) |
| 13:27:27 → 13:27:36 | **aucun** `voice.speech.interrupted`, **aucun** `voice.reflex.decided`, **aucun** `audio.output_stopped` — le réflexe continue 9,9 s de plus |
| 13:27:36.554 | le cerveau rend **B** (19,0 s) → 3 morceaux `eligible` / `current_intent`, mis en file |
| 13:27:36.962 | `audio.drain_result` — `status: completed`, `written: confirmed` → le réflexe a été joué **en entier**, 18,0 s |
| 13:27:36.963 | `voice.turn_completed` — et **c'est seulement là** que B est `selected` / `priority_then_fifo` puis dispatché |
| 13:27:53.010-012 | « Stop, stop, stop. » → `core.brain.replies_superseded` + `voice.speech.superseded` × 3 sur les morceaux de A, `reason: dependency_revoked` → **A meurt sans avoir été dit** |

Le tour suivant confirme l'exaspération : trois `voice.barge_in_rejected` (13:27:43,
13:27:51, 13:27:53) avant qu'un `voice.barge_in` aboutisse enfin à 13:28:04, après
26,6 s de lecture. Puis « putain, ta gueule ! » à 13:28:06.

### L'hypothèse « version non rechargée » est fausse

C'était la première piste à écarter, et elle tombe :

- les trois processus tournent depuis **13:22:45 UTC** (`process.start` core/ui/voice,
  PID 4796 / 2172 / 16576, confirmés côté OS avec le même `StartTime`) ;
- le dernier commit de `main` est `e3bb546` du **19/09 12:56** ; les fichiers de la voix
  ont des dates de modification antérieures au démarrage
  (`speech_scheduler.py` 12:03:17, `realtime_audio.py` 12:03:17,
  `reflex_policy.py` 18/09 18:39) ;
- le seul travail non commité porte sur `control_center_scene_*.js` et deux tests de
  scène — rien de vocal.

Donc `54d0a3e` (« Barge-in : armer l'interruption aussi quand le cerveau réfléchit ») et
`555134e` (« Orbe : dériver la couleur de deux faits ») **sont en vigueur**. La trace le
montre d'ailleurs directement : les `voice.barge_in_pending` / `confirming` apparaissent
bien pendant que le cerveau réfléchit. Le symptôme observé n'est pas un reliquat de
version.

### Les deux « cerveau avant » : vérifié, et sans effet ici

Il y a bien deux choses distinctes :

- le **réflexe de surface** — la phrase d'attente — décidé par
  `jarvis/domain/reflex_policy.py:decide_reflex` et joué par
  `SpeechScheduler._maybe_speak_reflex` (`jarvis/runtime/speech_scheduler.py:1275`) via
  `session.speak_reflex` ; c'est le modèle Realtime lui-même qui la prononce, d'où
  `source: surface.reflex` et `speech_id: null` dans la trace ;
- le **front brain analyseur** — `jarvis/adapters/openai_front_brain.py`,
  `jarvis/domain/front_brain_hints.py`, `jarvis/runtime/front_brain_sidecar.py` — qui
  produit des *indices* de classement d'intention, jamais du texte parlé.

Dans cette session le second **n'était pas actif** (`analysis_model: null`,
`surface_reflex_only: true`). Le réflexe incriminé vient donc entièrement du premier.

## Pistes

### Symptôme 2 — cause établie : un réflexe audible n'est plus annulable

Le mécanisme d'interruption existe et il est bien armé. `SpeechScheduler._replan`
(`jarvis/runtime/speech_scheduler.py:1147`) appelle
`self._invalidate_reflex("useful_content_ready")` dès qu'une parole du cerveau devient
éligible. Mais `_invalidate_reflex` (`:492`) commence par :

```python
if reflex.admission is not None and not reflex.admission.invalidate():
    continue  # A native write already began; this is not proven unplayed.
```

et `OutputAdmission.invalidate()` (`jarvis/runtime/output_admission.py:33`) ne rend `True`
que si l'état est encore `RESERVED` :

```python
def invalidate(self) -> bool:
    with self._lock:
        if self._state is OutputAdmissionState.RESERVED:
            self._state = OutputAdmissionState.INVALIDATED
            return True
        return self._state is OutputAdmissionState.INVALIDATED
```

Dès le **premier octet PCM écrit** vers la carte son, l'état passe à `WRITE_STARTED`
puis `WRITTEN`. `invalidate()` rend alors `False`, la boucle fait `continue`, et
**aucune annulation n'est envoyée à la surface** : pas de `reflex.output_id` dans
`_reflex_cancelled`, pas d'appel à `session.invalidate_reflex`, pas même une trace
`voice.reflex.decided`. C'est exactement ce qu'on observe à 13:27:36 : le silence des
traces prouve le `continue`.

**La barrière d'admission a été conçue pour la comptabilité, pas pour l'arbitrage.** Son
commentaire le dit : *« write_started reserves an in-flight native write; it is not heard
evidence. A result arriving after that boundary cannot prove the output was unplayed. »*
Elle répond à la question « puis-je encore affirmer que ça n'a pas été entendu ? » — et
la réponse est non, légitimement. Mais `_invalidate_reflex` l'utilise pour répondre à une
tout autre question : « dois-je continuer à le faire parler ? ». Les deux ont été
confondues. Un réflexe déjà entendu **ne peut plus être effacé**, mais il peut
parfaitement **être coupé**.

Second verrou, indépendant du premier : la boucle de livraison attend le silence
*avant* de choisir (`_deliver_pending`, `:1263-1266`) —
`await self._wait_until_silent()` → `_wait_for_idle_output`, dont le docstring précise
« réflexe de surface compris ». Même si le réflexe restait annulable, la file ne
préempte pas : elle attend. Le seul point de préemption existant,
`_invalidate_presentation` (`:1149`), ne vise que les paroles du cerveau entre elles,
avec la même barrière d'admission.

**Et la non-préemption est écrite noir sur blanc**, dans la docstring de la classe
(`:183-190`) :

> « Il ne déclenche pas l'interruption : c'est le bridge qui possède le micro […].
> Une demande qui en périme une autre n'interrompt toujours rien : elle attend la fin de
> la phrase en cours. »

Il faut donc être net sur la prémisse du retour : **il n'existe pas aujourd'hui
d'arbitrage par priorité entre le réflexe et le cerveau.** `SpeechPriority` ne sert qu'au
tri (`_pop_next`, `:1248-1250`, `ordering_key = (-priority, created_at)`) ; `IMMEDIATE`
passe devant dans la file, mais ne coupe rien. Le champ `SpeechRequest.interruptible`
(`jarvis/domain/v2.py:467`) est déclaré, validé, sérialisé — et **lu par aucune
politique du dépôt**. La règle que l'utilisateur énonce (« le message cerveau a la
priorité sur ce que tu racontes ») est la bonne règle, mais elle n'est pas implémentée :
l'arbitrage réel est *temporel et exclusif* — le cerveau gagne toujours **s'il est prêt
avant que le réflexe ne commence**, et perd toujours ensuite.

**Mesure qui le prouve, et qui échoue sur le code actuel.** La sonde jointe
(`sonde-reflexe-audible-non-coupe.py`, à copier dans `tests/unit/`) est le miroir exact
de `tests/unit/test_reflex_gate.py:194`
(`test_a_preamble_is_cancelled_when_the_answer_arrives_before_it_plays`), mais après le
premier octet écrit :

```
>       assert output in selected._reflex_cancelled, "le reflexe audible n'a pas ete coupe"
E       AssertionError: le reflexe audible n'a pas ete coupe
E       assert '6685da1d-e5b7-4d2a-a89e-e3d8a07f437e' in set()
```

Le test existant ne couvrait que le cas « avant le premier son ». Le cas « pendant »
n'avait jamais été mesuré.

### Symptôme 1 — cause établie : l'intention A est périmée par l'intention B

Ce symptôme est **distinct** du premier, et ne vient pas du réflexe.

L'utilisateur a posé deux questions à 5 s d'intervalle (13:27:12 puis 13:27:17). La
seconde a fait avancer l'`intent_epoch` (106 → 107). Quand la réponse à A est arrivée
14 s plus tard, `_eligibility` (`:1041-1047`) a comparé
`(intent_id, intent_epoch)` à l'intention courante et rendu `stale_source` :

```python
if (request.source.intent_id, request.source.intent_epoch) != (self._current_source.intent_id, self._current_source.intent_epoch):
    ...
    status = SpeechCandidateStatus.SUPERSEDED if request.kind in TRANSIENT_KINDS else SpeechCandidateStatus.DEFERRED
    return status, "stale_source"
```

Un `result` n'étant pas transitoire, les trois morceaux de A sont partis dans
`_deferred` — c'est-à-dire en attente d'un retour de l'intention A, qui ne reviendra
jamais. Ils y sont restés 26 s, puis `core.brain.replies_superseded` les a révoqués.

Le même fichier documente déjà un cas identique, ligne 1068 : une parole d'erreur restée
`deferred` / `stale_source` le 16/09/2026 à 07:38:57, que personne n'a entendue. Le
commentaire y assume la décision — « son intention est passée, et le cerveau la redira
sur l'intention courante depuis son contexte de travail ». **Dans le cas présent cette
promesse n'a pas été tenue** : la réponse à B (« rappelle-moi les tâches terminées ») ne
contenait pas le résumé de l'écran demandé en A. Le contenu a bien été perdu.

### Les deux symptômes sont liés, mais pas comme on pourrait le croire

Le réflexe n'a pas *causé* la péremption de A : A était déjà `stale_source` à 13:27:27,
pour une raison qui ne doit rien à la bouche occupée. Mais le réflexe a rendu la perte
**irréversible** : pendant les 16,6 s où il était audible et inarrêtable, aucune parole,
même éligible, ne pouvait sortir. La fenêtre où A aurait pu être dite a été mangée par
du meublage.

Et c'est là que le dimensionnement compte : ces réflexes sont **longs**. 18,0 s au tour
fautif, 13,9 s à 13:29:43, 6 s à 13:28:38. Une phrase d'attente qui dure 18 secondes
n'est plus une phrase d'attente. Elle est presque toujours encore en train de parler
quand le cerveau rend sa réponse (budget cerveau dépassé à 14,3 s et 19,0 s ici), donc
elle tombe presque toujours dans le trou décrit ci-dessus. C'est ce qui fait passer un
défaut de bordure pour le comportement normal.

### Ce que je propose (non implémenté)

1. **Séparer « effacer » de « couper ».** Ajouter à `OutputAdmission` une opération qui
   arrête une sortie déjà commencée sans prétendre qu'elle n'a pas été entendue —
   l'équivalent de ce que fait déjà le barge-in humain, qui lui sait couper un flux
   `WRITTEN` (`voice.barge_in` à 13:28:04 avec `played_ms: 26618`). La capacité existe
   déjà et ne demande pas d'être écrite : `SoundDeviceRealtimeAudio.stop_output`
   (`jarvis/runtime/realtime_audio.py:1097` → `_abort_output` `:1131`) interrompt le flux
   PortAudio sans consulter l'admission. Il suffit que
   `_invalidate_reflex("useful_content_ready")` l'emprunte, au lieu de faire `continue`.
   C'est le correctif minimal, et il cible précisément les mots de l'utilisateur.
2. **Donner à la boucle de livraison un droit de préemption sur le réflexe.**
   `_wait_until_silent` doit distinguer « la bouche est prise par une parole du cerveau »
   (attendre) de « la bouche est prise par un réflexe » (couper). Sans cela, le point 1
   coupe le réflexe mais la file peut encore hésiter.
3. **Borner la durée du réflexe.** Un préambule doit être court par construction — une
   ou deux secondes. 18 s signifie que le modèle de surface improvise bien au-delà de
   l'accusé de réception. À traiter séparément, mais c'est l'amplificateur de tout le
   reste.
4. **Pour le symptôme 1 :** deux questions consécutives ne devraient pas s'annuler l'une
   l'autre. Soit `_defer` conserve un `result` périmé assez longtemps pour le dire après
   la réponse courante, soit le cerveau est informé que A n'a pas été dite et doit la
   reprendre. Aujourd'hui la trace émet `stale_source` en `info` : une réponse complète
   jetée mérite au minimum le même traitement que la parole d'erreur
   (`SPEECH_ERROR_WITHHELD`, en `warning`), sans quoi cela « passe pour un silence
   normal » — les mots du commentaire existant.

### Deux anomalies voisines, relevées au passage

- `speech_scheduler.py:1192-1193` : quand `len(self._seen_speech_ids) + len(spans) > 4096`,
  la parole est jetée par un `return` nu — **aucune trace, aucun événement**. C'est le seul
  point de rejet du fichier qui ne laisse rien derrière lui. Sans rapport avec l'incident
  du jour (9 identifiants dans la session), mais c'est un silence aveugle en réserve.
- Côté Core, `jarvis/core/brain_service.py:1846-1852` (`semantic_chunk_capacity`) et
  `:1838-1844` (`ambiguous_work_dependency`) retiennent l'*outcome* durable mais ne
  publient aucune parole : une réponse peut donc aussi se perdre en amont de
  l'ordonnanceur. Non observé aujourd'hui.

### Ce dont je doute

Le point 4 touche à une décision assumée du projet (une intention neuve périme la
précédente), pas à un bug. La corriger sans garde-fou ramènerait le bavardage que cette
règle évite. La question ouverte : **deux questions dans le même souffle sont-elles une
intention ou deux ?** Le code répond « deux » ; l'utilisateur, à l'oral, en attendait
visiblement une réponse pour chacune. C'est un arbitrage à trancher, pas à deviner.

Aucun code de production n'a été modifié : diagnostic uniquement.
