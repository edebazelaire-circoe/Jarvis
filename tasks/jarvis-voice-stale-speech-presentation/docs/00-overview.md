# Vue d'ensemble

## Symptôme rapporté (28/09/2026)

« La conversation galère. Jarvis a toujours un métro de retard… il galère
vachement avec de la donnée périmée », en particulier pendant la calibration
Bare Hands, quand l'utilisateur coupe ou relance.

Scène type de la transcription (horodatages de l'utilisateur) :

| Instant | Utilisateur | Brain | Bouche |
|---|---|---|---|
| 12:58:09 | — | rédige A « D'accord, aucun de mes réglages… On passe cette étape ? » | occupée (parole de 12:57:29) |
| 12:58:32 | « t'as rien relancé » (tour N) | — | occupée |
| 12:58:37 | — | rédige B' « Pardon, c'est relancé… » (tour N, correct) | occupée |
| 12:58:38 | — | — | **dit A** (tour N‑1) |

## Chaîne causale vérifiée

1. La bouche Live reste « occupée » 30 s par parole (pas de fin de sortie) →
   une file se forme.
2. Quand elle se libère, la sélection sert la parole éligible **la plus
   ancienne** à priorité égale → A avant B'.
3. A est éligible parce qu'une parole durable d'une intention passée est
   `carried_over`.
4. Core a remis A au cerveau (`pending_replies`) mais ne l'a pas retirée de la
   bouche → le cerveau et la bouche se contredisent.
5. Les relais spontanés (accusés et analyses de calibration) n'ont ni
   `work_id`, ni TTL, ni clé de supersession : ils échappent à tout ce qui
   précède et ressortent à retardement (« cimetière » expiré en masse au
   passage en arrière-plan).

## Résultat visé

- Une phrase Live courte libère la bouche en ≈ sa durée audio + une petite
  marge, jamais au bout de 30 s.
- Après une prise de parole de l'utilisateur, **aucune** formulation rédigée
  avant elle ne démarre sans avoir été réémise par le cerveau pour l'intention
  courante.
- Les accusés et progressions sont transitoires, remplacés par ce qu'ils
  annoncent.
- Interrompre Jarvis pendant qu'il parle a le même effet sur la file que
  l'interrompre pendant qu'il réfléchit (sans purger le travail).
