# Relations entre agents, tableaux de relation et relais

Page canonique des relations typées qu'un Mission Owner noue entre des instances d'agent, des messages
explicites qu'elles échangent et du paquet de relais. Elle décrit le contrat ; la persistance (Slice 03),
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

Au plus `MAX_PARTICIPANTS` (12) ; une instance n'apparaît qu'une fois. Les participants sont fixés à la
création : changer l'ensemble, c'est nouer une autre relation.

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
  `outcome_summary` (1 000 caractères), `winner_instance_id`.

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
`schedule`, `plan`, `workflow`) est refusée nommément (`relation_is_not_a_protocol`). Une relation se clôt à
tout moment, avec ou sans messages ; une Work Method peut recommander une pratique (par exemple travailler
d'abord indépendamment dans un Adversary), le Mission Owner décide.

## 3. Le tableau de relation et ses messages (D13)

Chaque relation a un **tableau** : le fil de ses messages, identifié par son `relation_id`. Ce n'est pas un
Board d'espace de travail ([boards.md](boards.md)) ; le mot « board » ne désigne ici que ce fil. La
communication n'existe que pour lui ; les autres natures peuvent s'en servir (critique d'une QA,
confrontation d'un Adversary, question d'un délégataire).

`RelationMessage` : `message_id`, `relation_id`, `author_instance_id`, `type`, `text` (4 000 caractères,
requis), `created_at`, `audience` (participants visés ; vide = tous ; jamais l'auteur), `artifact_refs`
(16 ids au plus).

Types (`RelationMessageType`) : `message`, `proposal`, `critique`, `question`, `decision`,
`result_summary`, `handoff_note` (ce dernier sur un relais seulement).

`check_message(relation, message)` : auteur et audience parmi les participants
(`relation_not_participant`), relation ouverte (`relation_closed`), message pas antérieur à la relation,
type permis (`relation_message_type_invalid`). Aucune règle d'ordre ni de nombre : l'ordre du fil est celui
de l'acceptation par le magasin (Slice 03/06), pas un numéro de tour.

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
relation (`handoff_mission_mismatch`) ; le successeur n'est pas plus ancien que son prédécesseur
(`handoff_successor_not_fresh`) ; le rôle peut changer. Sur un ensemble (`check_handoff_chain`) : une
instance ne reçoit qu'un relais (`handoff_successor_reused`) et les relais ne bouclent pas
(`handoff_cycle`) ; un relais `withdrawn` ne compte pas. Le prédécesseur peut finir ou rester disponible :
aucun arrêt forcé.

## 5. Frontière de confidentialité

Le contrat ne peut pas représenter un raisonnement privé (chain-of-thought), un prompt caché ni une charge
brute du fournisseur :

- **aucun champ** pour eux ; le décodage est strict (clé inconnue refusée) ;
- une **clé privée à toute profondeur** d'une charge reçue (`reasoning`, `thinking`, `chain_of_thought`,
  `system_prompt`, `tool_input`, `raw_arguments`, `api_key`…) est refusée nommément
  (`relation_private_content`) avec la même règle que Conversation Events
  (`conversation_events.is_forbidden_key`), message sans la valeur ;
- un **texte** (message, objet, paquet, résumé de clôture) qui porte une balise de raisonnement
  (`<thinking>`, `<reasoning>`, `<scratchpad>`…) est refusé (`relation_private_content`) ; un texte qui *est*
  un objet ou un tableau JSON (un événement brut recopié) aussi (`relation_raw_payload`) ; des octets bruts
  aussi. Une prose qui contient des crochets reste acceptée.

Ce contrôle du contenu est une défense en profondeur. La vraie frontière est la voie d'entrée : un message
n'entre sur un tableau que par un outil explicite qu'un agent appelle pour le publier (Slice 06), jamais par
une copie du flux du fournisseur (`agent.event`, blocs de réflexion).

## 6. Participants : jamais éphémères (D08)

`check_relation_participants(relation, instances, missions=None)` exige des participants connus
(`relation_participant_missing`) et **non éphémères** (`ephemeral_relation_participant`) : une relation
durable ferait d'une instance éphémère un nœud d'historique. Un travail qui mérite une relation n'est pas
éphémère. Délégation vers une sous-mission : le délégataire porte cette sous-mission et, si les missions
sont fournies, elle est fille de la mission de la relation (`delegation_sub_mission`) ; la mission de la
relation existe (`relation_mission_missing`).

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
`relation_not_participant`, `relation_message_type_invalid`, `handoff_packet_incomplete`,
`relation_participant_missing`, `ephemeral_relation_participant`, `qa_reviewer_role`,
`adversary_producer_is_reviewer`, `delegation_sub_mission`, `relation_mission_missing`,
`handoff_mission_mismatch`, `handoff_successor_not_fresh`, `handoff_successor_reused`, `handoff_cycle`.

## 9. Ce qui reste à câbler

| Sujet | Où |
| --- | --- |
| Tables durables des relations, messages et paquets (`jarvis.sqlite3` v10), ordre du fil | Slice 03 |
| Outils du Mission Owner qui nouent, alimentent et closent les relations | Slices 05 et 06 |
| Ajout de participants en cours de communication, s'il s'avère utile | Slice 06 |
| Projection dans la scène et styles de lien | Slice 08 |
| Graphe et ouverture du tableau depuis une relation | Slice 09 |
