# La trace garde le texte de la salle quand le cerveau le lit ou le cite

- Trouvé : 2026-10-01, Slice 11 (vérification de confidentialité de la matrice E2E).
- Hors périmètre : le miroir `agent.event` de la conversation du cerveau dans
  `runtime/trace.jsonl` est antérieur à cette tâche ; il garde aussi les demandes et réponses
  ordinaires.

## Constat

- Les journaux de Core (`core.capture.*`, `core.transcript.*`, `core.artifact.*`,
  `core.context_enrichment.*`) ne portent aucun texte de la salle (vérifié sur la trace de la
  matrice : aucune phrase transcrite dans une ligne `core.*`). Les appels restreints du worker
  d'enrichissement sont retenus (`restricted_input_withheld`).
- En revanche, quand le cerveau lit une transcription (`transcript_read`) ou cite la salle dans
  sa réponse, le texte est dans `agent.event` (résultat d'outil, réponse) de `trace.jsonl`, comme
  toute réponse du cerveau, et dans le journal de session du CLI Claude
  (`~/.claude/projects/…`), qui garde aussi le bloc de rattrapage de chaque tour (queue de
  transcription ≤ 1 500 caractères, `summary.md`).
- Constaté : matrice Slice 11 (réponse T1 citant la salle), trace de la Slice 09
  (`transcript_read`).

## Suite proposée

Décider si la trace doit masquer les résultats de `transcript_read` / `artifact_get` (texte des
segments) comme elle masque déjà l'entrée des appels restreints, et documenter la rétention du
journal de session du CLI. Documenté pour l'opérateur dans `docs/session-context-capture.md`
(*Privacy*).
