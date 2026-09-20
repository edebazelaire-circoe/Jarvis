# Les fins de sous-tâches d'agents enfants ne font pas parler JARVIS

- **Date** : 2026-09-18
- **Mode vocal** : `JARVIS_VOICE_ARCH=continuous_brain`

## Comportement constaté

L'utilisateur voit dans le Control Center qu'une tâche vient de se terminer — « Trace
reflex brain path », terminée après 4 min 6 s, avec un résumé substantiel. JARVIS, lui,
n'a rien dit. L'utilisateur a dû le signaler à l'oral :

> « Tu as une tâche qui s'est terminée, on a eu la notif, mais c'est là où il faut
> intervenir, c'est prendre la parole pour me dire que la tâche est terminée et s'il y a
> des choses à dire. »

## Comportement attendu

Une tâche ne doit jamais mourir en silence. Quand une fin de tâche est affichée à
l'utilisateur, JARVIS prend la parole pour la lui annoncer, même en veille — seul le
lancement d'une tâche reste muet. C'est une règle établie du projet (« les fins de tâche
doivent percer la veille »), déjà l'objet du retour
`retours-utilisateur/1789654261/2026-09-17-annonce-fin-de-tache-absente.md`.

## Contexte

« Trace reflex brain path » était un agent **enfant** : il a été lancé par un sous-agent
(« [code] Latence du cerveau et du réflexe »), pas par le cerveau. Séquence relevée dans
`runtime/trace.jsonl` de la session `eb620157` :

| Heure (UTC) | Événement |
| --- | --- |
| 21:35:38 | `task_started` — `Trace reflex brain path`, `spawn_depth: 2`, `is_backgrounded: true` |
| 21:39:44 | `agent.subagent.finished` — `depth: 2`, `parent_id: a528f4ccc401047c6`, `status: completed`, `duration_ms: 246246`, résumé long |
| 21:39:44 | `task_notification` — `status: completed`, résumé complet dans la charge utile |
| 21:42:27 | fin d'un second enfant, `Trace TTS and speech queue path`, `depth: 2`, même parent |
| 21:44:44 | fin du **parent**, `[code] Latence du cerveau et du réflexe`, `depth: 1`, `parent_id: null` |
| 21:45:02 | `agent.unsolicited_result` puis `core.brain.notice_relayed` — **première parole**, celle du parent |

Entre 21:39:44 et 21:45:02, aucun `agent.unsolicited_result`, aucun
`core.brain.notice_relayed`, aucun `core.brain.woken_by_work`. Le silence a donc duré
5 min 18 s, pendant que l'écran affichait deux tâches terminées.

## Pistes

### Cause confirmée

L'hypothèse de départ était : « le cerveau ne reçoit de notification que pour les
sous-agents qu'il a lancés lui-même ». Elle est **juste sur le fond, fausse sur le
mécanisme**. Il n'existe nulle part dans le dépôt de filtre `owner` / `launched_by` /
`parent` qui écarterait un enfant. Ce n'est pas un filtre, c'est une **absence de
chemin**, doublée d'une politique d'attention qui ignore le succès.

**Deux voies seulement mènent à la parole, et aucune ne couvre le cas.**

