# Slice 10 — résultats (2026-10-16)

Worktree `bu10`, branche `feat/ucb-s10`, partie de `9e65c033` (branche de tâche, Slices 01 à 09 et reprise post-09).
Aucun Jarvis démarré, arrêté ni relancé ; aucune base hors de `tmp_path`.

## Recherche « second journal de chat »

Commande (racine du worktree) :

```bash
rg -n -i "chat[_ .-]?(log|history|transcript|journal)s?\b" --glob '!tasks/**' jarvis docs tests
rg -n -i "create table[^;]*chat|chat[^\"' ]*\.jsonl|chat[_-]?messages?\b.*(insert|write|append)" jarvis tests docs
```

Résultat : la première commande ne trouve que l'élément DOM `#chatLog` (liste `role="log"` du panneau,
`jarvis/runtime/control_center.html`, `control_center_chat.js`, et les tests navigateur qui le lisent) et la phrase
« No second chat log » de `docs/chat.md`. La seconde ne trouve rien : aucune table, aucun JSONL, aucun cache durable
de messages. Le seul stockage local du Chat est `localStorage` (`jarvis.chat.open`, `jarvis.chat.draft.<conversation_id>` :
brouillon non envoyé et pièces prêtes, pour la reprise après rechargement). Le Chat lit les événements de conversation
seuls. Schéma inchangé : `_SCHEMA_VERSION` 8 (`sqlite_state.py`) et 1 (`sqlite_scene.py`), `test_schema_migrations.py` 8 passés.

## Critère d'acceptation : tout se retrouve depuis `docs/chat.md`

- **Routes** : section *Routes* (9 routes du Control Center et de Core, avec leur relais et leur garde).
- **Codes d'erreur** : *Error codes*, une colonne *Test* par code.
- **Réglages** : *Configurable bounds* (`JARVIS_UPLOAD_MAX_BYTES`, `JARVIS_CHAT_MAX_ATTACHMENTS`, lecture, plafonds),
  lien vers `docs/OPERATIONS.md` › *Chat et dépôt sur le Board*.
- **Limites connues** 1 à 10 (8192 caractères, lien automatique au Board actif, accès `artifacts_root`, pas de message
  sans texte, pas d'objet de scène, journal d'outils du CLI, `artifacts_root` visible de la page, reprise manuelle,
  Board d'une pièce jointe, MAX_PATH), chacune avec sa ligne *Held by* ou « no test ».
- **Tests** : tableau des sections en tête, section *Conformance* (règle → test). Décompte (racine du worktree) :

  ```bash
  grep -oE '`[A-Za-z0-9_/.]*test_[A-Za-z0-9_]+\.py::test_[A-Za-z0-9_]+`' docs/chat.md | wc -l
  grep -oE '`[A-Za-z0-9_/.]*test_[A-Za-z0-9_]+\.py::test_[A-Za-z0-9_]+`' docs/chat.md \
    | sed -E 's#`##g; s#^tests/##; s#^unit/##' | sort -u | wc -l
  ```

  270 occurrences, 218 couples `fichier::test` distincts (préfixes `tests/` et `unit/` ramenés à un seul chemin).
  Chaque couple a été vérifié par script au HEAD (fichier présent, `def test_…` présent) : aucun manquant.
- **Sécurité** : `docs/SECURITY.md` contrôle 22 ; **architecture** : `docs/ARCHITECTURE.md` › *Text channel: the Chat,
  and the voice channel owned by Core* ; **données** : `docs/local-data.md` › *Fichiers des Artifacts*.
