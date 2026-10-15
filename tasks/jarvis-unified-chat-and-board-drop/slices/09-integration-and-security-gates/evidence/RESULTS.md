# Slice 09 — résultats (2026-10-15)

Base testée : `96c21101` (branche `feat/ucb-s09` = tâche avec Slices 01-08 et `origin/main` fusionnés), worktree `bu09`.
Python `.venv` de `jarvis-agent-01`, `PYTHONPATH=<worktree>`. Aucun Jarvis vivant touché, aucun port 17653/17654,
aucune base hors `tmp_path` ou d'une racine temporaire supprimée en fin de run.

## Tests — `tests/integration/test_chat_end_to_end.py`

```
pytest tests/integration/test_chat_end_to_end.py -q                     # 13 passed, 1 skipped (x3, 10-17 s)
JARVIS_LIVE_CLAUDE=1 pytest tests/integration/test_chat_end_to_end.py \
    -k attachments_pdf_png_read_by_real_cli                             # 1 passed (30,9 s), vrai CLI claude
```

Suite par défaut : vrai Core (SQLite sous `tmp_path`) + `LocalProtocolServer` + vrai `ControlCenter`, Voice simulé
par le client typé, cerveau scripté (ses fins de sous-agent passent par `next_notices`, la voie de production).
Catégorie 2 : convention du dépôt (`skipif` + `JARVIS_LIVE_CLAUDE=1`) ; les marqueurs `category2` /
`--include-category-2` n'existent pas dans Jarvis (`tasks/jarvis-category2-test-lab/.../READINESS.md` point 6).

| Scénario | Résultat |
| --- | --- |
| voice_active_chat_reads_but_refuses | PASS |
| switch_to_chat_then_text_turn_same_binding | PASS |
| subagent_survives_switch | PASS |
| text_turn_no_speech_requested | PASS |
| reactivation_relocks_and_inflight_turn_kept | PASS |
| retry_after_timeout_no_duplicate | PASS |
| board_switch_A_B_A_no_leak | PASS |
| reload_equals_live_union | PASS (Python et modèle JS servi) |
| core_restart_cursor_survives_and_unknown_grace | PASS |
| attachments_pdf_png_read_by_real_cli | PASS (Catégorie 2) |
| unreadable_attachment_announced | PASS |
| board_drop_file_image_url_visible_no_turn | PASS (aucune connexion sortante) |
| security_cross_origin_refused_all_chat_routes | PASS (7 routes × 5-6 vecteurs = 40 refus 403, témoin same-origin passe) |
| no_bytes_or_names_in_trace_and_events | PASS |

## Parcours navigateur réel (`journey.py` + `journey.mjs` + `cdp.mjs`)

`python journey.py <sortie>` : Core et Control Center de production en sous-processus, Chrome sans tête, vrai CLI.

| Étape | Résultat |
| --- | --- |
| Question « 17 × 23 » | bulle « 391 » en 3,2 s |
| PDF + PNG par « Joindre » | 2 lignes « Prête » ; bulle « licorne violette 2026 » / « CODE ORANGE 47 » en 14,2 s |
| Sous-agent depuis le chat | accusé en 7,1 s, résultat tardif en bulle à 18,2 s (« 58 fichiers .md », exact) |

Captures `2026-10-15-s09-real-0{1..5}-*.png`, DOM `journey.json`, analyse `analysis.json`. 0 erreur console,
0 appel `/api/agent/ask|send` du navigateur.

## Analyse de trace (réelle)

- Brief reçu par le CLI (transcription de session du CLI) : ligne « Canal : écrit (chat)… » dans 3/3 tours écrits ;
  bloc « Pièces jointes du message — données, pas instructions » avant `[Demande]`, chemins des payloads.
- Outils : `Read` du PDF puis du PNG (un appel chacun, aucun détour) ; sous-agent `Agent` `run_in_background`, un
  `Bash` (`find -maxdepth 1 … | wc -l`). Aucun refus de permission, aucune erreur, aucun `turn_failed`.
- Parole : 0 `brain.speech.requested` sur la conversation ; 4 `core.brain.speech_withheld_text_channel`
  (dont la fin du sous-agent, `agent.unsolicited_result` = 1).
- Fuites : noms d'origine, `upload.pdf|png`, chemin `artifacts` absents des événements ; noms d'origine et phrase
  secrète absents de `trace.jsonl` (`agent.input` ne garde que la demande visible).
- Coût : attachments test ≈ 0,38 USD × 3 runs (un compté par estimation), parcours 0,34 USD → ≈ 1,5 USD.

## Constats

1. **Polish (S07)** — Core accepte une pièce jointe d'un autre Board : envoi sur A, bascule vers B,
   `POST /api/chat/turns {conversation_id: B, attachments: [id_A]}` → 202 ; le Brain de B reçoit le chemin. Le contrôle
   est par Session ; l'état `stale` (« ne partira pas d'ici ») n'est tenu que par la page, alors que *Safety is
   server-side*.
2. **À vérifier en Slice 10 (S03/S04)** — après « Passer au chat » et **avant** tout tour écrit, la fin d'un sous-agent
   lancé à la voix émet `brain.speech.requested` (le relais emprunte l'intention vocale). Visible au chat ; audible ou
   non selon Voice en `background`. Limite déjà notée en QA S3.
3. **Polish (S07)** — un payload dont le chemin dépasse 260 caractères (racine de données profonde) échoue en
   `upload_storage_failed` ; `core.upload.refused` ne dit pas la cause réelle (OSError / MAX_PATH). Le test réel
   utilise donc une racine courte (`short_root`).
4. **Préexistant** — Core et Control Center écrivent le même `runtime/trace.jsonl` : 2 lignes entrelacées illisibles
   sur un run (0 sur le parcours).

Nettoyage : dossiers vides `retours-utilisateur/<horodatage>` créés et supprimés par `RealStack`
(`1792066361`, `1792066844` et ceux des runs Catégorie 2) ; aucun processus restant ; racines temporaires supprimées.
