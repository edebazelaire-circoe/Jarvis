# Slice 06 — Preuves (implémenteur)

## Smoke du vrai micro (2026-10-01)

But : vérifier D-CAP sur l'hôte réel — Core ouvre **son propre** flux
`sounddevice` par l'adaptateur de production (`AudioRecordingSources` →
`SoundDeviceInput` → `MicrophoneRecordingSource`), écrit le spool WAV par son
fil d'écriture et finalise par le vrai `CaptureService`.

- Harnais isolé : `scratchpad/s6/smoke_mic.py` (hors dépôt), racine de données
  temporaire `scratchpad/s6/smoke`, jamais la base vivante ni `~/.jarvis`.
- Appareil : entrée système par défaut (`Microphone Array (Realtek(R) Au…`),
  réglage `audio_input_device` absent du harnais (même chemin que Voice).
- Contexte : l'arbre Jarvis vivant de l'humain tournait sur l'hôte (Core
  127.77.0.1:17653, UI 127.0.0.1:17654) ; l'état de Voice n'a pas été inspecté.
- Durée : 3,0 s, puis arrêt explicite.

| Mesure | Valeur |
| --- | --- |
| Ouverture (création Artifact + ouverture appareil) | 1,87 s (échéance 15 s) |
| État capture / Artifact | `complete` / `complete`, `error_code` nul |
| Trous (`capture.gap`), débordements pilote | 0 / 0 |
| Fréquence retenue | 16 000 Hz mono PCM16 |
| Taille du fichier | 96 044 o = 44 (en-tête) + 96 000 |
| Taille RIFF / `data` déclarées | cohérentes avec la longueur réelle (vrai / vrai) |
| Trames, durée | 48 000, 3,000 s (`duration_ms` = 3000) |
| Échantillons non nuls | 39 532 / 48 000 (pièce calme, crête −57,1 dBFS) |
| Lecture par `wave` (stdlib) | valide |

Aucun contenu audio n'a été écouté, transcrit ni journalisé : seuls des
compteurs ont été imprimés. **Le fichier enregistré, sa base et tout le
dossier `scratchpad/s6/smoke` ont été supprimés** juste après la mesure
(`deleted=True`, contrôlé par `ls`). Aucun appel STT réel : le dépôt n'a aucun
fixture de parole synthétique utilisable hors ligne (le seul candidat serait
de l'audio de pièce, exclu par la règle de vie privée).

Conclusion D-CAP : tenu. PortAudio s'ouvre et tourne dans le processus de
Core sans instabilité observée ; le repli en processus enfant `jarvis capture`
n'est pas nécessaire.

## Tests automatisés (worktree `bsc`)

- Nouveaux : `tests/unit/test_audio_recording_source.py` (19),
  `tests/unit/test_recording_transcriber.py` (14) ; 5 passes répétées du
  second, stables ; aussi verts en `-X dev -W error` avec
  `test_capture_service.py` (65).
- Deux mutants manuels tués : remplissage de silence supprimé (2 tests
  rouges), adoption d'un segment rejoué supprimée (1 test rouge).
- Suites voisines : voir `LOG.md`, entrée Slice 06.
