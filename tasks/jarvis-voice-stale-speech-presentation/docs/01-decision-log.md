# Journal des décisions

## 19/09/2026 — Décision utilisateur héritée (conservée dans son esprit)

« Une réponse sans retard faut qu'elle soit dite si c'est cohérent avec le
contexte. » Traduite à l'époque par : pas de péremption en bloc ; les paroles
durables d'une intention passée sont `carried_over` ; Core remet les réponses
non dites au cerveau (`pending_replies`, `supersede_stale_replies=False`).

## 28/09/2026 — Vérité ≠ présentation (amende la traduction du 19/09)

- La cohérence reste jugée **par le cerveau**, jamais par une règle d'âge.
- Mais une formulation rédigée pour une intention passée n'est plus
  prononçable d'elle-même : dès qu'une nouvelle intention s'impose, elle est
  **retenue** (état `held_for_brain`), puis soit réémise par le cerveau sous
  l'intention courante, soit retirée (`not_revalidated`).
- La vérité n'est jamais touchée : outcomes, faits publics, travaux,
  dépendances restent intacts. Seule la présentation change d'état.
- Recommandation d'agent 0, prise en autonomie ; **à confirmer par l'Humain au
  point HV de la Slice 04** (c'est la seule Slice qui modifie un comportement
  décidé par lui).

## 28/09/2026 — Remise au cerveau = retrait de la bouche

Remettre une réponse au cerveau et la laisser prononçable crée une course.
Règle : une parole est dans **exactement un** des deux mondes — soit
prononçable dans la bouche, soit en attente du jugement du cerveau. Une parole
remise au cerveau reste dans le contexte Core jusqu'à ce qu'un tour du cerveau
**réussisse** ; un tour échoué ou abandonné la repasse au tour suivant.

## 28/09/2026 — Intention courante d'abord

À la sélection, toute parole de l'intention courante passe avant toute parole
d'une intention antérieure, quelle que soit sa date de création. La priorité ne
départage qu'à l'intérieur d'une même intention (les ERROR/URGENT gardent leur
rang à l'intérieur de l'intention courante).

## 28/09/2026 — Fin de parole Live par preuve locale

Sur une surface sans fin de sortie, la fin d'une parole est constatée
localement : son audio a été observé, puis le périphérique s'est tu et est
resté silencieux pendant une marge bornée. `OUTPUT_TIMEOUT_S` redevient un
filet de sécurité dont chaque déclenchement est une anomalie tracée, jamais le
chemin nominal.

## 28/09/2026 — Relais spontanés typés

Tout relais passant par `announce_notice` déclare son genre. Un accusé
(« je les analyse ») est ACK/PROGRESS, transitoire, avec TTL et une
`supersedes_key` partagée avec la réponse qu'il annonce. Aucun relais sans
durée de vie ni clé.

## 28/09/2026 — Interruption unifiée

Toute prise de parole de l'utilisateur pendant que Jarvis parle ou réfléchit
signifie « l'utilisateur reprend l'autorité conversationnelle » : la file est
gelée jusqu'à la décision d'adressage du nouveau tour. Tour adressé → règles
de la Slice 04. Tour non adressé / bruit → la file reprend telle quelle. Seul
le tour **en réflexion** est en plus annulé côté Core (comportement actuel).
