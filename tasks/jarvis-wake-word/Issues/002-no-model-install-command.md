# Issue 002 — Aucune commande produit pour installer les modèles openWakeWord

Non bloquante. Trouvée en Slice 08 en relisant le code livré contre la formule du handoff « installation à la demande ». Non corrigée (Slice documentaire : aucun changement de code produit).

## Symptôme

`jarvis/adapters/wakeword_model_catalog.py::ensure_models` télécharge et vérifie (taille, SHA-256) les trois modèles dans `runtime/wake-word/models/`, mais rien dans le produit ne l'appelle : ni Voice au démarrage, ni le Control Center (l'onglet Réglages › Mot d'éveil n'a pas de bouton d'installation), ni une sous-commande `python -m jarvis ...`. Le seul appelant hors tests est `scripts/measure_wakeword_inference.py --install`, un outil de mesure qui exige aussi l'extra `wakeword`.

## Effet

Un utilisateur qui coche « openWakeWord » sans installer les modèles obtient `wake_engine_unavailable` avec `cause_code=wake_model_missing` (dit proprement, F9 intacte). La procédure documentée dans `docs/OPERATIONS.md` (« Installer openWakeWord ») est une ligne Python, `python -c "from jarvis.adapters import wakeword_model_catalog as c; c.ensure_models()"`.

## Piste (non appliquée)

Une petite commande (par exemple `python -m jarvis wake-word install`) ou un bouton explicite dans l'onglet, sur action de l'utilisateur seulement (jamais au démarrage de Voice), qui appelle `ensure_models` et dit les codes `wake_model_*`.

## Résolution (Slice 09, 2026-10-08)

Résolue par une sous-commande explicite : `python -m jarvis wake-word install [--yes]` et `python -m jarvis wake-word status [--json]` (`jarvis/runtime/wake_word_install.py`). Elle annonce ce qu'elle télécharge (3 fichiers, 3 685 906 octets, URL amont, licence CC BY-NC-SA 4.0 à usage privé), demande confirmation sauf `--yes`, appelle `ensure_models`, est idempotente, n'écrit que sous `runtime/wake-word/models/` et dit chaque échec par son code `wake_model_*`. Voice ne télécharge toujours rien au démarrage ; l'écran des Réglages n'a pas de bouton (non demandé). Tests : `tests/unit/test_wake_word_install_command.py` (faux `urlopen`). Documentation : `docs/OPERATIONS.md`, « Installer openWakeWord ».
