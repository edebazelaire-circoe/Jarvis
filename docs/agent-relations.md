# Relations entre agents, tableaux de relation et relais

Page canonique des relations typées qu'un Mission Owner noue entre des instances d'agent, des messages
explicites qu'elles échangent et du paquet de relais. Elle décrit le contrat ; la persistance
([mission-history.md](mission-history.md)),
les outils qui créent ces relations (Slices 05 et 06) et leur affichage (Slices 08 et 09) sont signalés là
où ils manquent encore.

| Contrat | Code | Tests |
| --- | --- | --- |
| Natures, relations, participants, clôture | `jarvis/domain/agent_relations.py` (`AgentRelation`) | `tests/unit/test_agent_relations.py` |
| Messages de relation | `RelationMessage`, `check_message` | idem |
| Paquet de relais | `HandoffPacket`, `check_handoff_chain` | idem |
| Frontière de confidentialité | `scan_private_keys`, `check_collaboration_text` | idem |

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
sont fixés à la création : changer l'ensemble, c'est nouer une autre relation. Si la Slice 06 prouve qu'il
faut faire entrer un membre dans une communication en cours, elle l'ajoutera comme une opération explicite et
datée (« join ») **en plus** de ce contrat, sans réécrire l'ensemble initial ni casser son décodage.

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
- qu'il ne porte pas déjà de travail ne se voit pas dans ce contrat (c'est Work State) : l'aide de relais de
  la Slice 06 garantit cette fraîcheur en créant le successeur pour le relais. Sans `relations`, un pair créé
  après le prédécesseur et déjà au travail n'est donc pas détecté ici.

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
n'entre sur un tableau que par un outil explicite qu'un agent appelle pour le publier (Slice 06), jamais par
une copie du flux du fournisseur (`agent.event`, blocs de réflexion).

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

## 9. Ce qui reste à câbler

| Sujet | Où |
| --- | --- |
| Tables durables des relations, messages et paquets (`jarvis.sqlite3` v10), ordre du fil : faits ([mission-history.md](mission-history.md)) | Slice 03 |
| Outils du Mission Owner qui nouent, alimentent et closent les relations | Slices 05 et 06 |
| Opération « join » d'une communication en cours, si elle s'avère utile (§1) | Slice 06 |
| Fraîcheur du successeur côté Work State (aucun travail porté), fil fourni à `check_message` | Slice 06 |
| Projection dans la scène et styles de lien | Slice 08 |
| Graphe et ouverture du tableau depuis une relation | Slice 09 |
