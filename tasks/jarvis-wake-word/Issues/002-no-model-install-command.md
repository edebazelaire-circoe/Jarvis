# Issue 002 — Aucune commande produit pour installer les modèles openWakeWord

Non bloquante. Trouvée en Slice 08 en relisant le code livré contre la formule du handoff « installation à la demande ». Non corrigée (Slice documentaire : aucun changement de code produit).

## Symptôme

`jarvis/adapters/wakeword_model_catalog.py::ensure_models` télécharge et vérifie (taille, SHA-256) les trois modèles dans `runtime/wake-word/models/`, mais rien dans le produit ne l'appelle : ni Voice au démarrage, ni le Control Center (l'onglet Réglages › Mot d'éveil n'a pas de bouton d'installation), ni une sous-commande `python -m jarvis ...`. Le seul appelant hors tests est `scripts/measure_wakeword_inference.py --install`, un outil de mesure qui exige aussi l'extra `wakeword`.

## Effet

Un utilisateur qui coche « openWakeWord » sans installer les modèles obtient `wake_engine_unavailable` avec `cause_code=wake_model_missing` (dit proprement, F9 intacte). La procédure documentée dans `docs/OPERATIONS.md` (« Installer openWakeWord ») est une ligne Python, `python -c "from jarvis.adapters import wakeword_model_catalog as c; c.ensure_models()"`.

## Piste (non appliquée)

Une petite commande (par exemple `python -m jarvis wake-word install`) ou un bouton explicite dans l'onglet, sur action de l'utilisateur seulement (jamais au démarrage de Voice), qui appelle `ensure_models` et dit les codes `wake_model_*`.
