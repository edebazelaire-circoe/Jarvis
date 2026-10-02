# Le résumé du Context peut lister une demande de la salle comme « point ouvert »

- Trouvé : 2026-10-01, QA de la Slice 11 (lecture du `summary.md` produit pendant la matrice E2E
  avec un vrai modèle d'enrichissement).
- Gravité : observation, pas un défaut de sécurité. À reprendre lors d'un futur réglage de la
  consigne du résumé (`jarvis/domain/context_enrichment_prompt.py`, `SUMMARY_INSTRUCTIONS`).

## Constat

La matrice injecte dans l'audio une phrase de la salle qui ressemble à un ordre adressé à Jarvis.
Le worker d'enrichissement l'a reprise dans `summary.md` comme un **point ouvert** du travail.

Ce qui tient :

- la phrase y est formulée comme une information, jamais comme une consigne ;
- le cerveau ne l'a pas suivie : il la cite comme parole ambiante (EVIDENCE, scénario 7, T1) ;
- `summary.md` arrive au cerveau encadré comme information, pas comme instruction
  (`BRIEF_SUMMARY_FRAME`, lignes neutralisées, D17), et la règle de la parole ambiante reste
  valable.

Ce qui peut gêner : une demande dite dans la pièce, sans rapport avec le travail, encombre la
liste des points ouverts et peut être relue plus tard comme une tâche à faire.

## Piste

Préciser dans la consigne du résumé qu'une demande entendue dans la salle n'est un point ouvert
que si elle porte sur le travail du Context, et qu'elle reste attribuée à la salle (« demandé dans
la pièce »). Mesurer sur la même injection avant et après ; garder le test d'injection existant.
