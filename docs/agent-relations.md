# Relations entre agents, tableaux de relation et relais

Page canonique des relations typées qu'un Mission Owner noue entre des instances d'agent, des messages
explicites qu'elles échangent et du paquet de relais. Elle décrit le contrat (§1-§8) et son runtime (§10,
Slice 06 : outils des agents, autorité, relais en une transaction) ; la persistance est dans
[mission-history.md](mission-history.md), l'affichage (Slices 08 et 09) est signalé là où il manque encore.

| Contrat | Code | Tests |
| --- | --- | --- |
| Natures, relations, participants, clôture | `jarvis/domain/agent_relations.py` (`AgentRelation`) | `tests/unit/test_agent_relations.py` |
| Messages de relation | `RelationMessage`, `check_message` | idem |
| Paquet de relais | `HandoffPacket`, `check_handoff_chain` | idem |
| Frontière de confidentialité | `scan_private_keys`, `check_collaboration_text` | idem |
| Runtime : autorité, relais préparé, résumés, consignes (§10) | `jarvis/domain/relation_runtime.py` | `tests/unit/test_relations_runtime_hook.py` |
| Runtime : service Core, routes | `jarvis/core/mission_history.py`, `jarvis/protocol/mission_routes.py` | `tests/unit/test_relations_runtime_service.py` |
| Runtime : outils MCP, relais du Control Center, billets, hook | `jarvis/runtime/relations_mcp_tools.py`, `relation_relay.py`, `agent_handoffs.py`, `routing_hook.py` | `tests/unit/test_relations_runtime_relay.py`, `test_relations_runtime_hook.py` |

Les instances et missions que ces relations relient sont celles de [subagent-roles.md](subagent-roles.md)
(`missions.AgentInstance`, `missions.Mission`). Décisions produit : D09 à D15 du handoff
`tasks/jarvis-organic-agent-orchestration/docs/01-decisions.md`.

## 1. Cinq natures, des données explicites

`AgentRelationKind` est fermé : `delegation`, `communication`, `adversary`, `qa`, `handoff`. C'est la
**source canonique** du vocabulaire : `RELATION_KINDS` en est la forme texte, et
`work_methods.USEFUL_RELATION_KINDS` l'importe (une Work Method suggère ces natures, elle ne les redéfinit
pas). Une nature n'est jamais déduite d'un libellé, d'un texte de consigne ou d'un nom d'agent (D09) : elle
est déclarée par l'outil qui noue la relation.

Chaque participant tient une **position** (`ParticipantPosition`) qui dit la forme de la relation :

| Nature | Forme | Positions | Sens |
| --- | --- | --- | --- |
| `delegation` | dirigée | `delegator` -> `delegatee` | « tu prends ce travail borné (ou cette sous-mission) pour moi » |
| `communication` | entre pairs, 2 au moins | `member` | canal de coordination explicite |
| `adversary` | entre pairs, 2 au moins | `producer` | compétition symétrique : chacun produit et défend une approche (D10) |
| `qa` | dirigée | `reviewer` -> `reviewed` | revue critique du résultat d'un autre (D11) |
| `handoff` | dirigée | `predecessor` -> `successor` | la mission continue dans une instance neuve (D14) |

Au plus `MAX_PARTICIPANTS` (12) ; une instance n'apparaît qu'une fois. Dans ce contrat, les participants
sont fixés à la création : changer l'ensemble, c'est nouer une autre relation. La Slice 06 n'a **pas** ajouté
de « join » : le Mission Owner noue une nouvelle communication avec le nouvel ensemble (un appel), ce qui garde
chaque fil fermé à ceux qui y étaient. Une opération explicite et datée reste possible plus tard, **en plus** de
ce contrat, sans réécrire l'ensemble initial ni casser son décodage.

