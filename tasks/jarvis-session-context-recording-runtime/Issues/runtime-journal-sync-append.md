# Le journal `RuntimeJournal` écrit sur la boucle d'événements : un disque lent fige le processus

- Trouvé : 2026-10-01, Slice 11, enquête sur l'arrêt de ~12 s vu pendant la QA de la Slice 10
  (`GET /v1/captures/status` lu par le Control Center en 12,6 s, `core_timeout` dans la trace,
  `/board` injoignable pendant la même fenêtre).
- Hors périmètre : `jarvis/runtime/journal.py` est antérieur à cette tâche et partagé par Core,
  le Control Center, Voice et les serveurs MCP. Le changer touche tous les processus.

## Constat

`RuntimeJournal.emit()` ouvre `runtime/trace.jsonl` en ajout, écrit une ligne et le ferme, de
façon synchrone, dans le fil de l'appelant — le plus souvent la boucle asyncio.

Reproduit avec le harnais `scripts/e2e_session_capture.py` (chien de garde de boucle : battement
de 100 ms, pile du fil de la boucle relevée dès 1 s de retard, `faulthandler` pour tous les fils
à 3 s) :

- soak 1 (Core + Control Center, enregistrements audio et écran, sondage du statut à 1 Hz) :
  **11,2 s** de boucle figée dans le Control Center, pile figée dans
  `claude_local.wait_ready` → `RuntimeJournal.emit("agent.ready")` → `journal._append` →
  `path.open("a")`. Pendant ces 11 s, le fil du chien de garde (qui écrit lui aussi dans le
  dossier `runtime`) n'a rien pu écrire : c'est l'ouverture de fichier qui bloquait, pas le GIL ;
- matrice finale : 6,7 s figées dans un import paresseux (`importlib … get_data`, lecture d'un
  `.py`) sur la boucle du Control Center ; une sonde hors boucle a mesuré une ouverture de fichier
  en ajout de **2,09 s** dans le même dossier ;
- Core, dans les mêmes runs : pire lecture du statut 0,78 s (p99 0,04 s), aucun arrêt > 3 s.

L'hôte a donc des pics de latence du système de fichiers de plusieurs secondes (antivirus,
mémoire disponible 1-2 Go). Toute E/S disque synchrone sur une boucle les transforme en arrêt
complet du processus : routes, relais, rail de capture (« état inconnu »).

## Ce qui a été corrigé dans la tâche

Le code de cette tâche qui touchait le disque sur la boucle de Core passe dans un fil
(`asyncio.to_thread`) : dossiers de Context (`ensure`, `handoff.md`, lecture de `summary.md`,
écritures et lectures du worker d'enrichissement, y compris la taille et la lecture des captures
d'écran à décrire, jusqu'à 3,5 Mo — reprise finale) et payloads d'Artifact (`store_payload`,
suppression des dossiers). Test : `tests/unit/test_core_disk_off_loop.py` (le témoin de boucle
bat encore 50 ms après la dernière opération, pour que son blocage soit mesuré).

## Ce qui reste

- `RuntimeJournal.emit` sur la boucle, dans tous les processus. Correction proposée : un
  écrivain par processus (fil dédié + file bornée, perte comptée et dite), `emit` ne fait plus
  que mettre en file ; ordre gardé ; vidage à l'arrêt.
- Les imports paresseux dans des gestionnaires de requête du Control Center (`jarvis.testlab.*`,
  `aiohttp.web_fileresponse`) : 1,3 à 2,5 s au premier appel, jusqu'à 6,7 s observées.
- `ArtifactService.open_spool` (ouverture du `.partial` au démarrage d'une capture) et les
  `stat` de finalisation restent sur la boucle de Core : un appel court par capture.
