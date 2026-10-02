# Slice 07 — Preuves (implémenteur)

Toutes les mesures du 2026-10-01 sur l'hôte de développement. Aucune image ni
vidéo n'est jointe : chaque fichier capturé (le bureau pouvait montrer du
contenu privé de l'humain) a été supprimé juste après la mesure, et aucun
contenu d'image n'a été affiché ni transmis. Harnais hors dépôt
(`scratchpad/s7/*.py`), racines de données temporaires `scratchpad/s7/smoke*`
(supprimées), jamais `~/.jarvis` ni la base vivante. Dépendances d'essai dans
un venv à part (`scratchpad/s7/venv` : `mss` 10.2.0, `imageio-ffmpeg` 0.6.0) ;
le venv partagé n'a reçu aucun paquet. Le Core d'essai lisait ffmpeg par
`JARVIS_FFMPEG_EXE`.

## Audit de l'hôte

| Fait | Valeur |
| --- | --- |
| OS | Windows 11 Pro 10.0.26200, 20 CPU logiques |
| Écrans | `\\.\DISPLAY1` principal 1920×1080 en (0,0), 120 dpi (125 %) ; `\\.\DISPLAY5` 1920×1080 en (1920,0), 96 dpi |
| Vu sans conscience DPI (Core) | principal 1536×864 — d'où la bascule DPI par fil |
| ffmpeg de `imageio-ffmpeg` | 7.1 gyan.dev *essentials*, `--enable-gpl --enable-version3`, libx264/libx265/h264_mf/nvenc/qsv/amf, `gdigrab`, `ddagrab` |
| `mss` 10.2 | appelle `SetProcessDpiAwareness(2)` (effet sur tout le processus) : écarté |

## Choix d'encodage (enregistrements de 5 à 10 s, fichiers supprimés)

| Variante (écran principal, 5 i/s sauf mention) | CPU ffmpeg (un cœur) | Taille |
| --- | --- | --- |
| gdigrab + x264 ultrafast CRF 30 | 20,9 % | 1,7 Mo/min |
| gdigrab + x264 veryfast CRF 30 | 24,1 % | 0,6 Mo/min |
| gdigrab + x264 ultrafast, 10 i/s | 40,3 % | 4,5 Mo/min |
| gdigrab + h264_mf (Media Foundation) | 27,5 % | 1,5 Mo/min |
| ddagrab + x264 ultrafast | 16,2 % | 1,7 Mo/min |

Résistance à une mort brutale (ffmpeg tué ~4 s après le lancement, 5 i/s) :

| Conteneur / réglage | Octets sur disque | Lisible |
| --- | --- | --- |
| MKV, x264 par défaut | 0 | non |
| MKV + `flush_packets` + clusters 2 s, x264 par défaut | 591 (en-tête) | non (lookahead x264 : ~6 s retenus en mémoire) |
| MKV + `zerolatency` + clusters 2 s | 71 963 | oui, 2,0 s, durée N/A |
| MP4 fragmenté (`frag_keyframe+empty_moov`) + `zerolatency`, fragments à l'image clé (2 s) | 72 026 | oui, 2,0 s, durée lue |
| **MP4 fragmenté + `zerolatency` + fragments d'1 s (retenu)** | 75 358 | **oui, 3,0 s** |

## Arguments finaux (`recording_args`), 10 s par mesure

| Écran / contenu | i/s | CPU ffmpeg | Taille | Durée sondée |
| --- | --- | --- | --- | --- |
| principal, bureau surtout statique | 5 | 31,0 % | 0,54 Mo/min | 10,0 s |
| principal | 10 | 56,2 % | 0,58 Mo/min | 9,8 s |
| second, contenu animé | 5 | 38,6 % | 10,04 Mo/min | 10,0 s |
| second | 10 | 64,5 % | 16,48 Mo/min | 10,4 s |

## Smoke par le vrai `CaptureService` (sources de production, écran principal)

| Mesure | Valeur |
| --- | --- |
| Capture d'écran | `complete`, PNG valide 1920×1080 (= résolution physique du principal), 154 390 octets, 167 ms (prise 145 ms), `dpi` 120, `dpi_scale` 1.25 |
| Enregistrement 5 s | `complete`, 1920×1080, H.264 High yuv420p, `ffmpeg -i` : Duration 00:00:05.20, `duration_source: probe`, sortie 0 |
| Latence démarrage (`start` → `active`) | 0,39 s |
| Latence arrêt (`q` → finalisé, mesure comprise) | 0,69 s |
| Taille | 81 286 octets, 0,86 Mo/min |
| CPU ffmpeg | 1,20 s sur 5,70 s = 21,1 % d'un cœur (1,06 % de l'hôte) |
| CPU Core (service + surveillance) | 0,08 s = 1,4 % d'un cœur |

## Mort brutale de Core pendant un enregistrement réel

Harnais Core (vrai service, vraie source) tué par `TerminateProcess` ~4,4 s
après le démarrage :

| Mesure | Valeur |
| --- | --- |
| ffmpeg vivant avant le kill | oui |
| ffmpeg après le kill de Core | **mort 0,02 s plus tard** (Job Object `KILL_ON_JOB_CLOSE`) |
| Fichier laissé | `screen.mp4.partial`, 77 935 octets |
| Reprise au démarrage suivant | capture `partial`/`recoverable_partial`, Artifact `partial`, 4 fragments, 0 octet tronqué, `duration_ms` 4000 |
| Décodage complet (`ffmpeg -i … -f null -`) | time=00:00:04.00, aucune erreur |

Après les mesures : `tasklist` ne montre aucun ffmpeg ; dossiers `smoke1`,
`smoke2`, `meas`, `meas2` supprimés.

## Tests

- `tests/unit/test_screen_capture.py` : 31 verts avec ffmpeg
  (`JARVIS_FFMPEG_EXE`), 29 verts + 2 ignorés sans (venv partagé, marqueur
  « ffmpeg absent: install the 'capture' extra »). Les deux tests ffmpeg
  utilisent une mire `lavfi testsrc`, jamais le bureau.
- Non-régression : `test_capture_domain/service/store` 49, `test_artifact_payloads/store` 34,
  `test_scene_capture` + `test_scene_capture_logic` 37 (capture de scène intacte),
  `test_v2_architecture` + `test_owned_process_tree` + `test_schema_migrations` 21,
  `test_audio_recording_source` + `test_recording_transcriber` 33, `test_app` 27. 0 échec.