**Adversary n'est pas QA.** Adversary relie au moins deux producteurs pairs, tous en `producer`, sans
source ni cible (`endpoints()` vaut `None`) ; QA relie exactement un `reviewer` et un `reviewed`. Aucune
position n'est commune aux deux : une QA à trois, une QA entre producteurs ou un Adversary qui contient un
relecteur sont refusés (`relation_participants_invalid`). Avec les instances, un producteur qui a le rôle
QA est refusé (`adversary_producer_is_reviewer` : critiquer n'est pas concourir), et un relecteur sans rôle
QA aussi (`qa_reviewer_role`).

## 2. La relation

`AgentRelation` :

- `relation_id`, `kind`, `mission_id` (la mission dans laquelle le lien est noué), `participants`,
  `purpose` (300 caractères, requis), `created_at`, `created_by_instance_id` (l'instance qui l'a nouée,
  `None` pour le cerveau ou Core) ;
- champs propres à une nature, refusés ailleurs (`relation_field_not_for_kind`) :
  - `sub_mission_id` (délégation) : la sous-mission confiée, distincte de `mission_id` ;
  - `target_refs` (QA) : les artefacts ou résultats précis relus (ids, 16 au plus) ;
  - `handoff` (relais) : le `HandoffPacket`, **exigé dès la création** ;
- clôture : `status` `open` -> `closed` une seule fois (`close`), `closed_at`, `outcome`,
  `outcome_summary` (1 000 caractères), `winner_instance_id`, `closed_by_instance_id` (l'instance qui clôt,
  `None` pour le cerveau ou Core). `closed_by_instance_id` est **exigé** pour un verdict QA (`approved`,
  `findings`, `correction_requested`, `rejected`), et c'est alors le relecteur ; il est exigé aussi pour le
  choix d'un vainqueur (`winner`), où c'est l'instance qui a tranché, participante ou non
  (`relation_outcome_invalid`).

Issues permises (`OUTCOMES_BY_KIND`) ; `withdrawn` (retirée) vaut pour toutes :

| Nature | Issues |
| --- | --- |
| `delegation` | `returned` |
| `communication` | `ended` |
| `adversary` | `winner` (avec `winner_instance_id`, un des producteurs), `synthesis`, `unresolved`, `escalated` |
| `qa` | `approved`, `findings`, `correction_requested`, `rejected` |
| `handoff` | `transferred` |

Reclore à l'identique est sans effet ; reclore autrement lève `relation_closed`.

### Pas de protocole (D12)

Une relation a un sens, pas un déroulé. Aucun champ ne compte ni n'ordonne des tours ; une clé de protocole
reçue (`round`, `rounds`, `max_rounds`, `turns`, `phase`, `phases`, `protocol`, `steps`, `sequence`, `order`,
`schedule`, `plan`, `workflow`, `turn`, `iteration`, `iterations`, `max_iterations`, comparées sans
casse ni séparateur : `Round`, `maxTurns`, `max-iterations`) est refusée nommément (`relation_is_not_a_protocol`). Une relation se clôt à
tout moment, avec ou sans messages ; une Work Method peut recommander une pratique (par exemple travailler
d'abord indépendamment dans un Adversary), le Mission Owner décide.

## 3. Le tableau de relation et ses messages (D13)

Chaque relation a un **tableau** : le fil de ses messages, identifié par son `relation_id`. Ce n'est pas un
Board d'espace de travail ([boards.md](boards.md)) ; le mot « board » ne désigne ici que ce fil. La
communication n'existe que pour lui ; les autres natures peuvent s'en servir (critique d'une QA,
confrontation d'un Adversary, question d'un délégataire).

`RelationMessage` : `message_id`, `relation_id`, `author_instance_id`, `type`, `text` (4 000 caractères,
requis), `created_at`, `audience` (participants visés ; vide = tous ; jamais l'auteur), `artifact_refs`
(16 ids au plus), `reply_to_message_id` (facultatif : le message auquel il répond, jamais lui-même).

Types (`RelationMessageType`) : `message`, `proposal`, `critique`, `question`, `decision`,
`result_summary`, `handoff_note` (ce dernier sur un relais seulement).

`check_message(relation, message)` : auteur et audience parmi les participants
(`relation_not_participant`), relation ouverte (`relation_closed`), message pas antérieur à la relation,
type permis (`relation_message_type_invalid`). Avec le fil déjà accepté (`thread=`), une réponse vise un
message de la même relation qui ne lui est pas postérieur (`relation_reply_invalid`) ; sans le fil, la cible
n'est pas vérifiable et le magasin (Slice 03/06) fournit le fil. Aucune règle d'ordre ni de nombre : l'ordre
du fil est celui de l'acceptation par le magasin, pas un numéro de tour.

## 4. Le relais (D14)

Un changement de rôle, ou un contexte à rafraîchir, ne modifie jamais une instance : une **nouvelle
instance** reçoit la mission par une relation `handoff` qui porte son paquet. `missions.transfer_ownership`
prend l'id de cette relation comme `handoff_ref` quand la propriété de la mission passe au successeur.

`HandoffPacket`, complet par construction :

| Champ | Contrat |
| --- | --- |
| `objective`, `completed_work`, `recommended_next_action` | requis, 2 000 caractères chacun |
| `key_decisions`, `open_points` | 0 à 16 entrées uniques de 300 caractères ; peuvent être vides mais doivent être dites |
| `artifact_refs`, `evidence_refs` | 0 à 16 ids (artefacts, relation QA, mission, fichier) |

La mission, le prédécesseur et le successeur sont ceux de la relation : le paquet ne les recopie pas. Un
paquet décodé sans l'une de ses clés est refusé (`handoff_packet_incomplete`) : un paquet tronqué en transit
n'est pas un paquet vide, et un successeur ne peut pas se prévaloir d'un paquet incomplet.

Avec les instances (`check_relation_participants`) : prédécesseur et successeur sont de la mission de la
relation (`handoff_mission_mismatch`) ; le rôle peut changer. **Instance neuve** (`handoff_successor_not_fresh`) :

- le successeur n'est pas plus ancien que son prédécesseur ;
- avec `relations=` (les relations connues de la mission), il n'a pris part à **aucune** relation de la
  mission nouée avant ce relais ;
- qu'il ne porte pas déjà de travail ne se voit pas dans ce contrat (c'est Work State) : le runtime de la
  Slice 06 le garantit (§10.4) — le successeur est l'instance **créée par sa propre déclaration** `[relais]`,
  écrite dans la même transaction que le relais (`record_handoff` refuse une instance déjà retenue,
  `handoff_successor_not_fresh`). Sans `relations`, un pair créé après le prédécesseur et déjà au travail n'est
  donc pas détecté par ce seul contrat.

Sur un ensemble (`check_handoff_chain`), les relais forment des **chaînes** : une instance ne reçoit qu'un
relais (`handoff_successor_reused`), un prédécesseur ne transmet qu'une fois (`handoff_fan_out` : pas
d'éventail, la propriété ne se transfère pas deux fois) et les relais ne bouclent pas (`handoff_cycle`) ; un
relais `withdrawn` ne compte pas. Le prédécesseur peut finir ou rester disponible : aucun arrêt forcé.

## 5. Frontière de confidentialité

Le contrat ne peut pas représenter un raisonnement privé (chain-of-thought), un prompt caché ni une charge
brute du fournisseur :

- **aucun champ** pour eux ; le décodage est strict : une clé inconnue est refusée (`relation_invalid`,
  `field` = la clé), une clé de protocole aussi (§2) ;
- une **clé privée à toute profondeur** d'une charge reçue (`reasoning`, `thinking`, `chain_of_thought`,
  `system_prompt`, `tool_input`, `raw_arguments`, `api_key`…) est refusée nommément
  (`relation_private_content`) avec la même règle que Conversation Events
  (`conversation_events.is_forbidden_key`), message sans la valeur ;
- un **texte** (message, objet, paquet, résumé de clôture) est normalisé (NFKC pour la pleine chasse,
  caractères de largeur nulle et trait d'union conditionnel retirés, entités `&lt;`/`&gt;` décodées) puis
  refusé s'il porte une balise de raisonnement : `<think>`, `<thinking>`, `<reasoning>`, `<scratchpad>`,
  `<chain-of-thought>`, `<redacted_thinking>`, ouvrante ou fermante, éventuellement suffixée
  (`<thinking_process>`, `<reasoning_content>`). Un mot entre crochets (`[thinking]`) n'est pas une balise ;
- un **JSON cité** dans un texte (le texte entier, un bloc de code, une citation dans une phrase) est permis
  — `{"winner": "A", "score": 3}`, `["A","B"]` — mais ses clés passent le même contrôle : un fragment qui
  contient `thinking`, `reasoning` ou une autre clé interdite est refusé (`relation_private_content`). Un
  JSON trop imbriqué pour être vérifié (plus de 32 niveaux), ou des octets bruts, sont refusés
  (`relation_raw_payload`) ;
- **faux positif accepté** : une prose qui *cite* une balise (« la balise <thinking> des modèles ») est
  refusée. Les messages d'erreur disent à l'agent qui publie quoi corriger (publier le message explicite, pas
  son raisonnement ; nommer la balise sans chevrons ; retirer le champ privé du JSON), car la Slice 06 les
  lui renvoie tels quels. Une prose qui raconte un raisonnement sans balise (« Thinking: first… ») n'est pas
  détectable ici.

Ce contrôle du contenu est une défense en profondeur. La vraie frontière est la voie d'entrée : un message
n'entre sur un tableau que par un outil explicite qu'un agent appelle pour le publier (`relation_post`, §10),
jamais par une copie du flux du fournisseur (`agent.event`, blocs de réflexion). Le refus revient à l'agent qui
publie, avec ce qu'il doit corriger (`relation_runtime.actionable`).

## 6. Participants et périmètre de mission

`check_relation_participants(relation, instances, missions=None, relations=None)` :

- participants connus (`relation_participant_missing`) et **non éphémères**
  (`ephemeral_relation_participant`) : une relation durable ferait d'une instance éphémère un nœud
  d'historique (D08). Un travail qui mérite une relation n'est pas éphémère ;
- la mission de la relation existe, si les missions sont fournies (`relation_mission_missing`) ;
- **périmètre de mission** (`relation_mission_mismatch`), une instance sans mission n'y entre jamais :

| Nature | Règle |
| --- | --- |
| `communication`, `adversary` | chaque participant est de la mission ou d'une de ses sous-missions, à toute profondeur : des sous-missions sœurs peuvent être reliées |
| `qa` | l'instance relue est de la mission ou d'une sous-mission ; le relecteur n'est pas contraint |
| `delegation` | le délégant est de la mission ; sans `sub_mission_id`, le délégataire aussi ; avec, il porte cette sous-mission, fille de la mission (`delegation_sub_mission`) |
| `handoff` | prédécesseur et successeur de la mission (`handoff_mission_mismatch`) |

Une sous-mission ne se reconnaît qu'avec `missions` : sans elles, seule l'égalité est vérifiable et le
message d'erreur demande de les fournir.

## 7. Frontières avec l'existant

| Existant | Ce qu'il dit | Pourquoi ce n'est pas une relation typée |
| --- | --- | --- |
| `work_state.WorkLink` | rattache un travail observé au `work_id` du cerveau et au tour qui l'a demandé | un lien travail -> cerveau, pas entre instances ; vivant, en mémoire ; aucune nature |
| `WorkItem.parent_external_id` | parenté d'exécution observée | topologie d'exécution, pas une délégation déclarée ; une délégation peut la recouvrir sans s'en déduire |
| Scene `RelationKind` (`parent_of`, `explains`, `groups`) | liens **projetés** et dessinés, binaires, écrits par runtime/cerveau/utilisateur ([scene-model.md](scene-model.md)) | projection (D17) : la Slice 08 projette ces relations (un Adversary à N producteurs donne des liens par paire ou un groupe) sans faire de la scène leur source |
| Conversation Events `subagent.*` | spans diagnostiques de sous-agent, éphémères compris ([conversation-events.md](conversation-events.md)) | diagnostic d'une conversation, pas l'historique (D08, D25) ; n'alimente ni les relations ni le graphe. Des types d'événement d'audit de relation ne s'ajouteront que si la Slice 06 en a besoin |
| `artifact_relations` | provenance entre artefacts | relie des artefacts, pas des instances ; une relation y renvoie par `artifact_refs`/`target_refs` |
| Dossier de mission `mission.md` | prose partagée de la mission | contexte lisible ; le tableau de relation est un fil de messages bornés, pas un document |

## 8. Codes d'erreur

`RelationError` (sous-classe de `ValueError`) porte `code` et `field` :

`relation_invalid` (forme, borne, clé inconnue ou manquante), `relation_participants_invalid`,
`relation_participant_duplicate`, `relation_field_not_for_kind`, `relation_outcome_invalid`,
`relation_closed`, `relation_is_not_a_protocol`, `relation_private_content`, `relation_raw_payload`,
`relation_not_participant`, `relation_message_type_invalid`, `relation_reply_invalid`,
`handoff_packet_incomplete`, `relation_participant_missing`, `ephemeral_relation_participant`,
`qa_reviewer_role`, `adversary_producer_is_reviewer`, `delegation_sub_mission`, `relation_mission_missing`,
`relation_mission_mismatch`, `handoff_mission_mismatch`, `handoff_successor_not_fresh`,
`handoff_successor_reused`, `handoff_fan_out`, `handoff_cycle`.

`relation_raw_payload` ne couvre plus que les octets bruts et le JSON trop imbriqué pour être vérifié : un
JSON lisible n'est plus refusé en bloc.

Runtime (Slice 06, §10) : `relation_caller_unstamped`, `relation_caller_not_instance`, `relation_agent_unknown`,
`relation_agent_not_recorded`, `relation_not_owner`, `relation_no_mission`, `relation_kind_not_opened_by_agent`,
`relation_closed_by_core`, `relation_unknown`, `mission_closed`, `handoff_not_owner`, `handoff_unknown`,
`handoff_wrong_predecessor`, `handoff_expired`, `relation_read_not_allowed`, `handoff_ticket_missing` et `handoff_impossible` (hook).

## 9. Ce qui reste à câbler

| Sujet | Où |
| --- | --- |
| Tables durables des relations, messages et paquets (`jarvis.sqlite3` v10), ordre du fil : faits ([mission-history.md](mission-history.md)) | Slice 03 |
| Outils qui nouent, alimentent et closent les relations ; relais ; délégation alignée ; fraîcheur du successeur ; fil fourni à `check_message` | fait (Slice 06, §10) |
| Opération « join » d'une communication en cours | non ajoutée (§1) : une nouvelle communication la remplace |
| Enseigner au cerveau quand demander une QA, un Adversary, un relais à ses agents racines | Slice 07 |
| Projection dans la scène et styles de lien | Slice 08 |
| Graphe et ouverture du tableau depuis une relation | Slice 09 |

## 10. Runtime des relations (Slice 06)

### 10.1 Voie d'entrée : des outils explicites, l'identité apposée par le hook

Un agent noue, alimente, lit ou clôt une relation, ou passe la main, par cinq outils MCP du serveur
`jarvis-workspace` (`jarvis/runtime/relations_mcp_tools.py`) : `relation_open`, `relation_post`, `relation_read`,
`relation_close`, `relation_handoff`. Pourquoi cette voie :

- **un sous-agent hérite des serveurs MCP du cerveau** (constaté en Slice 05) ; `jarvis-workspace` est déclaré à
  chaque lancement, sans interrupteur. Le test de parité (`test_brain_capability_parity`) exige que chaque outil
  d'un serveur déclaré soit nommé dans la consigne du cerveau : une ligne de `BRAIN_WORKSPACE_PROMPT` (consigne du
  serveur, pas la consigne système) les nomme et dit que le cerveau ne fait que lire (`relation_read`).
  `BRAIN_SYSTEM_PROMPT` et `brain_rules()` ne changent pas : enseigner au cerveau quand s'en servir relève de la
  Slice 07 ;
- **l'appel est synchrone** : le refus codé de Core revient à l'agent qui publie, avec ce qu'il doit corriger. Un
  fait déposé par le hook (comme les déclarations) ne le pourrait pas ;
- **D25** : la sémantique vit dans les contrats de Core ; le hook n'appose qu'une **identité**. Pour chaque appel
  `mcp__jarvis-workspace__relation_*` (matcher du hook étendu et **ancré**, `routing_hook.HOOK_MATCHER` =
  `^(Agent|Task)$|^mcp__jarvis-workspace__relation_` : `TaskStop`, `TaskOutput`, `SendMessage`, `Glob` ne lancent
  pas le hook ; constaté sur le CLI 2.1.304), il écrit
  `jarvis_caller = {stamped, hook, agent_id, agent_type}` dans `updatedInput` (`hook` = `relation_runtime.STAMP_VERSION`,
  `relation-stamp@1`), depuis son événement (l'`agent_id` du CLI,
  `None` pour le cerveau), en **écrasant** toute valeur écrite par le modèle. Il reste court et hors ligne : ni
  disque ni réseau. Le champ n'est pas dans le schéma montré au modèle ; le serveur le retire avant le contrôle
  strict des arguments (`CURRENT_CALLER`). Sans lui, ou sans la version `hook` attendue (CLI lancé avec un ancien
  hook, champ écrit par le modèle), refus `relation_caller_unstamped` : rien n'est deviné. Le hook **échoue fermé**
  pour ces seuls outils : une panne (exception, import du hook cassé, `jarvis/runtime/hook_failsafe.py`) rend un
  refus explicite au lieu d'une sortie vide ; tout autre outil reste *fail-open*. Un hook tué par son délai ne
  pose rien : le serveur refuse alors l'appel. Constaté sur le CLI 2.1.304 (sonde du 2026-10-20) : l'`agent_id`
  du hook est le `task_id` de `task_started` et l'« agentId » que l'outil `Agent` rend à l'appelant ;
  `updatedInput` est honoré pour un outil MCP, même avec un champ hors schéma.

Le modèle de menace est en §10.7.

Chemin : outil MCP → Control Center `POST /api/missions/relations`, `.../{id}/messages`, `.../{id}/close`,
`GET /api/missions/relations/{id}`, `POST /api/missions/handoffs` (`relation_relay.py`) → Core
`/v1/missions/relations*`, `/v1/missions/handoffs` (`mission_routes.py`) → `MissionHistoryService`. Le Control
Center résout chaque agentId (et `self`) en identité de travail par le suivi des tâches
(`DeclarationRelay.task_for_agent`), remet d'abord les déclarations en attente (`settle`), et rend tel quel le
refus de Core. Core parle d'identités de travail, jamais d'agentId (D25).

### 10.2 Autorité (`relation_runtime`)

| Geste | Qui |
| --- | --- |
| nouer une communication ou un Adversary | le propriétaire courant de la mission de l'appelant, ou d'une mission ancêtre (D04) |
| nouer une QA | ce propriétaire, ou le relecteur lui-même (`reviewer = self`) : le Mission Owner décide en lançant un relecteur sur un travail nommé, le relecteur l'enregistre |
| publier, clore | un participant (`relation_not_participant` sinon), tant que la relation est ouverte. Mission close : pendant `CLOSED_MISSION_GRACE_S` (600 s) après la clôture, le geste est retenu et dit au journal (`relation_message_after_close` : un agent repris par `SendMessage` peut travailler après la clôture, constaté en bac à sable) ; ensuite refus `mission_closed`, et le balayage clôt `withdrawn` les relations encore ouvertes (`relation_withdrawn_after_close`, aucun verdict ni vainqueur inventé) |
| clore | verdict QA : le relecteur ; issue d'un Adversary : le propriétaire ou le créateur ; fin d'une communication : un membre aussi ; `withdrawn` : le créateur ou le propriétaire |
| délégation, relais | Core seulement (`relation_kind_not_opened_by_agent`, `relation_closed_by_core`) |
| lire | un participant, ou le Mission Owner courant de la mission ou d'une mission ancêtre ; le cerveau (et l'interface, sans lecteur) lit tout ; sinon refus `relation_read_not_allowed` (403) |

