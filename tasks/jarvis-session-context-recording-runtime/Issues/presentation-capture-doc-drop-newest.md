# La doc de capture PRESENTATION annonce une politique `DROP_NEWEST` qui n'existe pas

- Trouvé : 2026-10-01, audit à l'aveugle de la Slice 00.
- `docs/presentation-audio-capture.md:120` dit que `DROP_NEWEST` est disponible. Or `jarvis/audio/capture_hub.py:96-99` ne définit qu'une politique fixe, `BACKPRESSURE_POLICY = "drop_oldest"`.
- Hors périmètre : cette tâche ne modifie pas le hub ambiant (D12). La correction attendue est de supprimer la phrase de la doc, ou d'implémenter la politique.
