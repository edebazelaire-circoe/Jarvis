# MAINFIX du 30/09 — ce que la fusion `b8c3ba1` avait jeté, et comment c'est revenu

Branche `fix/main-merge-loss-2026-09-30`, sur `origin/main` (`96a9396`).
Même méthode que [`tasks/mainfix-2026-09/MAINFIX-LOG.md`](../mainfix-2026-09/MAINFIX-LOG.md).

## 1. Le symptôme

Sur `96a9396`, les unitaires donnent **6301 passés / 168 échecs / 122 erreurs** :
116 fichiers ne s'importent même pas. `jarvis/runtime/board_brains.py` importe
`READY_SETTLE_S` depuis `jarvis.runtime.claude_local`, qui ne le définit plus ;
les routes `/v1/boards*` et `/v1/sessions*` répondent 500
(`JarvisCoreApplication` n'a plus ni `boards` ni `sessions`).

## 2. Le fait mesuré

Pour chaque fusion, et pour chacun de ses deux côtés : les lignes ajoutées par
ce côté depuis la base commune (lignes non vides de plus de 3 caractères),
absentes du résultat de la fusion.

Fusions examinées : toutes celles atteignables depuis `96a9396` et pas depuis
la fusion `main` précédente (`76ee0fe`) — les trois de `main` (`1db9f40`,
`aeee8dd`, `b8c3ba1`) et les cinq fusions internes de la branche board-session.
Après `1db9f40`, l'historique premier-parent de `main` ne contient plus de fusion.

```
=== merge b8c3ba1 base 202333d parents ['739ba94', '0ff2a84']
  côté 739ba94 (board-session) : jarvis/adapters/control_center_brain.py : 100/108 absentes
  côté 739ba94 (board-session) : jarvis/core/brain_service.py            : 163/191 absentes
  côté 739ba94 (board-session) : jarvis/core/v2_app.py                   :  81/81  absentes
  côté 739ba94 (board-session) : jarvis/runtime/claude_local.py          :  96/107 absentes
  côté 739ba94 (board-session) : jarvis/runtime/speech_scheduler.py      :  56/68  absentes
  côté 0ff2a84 (voice-stale-speech) : (rien)
=== merge aeee8dd (origin/main dans tmp/merge-main) : (rien) des deux côtés
=== merge 1db9f40 (board-session dans tmp/merge-main) : (rien) des deux côtés
=== merge 045e8c8, 09f8ba7, f734c55, f324139, 0d5f1ba (internes à board-session) : (rien)
```

`b8c3ba1` — « Merge branch 'task/jarvis-voice-stale-speech-presentation' into
task/jarvis-board-session-context-runtime » — a pris ces cinq fichiers **en
entier** du côté voice-stale-speech : pour chacun, `git diff b8c3ba1 0ff2a84`
est vide. Ils n'ont plus bougé jusqu'à `96a9396`. Les **tests** des deux côtés,
eux, ont été gardés : la spécification était là, l'implémentation non. Tous
les autres fichiers de la fusion (les 27 de `git diff --stat b8c3ba1^1 b8c3ba1`,
dont `control_center.py`, `realtime_audio.py`, les `.js`) ont bien reçu les
deux côtés.

## 3. La restauration

Chaque fichier a été refusionné à trois voies (`git merge-file`, base `202333d`,
`739ba94` d'un côté, `0ff2a84` de l'autre), puis chaque conflit tranché à la
main en lisant les deux parents et leurs tests. Rien de voice-stale-speech n'a
été retiré.

### `claude_local.py` (1 conflit)

Revenu : `READY_SETTLE_S`, `_START_DIAGNOSTICS_MAX`, `wait_ready`, `stop(reason=...)`
(un arrêt demandé est journalisé en info), `_stop_request` / `_stream_ended`,
`speaks_notices`. Conflit : `publish_notice` garde le typage `NoticeTyping` de
voice-stale-speech et reprend `"spoken": self.speaks_notices` de board-session.

### `speech_scheduler.py` (1 conflit)

Revenu : `on_voice_binding_changed`, `_rebinding_to`, `_note_voice_binding`,
`drain`, `BOARD_REBIND_REQUESTED` / `BOARD_REBIND_DRAINED`, le routage de
`board.voice_binding.changed` avant le filtre de conversation. Conflit : la
signature du constructeur garde les deux jeux de paramètres (rebind + délais
live de voice-stale-speech).

### `brain_service.py` (8 conflits)

Revenu : `BRAIN_SPEECH_WITHHELD_KIND`, `_SpeechGate`, `speech_authority` /
`board_of` / `board_context`, `_speaking_conversation`, `_speech_gate`,
`_late_withheld`, `_trace_withheld`, `_inactive_board_notes`, `_turn_board`,
la retenue dans `select_outcome`, `announce_notice` et le réveil.

Les deux côtés avaient changé `_emit_speech` :

| | board-session | voice-stale-speech | retenu |
| --- | --- | --- | --- |
| retour | `bool` (False = retenue par la porte) | `_SpeechEmission(published, event_id, reason)` | `_SpeechEmission` ; retenue = raison `inactive_board` (`SPEECH_WITHHELD_INACTIVE_BOARD`) |
| paramètre | `origin` | `trace_kind` | les deux |
| suivi | `_spoken_works` | `_track_presentation` (Décision 48) | `_track_presentation`, **après** la seconde porte |
| question | point ouvert **après** la publication | avant | après (sinon une question retenue ouvrirait un point) |

Aucun `await` entre la seconde porte (`_late_withheld`) et `_publish` : c'est
l'invariant B1 de board-session, conservé.

`announce_notice` garde le typage des relais (voice-stale-speech) et re-passe
les deux portes avec `origin="notice"`.

**Où va un relais qui ne nomme pas sa conversation.** Le produit suit
board-session et `docs/boards.md` (« `announce_notice` targets the authority's
conversation (not the last turn received) », idem `wake_for_work_attention`) :
`_speaking_conversation()`, la liaison qui a la parole. C'est la seule
conversation que Voice écoute ; y déroger ferait, par exemple, réveiller le
cerveau sur une conversation hors Board quand un travail du Board actif échoue,
et l'échec ne serait jamais entendu.

Ce sont donc les tests de voice-stale-speech qui ont été réconciliés, comme
board-session l'avait fait pour les siens : ils démarrent un vrai Core, qui
ouvre désormais une Session, et faisaient leur tour dans une conversation créée
hors de tout Board (`core.conversations.create()`). Ils font maintenant ce tour
dans la conversation de la Session ouverte
(`(await core.sessions.current()).binding.conversation_id`) :
`test_brain_notice_contract.py` (3 tests) et
`test_spontaneous_notice_typing.py::test_core_emits_the_calibration_notices_typed`.
Seule la conversation utilisée change ; tout ce qu'ils affirment des relais
(genre, échéance, clé partagée, journal) est intact. (Une première version de
cette restauration avait ajouté au produit un `_relay_conversation()` pour
garder ces tests tels quels ; retiré à la revue.)

**Une seule alerte par relais retenu.** Un relais retenu par la seconde porte
était tracé deux fois (`speech_withheld_inactive_board` puis
`core.brain.notice_dropped`), la première porte une seule. `announce_notice`
n'émet plus `notice_dropped` quand la raison est `inactive_board`
(`test_a_notice_withheld_at_the_late_gate_raises_one_alert_not_two`, qui échoue
sans la correction).

### `control_center_brain.py` (3 conflits) et `v2_app.py` (5 conflits)

Revenu dans `v2_app` : `BoardService`, `SessionManager`, `SpeechAuthority`,
`board_host`, `BoardAttributingSink`, `board_of` de `JobService`, `active_board`
du contexte de travail, alignement de l'hôte au démarrage, arrêt des Boards.
Revenu dans `control_center_brain` : `ControlCenterBoardHost`, `post_activation`,
le refus `brain_not_foreground` (409), le bloc `board` du contexte du tour.

Les deux côtés avaient changé la forme d'un relais de `next_notices` :
board-session un `BrainNotice` (sous-classe de `str` portant `conversation_id`),
voice-stale-speech un mapping typé (`text`, `kind`, `supersedes_key`, `ttl_s`,
`work_id`). Retenu : le mapping typé, avec en plus la clé `conversation_id`
quand le Control Center la donne ; `_announce_one_notice` la transmet à
`announce_notice`. `BrainNotice` reste défini dans `jarvis/domain/v2.py`
(un test l'utilise encore pour appeler `announce_notice`) mais le backend ne le
produit plus.

## 4. Deux assertions arbitrées (commit séparé)

Même situation que la section 4 du précédent : chaque côté épinglait sa forme
de retour, les deux ne peuvent pas être vraies ensemble.

- `test_board_speech_authority.py::test_a_speech_deferred_for_capacity_is_not_reported_as_withheld` :
  `assert result is True` → `assert not result.published and result.reason == "semantic_chunk_capacity"`.
  L'invariant du test (un report de capacité n'est pas une retenue de la porte,
  aucune trace `speech_withheld`) est gardé.
- `test_board_brains_rework.py::test_b1_the_backend_reads_the_notice_conversation` :
  `notice == "Fini." and notice.conversation_id == "conv-a"` →
  `notice["text"] == "Fini." and notice["conversation_id"] == "conv-a"`, parce que
  `test_brain_delegation.py` exige des relais typés (mapping).

`test_v2_architecture.py::test_core_adapter_exceptions_stay_minimal` n'était
**pas** périmé : il échouait parce que `v2_app.py` n'importait plus
`sqlite_workspace_board`. Il passe avec le câblage restauré, sans retouche.

## 5. Validation

Unitaires en 12 morceaux de ≤ 30 fichiers (hôte à faible mémoire) :

| | passés | échecs | erreurs | ignorés |
| --- | ---: | ---: | ---: | ---: |
| `96a9396` (avant) | 6301 | 168 | 122 | 4 |
| cette branche, avant revue | 9622 | 13 | 0 | 5 |
| cette branche, après revue (§6 et §3 retouchés) | 9628 | 8 | 0 | 5 |

`tests/integration --collect-only` : 606 tests collectés, **aucune erreur de
collecte** (10 avant). `test_board_session_e2e.py` et
`test_brain_work_context_protocol.py` : 9 passés.

### Les 13 échecs restants, un par un

Vérifiés dans un worktree détaché (`C:/Projects/jarvis/bmf`, supprimé ensuite).

**8 préexistants avant `b8c3ba1`** — ils échouent à l'identique sur `0ff2a84`,
sur `739ba94` et sur la base `202333d` :

- `test_barehands_interaction_js.py` ×2 (`practice_frame_is_moved…`, `…resizes_only…`) ;
- `test_scene_group_drag_js.py` ×5 ;
- `test_brain_delegation.py::test_the_voice_agent_starts_with_the_rule_and_with_the_agent_tool_available`
  (le prompt réellement passé au CLI porte en plus `BRAIN_SETTINGS_PROMPT`).

**5 introduits par `96a9396`, masqués jusqu'ici par l'erreur d'import** —
`test_environment.py` ×5 (`test_loads_literal_credentials_and_windows_paths[utf-8]`,
`[utf-8-sig]`, `test_voice_cli_passes_dotenv_key_to_realtime_and_hides_it_in_ui`,
`test_voice_missing_key_explains_how_to_configure_it`,
`test_supervisor_loads_dotenv_before_spawning_children`). Ces tests vident
l'environnement ; `V2Settings.load()` passe désormais par
`jarvis/data_root.py::default_data_root`, qui appelle `Path.home()` →
`RuntimeError: Could not determine home directory`. Preuve : les cinq fichiers
restaurés posés sur `58eeb18` → 14/14 passés ; les mêmes posés sur `96a9396` →
5 échecs. Ce n'est pas une perte de fusion : laissé au porteur de `96a9396`.

## 6. Les 5 échecs de `test_environment.py` (introduits par `96a9396`)

Où est la faute : dans le **test**, pas dans le produit. Le seul appelant de
production de `resolve_data_root()` est `V2Settings.load()`, où `data_root` est
un champ réel des réglages (Core, Voice, superviseur) ; le chargement de `.env`
(`load_project_environment`) n'y touche pas, il n'y a donc pas de résolution
prématurée à rendre paresseuse. En revanche, la fixture autouse
`isolated_environment` remplaçait `os.environ` par `{}` : un environnement
qu'aucun processus Windows réel n'a (USERPROFILE y est toujours), où
`Path.home()` lève. Sans cette levée, le test aurait de plus résolu la racine
des données de l'utilisateur, ce que `CLAUDE.md` interdit (aucun test ne dépend
d'une base réelle).

Correction : la fixture garde un environnement vide **sauf**
`JARVIS_DATA_ROOT`, pointé dans `tmp_path`. Aucune assertion touchée.
`test_environment.py` + `test_data_root.py` : **21 passés**.

Il ne reste donc que les 8 échecs préexistants à `b8c3ba1` (section 5).

## 7. Après la revue — suites relancées

Unitaires complets, 12 morceaux au premier plan : **9628 passés, 8 échecs,
0 erreur, 5 ignorés**. Les 8 échecs sont les préexistants de la section 5
(`test_barehands_interaction_js` ×2, `test_scene_group_drag_js` ×5,
`test_brain_delegation::test_the_voice_agent_starts_with_the_rule…`). Écart avec
9622 : +5 (`test_environment`, §6), +1 (le nouveau test de l'alerte unique).

Intégration, suites Boards / Sessions / Voice / cerveau (20 fichiers) :
**69 passés, 5 ignorés** (opt-in : `JARVIS_LIVE_*`, `JARVIS_TESTLAB_REAL_SESSION`).