*Voie A — le relais spontané, la seule qui parle sur un succès.* Le CLI ouvre un tour
spontané (`type: result` porteur d'un `origin: {kind: "task-notification"}`), le cerveau
résume, et le texte est mis en file :
`jarvis/runtime/claude_local.py:1109` (`_resolve_pending` sur tout `result`) →
`claude_local.py:881` (`_resolve_correlated`) → `claude_local.py:905` (`_push_notice`) →
`GET /api/agent/notices` (`jarvis/runtime/control_center.py:3115`) →
`jarvis/core/v2_app.py:291` (`_brain_notice_loop`) →
`jarvis/core/brain_service.py:645` (`announce_notice`) → `SpeechRequest`.

Cette voie ne s'ouvre que pour un `result` **de premier niveau**. La fin d'un enfant est
rendue à **son parent sous-agent**, sous forme de `tool_result` dans le flux du parent ;
elle n'arrive à JARVIS que comme `system/subtype=task_notification`
(`jarvis/runtime/agent_tasks.py:457-464`), et ce type d'événement n'alimente que le
tracker, le journal, les pastilles et Core — **jamais la file `notices`**. Le test
`tests/unit/test_conversation_event_subagents.py:212-225` le montre en creux : un enfant
y termine par `notification(...)` seul, sans aucun `result` spontané. La documentation le
dit aussi, `docs/conversation-events.md:573-578` : *« sub-agents launched by spontaneous
turns (task-notification) or by panel/console messages are not recorded »*.

*Voie B — le réveil par attention, la seule qui parle sans relais.* Elle est agnostique
de la hiérarchie — un enfant qui **échoue** réveille bien le cerveau — mais elle exclut
le succès par construction, `jarvis/domain/brain_context.py:51` :

```python
ATTENTION_WORK_STATUSES = frozenset({WorkStatus.FAILED, WorkStatus.INTERRUPTED, WorkStatus.BLOCKED})
```

Un travail `COMPLETED` ne réveille donc **jamais** le cerveau, quelle que soit sa
profondeur.

**Bilan par cas :**

| Cas | Le cerveau parle ? | Par où |
| --- | --- | --- |
| Sous-agent direct, succès | Oui, si le CLI ouvre un tour spontané | Voie A |
| Sous-agent direct, échec / interrompu | Oui | Voie B |
| Agent enfant (`depth ≥ 2`), **succès** | **Non** | *aucun chemin* |
| Agent enfant, échec / interrompu | Oui | Voie B |

### L'asymétrie écran / parole

L'affichage emprunte trois voies, dont **aucune** ne touche la file `notices` :

- **cartes du panneau Agents** : `GET /api/work` (`jarvis/runtime/control_center.py:2594`)
  → instantané Core, projeté côté client avec `parent_id` et `depth`
  (`jarvis/runtime/control_center.html:1036`, `:1233`, `:1255` `treeOrder()`, `:1718`
  « Profondeur — niveau 2 ») ;
- **pastilles d'arrière-plan** : `jarvis/runtime/background_events.py:74-76`, qui classe
  tout `agent.subagent.finished` non échoué en `DONE`, sans regarder la profondeur ;
- **scène constellation** : étoile créée puis fermée, rattachée par un lien `parent_of`
  (`jarvis/core/scene_projector.py:1174`, `_link_parent` `:1197`) — quatre
  `core.scene.star_finished` sur la fenêtre observée.

`background_events.py:6-11` assume explicitement cette moitié : *« Le retour vocal est
traité ailleurs (`WorkAttentionPolicy` réveille le cerveau…). Ce module tient l'autre
moitié, celle qui n'interrompt pas. »* La profondeur est donc **produite**
(`agent_tasks.py:187`, `:493`, `:571`) et **affichée**, mais elle n'entre dans aucune
condition de `background_events.py`, `brain_context.py`, `brain_service.py`,
`work_ingress.py` ni `claude_local.py`. La hiérarchie est purement descriptive : l'écran
la connaît, la parole l'ignore.

### Pistes de correction (non implémentées)

1. **Ne plus afficher les enfants comme des tâches de premier plan.** Supprime
   l'asymétrie par le haut, mais au prix d'une perte d'information réelle : l'utilisateur
   suit aujourd'hui l'avancement de ces enfants, et `treeOrder()` les présente déjà
   correctement. Renoncer à les montrer pour ne pas avoir à en parler, c'est régler le
   symptôme à l'envers.
2. **Faire remonter chaque complétion d'enfant au cerveau.** Techniquement possible —
   ajouter `COMPLETED` à `ATTENTION_WORK_STATUSES`, ou router les `task_notification` de
   profondeur ≥ 2 vers la file `notices`. Mais cela ferait parler JARVIS trois fois dans
   l'exemple ci-dessus (deux enfants + le parent), dont deux fois sur des résultats
   intermédiaires que le parent allait de toute façon synthétiser. C'est le bavardage
   garanti, et `announce_notice` n'a aucun moyen de savoir que l'enfant est un détail du
   parent.
3. **Rattacher visuellement les enfants à leur parent, de sorte que seule la fin du
   parent s'annonce.**

**La troisième piste est la plus cohérente avec l'architecture existante**, pour trois
raisons.

D'abord, elle respecte la ligne de partage que le code a déjà tracée et documentée :
`background_events.py` tient « la moitié qui n'interrompt pas », le cerveau tient celle
qui parle. La voie A est explicitement conçue autour du **tour racine** — un enfant n'y a
pas sa place, et l'y forcer reviendrait à défaire l'invariant `belongs_to_brain()`
(`agent_tasks.py:388`), qui écarte déjà tout ce qui porte un `parent_tool_use_id` pour ne
pas noyer l'historique du cerveau. Le même raisonnement vaut pour la voix.

Ensuite, toute la matière nécessaire est **déjà là, et déjà correcte** : `depth`,
`parent_id` / `parent_external_id`, `treeOrder()`, le lien `parent_of` dans la scène. Il
ne manque qu'une chose : que l'enfant ne soit pas compté comme un événement de fond
autonome. Concrètement, un seul point de décision à toucher —
`background_events.py:_classify`, qui reçoit déjà `data["depth"]` et `data["parent_id"]`
dans la charge utile de `agent.subagent.finished` (`agent_tasks.py:811-822`) : un enfant
terminé **en succès** ne produit pas de pastille propre, il nourrit l'avancement de son
parent. Un enfant **en échec** doit continuer à se signaler, puisque la voie B le remonte
déjà et qu'un échec silencieux est précisément ce qu'on ne veut plus.

Enfin, elle rétablit l'invariant sans en inventer un nouveau : ce qui est montré comme une
fin de tâche est ce qui se dit. L'utilisateur garde la visibilité sur l'arbre — les
enfants restent lisibles, imbriqués, avec leur profondeur — mais il n'attend plus une
parole pour chaque nœud. Reste un point à trancher si cette piste est retenue : que faire
d'un enfant dont le parent meurt sans rien rendre. La voie B le couvre déjà (`FAILED` /
`INTERRUPTED` réveillent le cerveau quelle que soit la profondeur), donc le trou paraît
fermé, mais cela mérite d'être vérifié sur une trace réelle.

### À noter en passant

`_resolve_pending` est appelé sur **tout** événement `type == "result"`
(`claude_local.py:1109`), alors que le tracker s'en garde
(`agent_tasks.py:417-420` : `elif kind == "result": if not parent:`). Un `result` de
sous-agent — forme attestée par `tests/unit/test_agent_tasks.py:659` — n'a ni
`user_message_uuids` ni `origin`, donc `consumed_message_uuids` rend `None` et
l'attribution `claude_local.py:872-874` livrerait ce résultat au `ask()` vocal en vol.
Distinct du présent retour, à vérifier sur trace réelle.

Par ailleurs, `origin.kind` est rangé dans la charge utile (`claude_local.py:927`, `:944`)
mais n'est jamais relu : c'est le crochet naturel s'il fallait un jour discriminer par
lanceur.

Aucun code n'a été modifié : diagnostic uniquement.