La relation est nouée dans la mission de l'appelant (`relation_no_mission` s'il n'en a pas). Les règles du
contrat (§1, §6) s'appliquent ensuite dans la transaction du magasin.

### 10.3 Sémantique au runtime, sans protocole

- **QA** (asymétrique, D11) : un relecteur de rôle `qa` relit le travail d'un autre ; il publie ses constats
  (`critique`) et rend un verdict (`approved`, `findings`, `correction_requested`, `rejected`). Le hook appose sur
  la consigne d'un relecteur le bloc `RELATION QA (JARVIS)` (`reviewer_brief`).
- **Adversary** (symétrique, D10) : au moins deux producteurs pairs, aucun relecteur ; ils publient leurs
  propositions et leurs critiques mutuelles ; le propriétaire tranche (`winner` + vainqueur, `synthesis`,
  `unresolved`, `escalated`).
- **Communication** (D13) : un fil de messages délibérés. `SendMessage` (CLI) reste le moyen de joindre un agent
  (amendement de readiness) ; le tableau garde ce qui a été dit.
- Aucun outil ne compte ni n'ordonne des tours ; une relation se clôt quand l'issue est connue, avec ou sans
  messages. Le Mission Owner reçoit le bloc `RELATIONS ENTRE AGENTS (JARVIS)` (`relations_brief`), apposé par le
  hook **après** la responsabilité de mission, en bloc distinct : quand chaque outil sert, jamais un ordre.

