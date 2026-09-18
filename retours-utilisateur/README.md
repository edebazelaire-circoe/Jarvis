# Retours utilisateur

Ce dossier consigne les dysfonctionnements constatés en usage réel de JARVIS
(sessions vocales, tâches de fond, etc.), par opposition aux défauts trouvés en test.

- Un dossier par session de JARVIS, nommé par l'heure de lancement du Control Center
  en secondes Unix (par exemple `1789654261` pour le 2026-09-17 à 16:11:01, heure de
  Paris). Les dossiers se trient donc dans l'ordre des sessions.
- Le Control Center crée ce dossier au démarrage et publie son chemin dans la
  variable d'environnement `JARVIS_FEEDBACK_DIR`, dont héritent le brain et ses
  sous-agents (`jarvis/runtime/feedback_sessions.py`).
- Dans le dossier de session : un fichier par retour, nommé `AAAA-MM-JJ-titre-court.md`.
- Chaque fiche indique : la date, le mode vocal (`JARVIS_VOICE_ARCH`), le comportement
  constaté, le comportement attendu, le contexte, puis une section « Pistes ».
- La section « Pistes » est complétée au fil du diagnostic ; les correctifs eux-mêmes
  sont documentés ailleurs (par exemple `docs/fixes/`).