### 10.4 Relais : une instance neuve, un paquet complet, la propriété avant la fin

1. Le propriétaire courant appelle `relation_handoff` (objet + paquet complet). Core vérifie qu'il est le
   propriétaire courant d'une mission ouverte et qu'il n'a jamais passé la main (`handoff_not_owner`,
   `handoff_fan_out`, `mission_closed`, `handoff_packet_incomplete`), puis garde un **relais préparé**
   (`PendingHandoff`, mémoire de Core, 64 au plus, `HANDOFF_TTL_S` = 600 s). **Rien de durable** n'est écrit : un
   relais jamais lancé ne laisse aucune trace (D15). Le Control Center dépose un **billet**
   (`<runtime>/agent-handoffs/<handoff_id>.json`, `agent_handoffs.py`, 64 au plus). Un billet réclamé ou expiré est
   effacé (élagage à l'écriture, à la réclamation et par le relais du Control Center, démarrage compris) ; un
   marqueur de réclamation, après 1 h.
2. Il lance le successeur avec `[relais]` après son rôle (`[code] [coder] [relais] Suite`), modificateur
   d'orchestration de `agent_markers`. Un `[relais]` impossible à honorer — rôle sans `can_own_mission`,
   `[éphémère]`, `[mission]` en plus, appel du cerveau — est **refusé** avec la règle (`HANDOFF_IMPOSSIBLE_REASON`),
   avant toute réclamation : le billet attend l'appel corrigé ; `relation_handoff` le dit dès la préparation. Le hook
   **réclame** le billet de son appelant par la création exclusive d'un marqueur `<handoff_id>.claim`
   (`O_CREAT | O_EXCL`, une seule réclamation même sous Windows, où un renommage écrase sa cible), déclare
   le successeur Mission Owner de la mission reprise (`AgentDeclarationFact.handoff_id`) et appose le paquet sur
   sa consigne (`RELAIS DE MISSION (JARVIS)`). Sans billet : l'appel `Agent` est **refusé** avec ce qu'il faut
   faire.
3. À la déclaration du successeur, Core écrit **en une transaction** (`record_handoff`) : l'instance neuve, la
   relation `handoff` et son paquet, le transfert de propriété (`mission_owners`) et la clôture `transferred`.
   Tout ou rien : un successeur n'est jamais propriétaire sans paquet complet. Le successeur est l'instance créée
   par cette déclaration (fraîcheur garantie : `handoff_successor_not_fresh` si elle existait).
4. **Avant la fin du prédécesseur** : la déclaration part dès que la tâche du successeur a démarré ; et tant qu'un
   relais préparé attend, la clôture de la mission est différée (`mission_close_deferred` avec `handoff_id`), même
   si le prédécesseur finit le premier. Ensuite seule la fin du propriétaire courant compte (Slice 05).
5. Relais inconnu, expiré, d'une autre mission, d'un autre prédécesseur (le successeur doit être lancé par lui),
   ou refusé par le magasin : le successeur est quand même retenu (D18), **sans** la propriété (`mission_owner`
   faux), et c'est dit à l'erreur (`mission_history.handoff_failed`, code). Un relais préparé vit en mémoire de Core : un redémarrage
   de Core entre la préparation et le lancement le perd (même dégradation, dite).

### 10.5 Délégation alignée sur `[mission]`

Quand `[mission]` ouvre une sous-mission, Core noue avec elle la délégation `delegator` (l'instance appelante)
→ `delegatee` (le nouveau Mission Owner), `sub_mission_id`, id déterministe `rel_dlg_<sous-mission>` (un rejeu la
retrouve identique). Elle est close `returned` quand la sous-mission se clôt. Un échec est dit
(`mission_history.delegation_failed`) et ne refuse jamais la déclaration.

### 10.6 Ce que voit le cerveau, ce qui est journalisé

`BrainWorkEntry.relations` (quatre lignes au plus : nature, position, id, état — `relation_summary`), lues sans
E/S (`MissionHistoryService.relation_refs`, cache borné, réchauffé au balayage après un redémarrage) ;
`work_brief` les écrit « relations : … ». Jamais le texte d'un message. Journal de Core :
`mission_history.relation_opened|relation_message|relation_closed|relation_refused|handoff_prepared|`
`handoff_transferred|handoff_failed|delegation_failed` (ids, codes, tailles — jamais un texte) ; Control Center :
`missions.relation_relayed|relation_failed` ; hook : `agent.relation_call`, `agent.handoff.claimed|failed`.

### 10.7 Modèle de menace de l'identité apposée

Ce qui est défendu : **les erreurs du modèle et un hook absent ou ancien.** Un `jarvis_caller` écrit par le modèle
est écrasé par le hook ; sous un CLI sans le hook à jour, il n'a pas la version `relation-stamp@1` et le serveur le
refuse ; une panne du hook pendant un appel de relation rend un refus explicite. Core applique ensuite l'autorité
(§10.2) sur l'identité résolue : un agent ne publie que là où il participe, ne tranche que ce qu'il possède.

Ce qui ne l'est pas : **un agent malveillant sous le même utilisateur du système.** Un sous-agent a Bash : il peut
lire l'environnement et le dossier runtime, écrire un `jarvis_caller` à la bonne version, ou appeler directement les
routes du Control Center (`/api/missions/relations*`, en bouclage, sans jeton) en se faisant passer pour un autre
agentId. Aucun secret local ne résisterait à cet accès : la version n'est donc pas une signature, et aucune n'est
prétendue. La frontière reste celle de JARVIS en général (le poste et son utilisateur) ; le journal garde, pour
chaque geste, l'agentId apposé et l'identité résolue, de quoi reconstituer un abus après coup.

