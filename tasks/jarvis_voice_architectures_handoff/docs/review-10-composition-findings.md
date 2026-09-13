# Revue indépendante Task10 — composition directe

Statut final : **accepté — aucun finding ouvert**.

## Périmètre

Revue indépendante du chemin de composition `Simple` / `Front Brain`. Les
frontières externes sont contrôlées ; le bridge, le scheduler, le sidecar,
l'encodeur OpenAI Realtime, l'admission atomique avant écriture et le join de
preuve multipart sont les implémentations de production.

Le nouveau fichier permanent
`tests/integration/test_front_brain_composition_review.py` vérifie :

- un tour adressé en `Simple` demande une réponse conversationnelle directe,
  sans soumission au backend fort et sans analyse Luna ;
- la même réponse directe part en `Front Brain` pendant qu'une analyse Luna
  reste bloquée ;
- une entrée d'une autre session ou explicitement rejetée ne déclenche aucun
  appel Luna ;
- le résultat tardif d'un partial révoqué n'est jamais consommé ; un final
  remplace le partial avec une nouvelle identité et lui seul est consommable ;
- une source Core plus récente ou `Stop` pendant l'attente fournisseur invalide
  la réservation, puis le vrai garde d'écriture native refuse le premier bloc ;
- l'appel Realtime contient exactement `response.create.response.input` avec
  les `item_reference` admis, sans `conversation.item.create` et sans
  `conversation: "none"` ;
- transcript, audio, fermeture des parties et fin de génération ne suffisent
  pas à produire `COMPLETE` : seul le drain checked du périphérique, avec les
  deux parties et leurs tailles exactes, autorise le texte confirmé ;
- fermer le sidecar annule son analyse possédée sans annuler une tâche de job
  indépendante.

La revue du raccordement final ajoute les preuves suivantes :

- deux tours provider conservent exactement la chaîne référencée
  `[user A, assistant A confirmé, user B]` ; le segment de bruit rejeté n'y
  apparaît jamais ;
- le contexte initial confirmé est envoyé comme messages `user` / `assistant`,
  absent des instructions, sans `response.create` initial ;
- les métadonnées de compatibilité `legacy` / `continuous_brain` restent
  inchangées ; les sélections explicites publient le modèle et le
  `configuration_id` exacts ;
- le registre distingue disponibilité fournisseur et adaptateur prêt, et
  refuse Duplex tant que son adaptateur n'est pas prêt ;
- une sélection Duplex versionnée conserve son `VoiceConfigError`
  `voice_adapter_not_ready` avant lecture de credentials ou ouverture de
  session, tandis qu'une ancienne valeur libre `voice_arch=duplex` garde son
  erreur de migration destinée à l'utilisateur ;
- `VisualSignalBus.offline()` remet l'état à `idle` et efface heartbeat,
  alerte, waveform et rapport de capture ; un cleanup device encore en cours
  reste explicitement en erreur sans faux `idle` ;
- le final Luna attend que la projection Core soit complète et égale à sa
  source d'origine. L'admission seule ne suffit pas.

## Finding résolu pendant la revue finale

`tests/unit/test_app.py::test_an_unknown_architecture_in_the_settings_file_stops_voice_clearly`
a d'abord reproduit un défaut de compatibilité : `resolve_voice_composition()`
était appelé avant le bloc qui transforme une ancienne valeur `voice_arch`
inconnue en erreur utilisateur stable. Le lead a déplacé la résolution dans ce
bloc. Le test isolé passe après correction ; la forme des métadonnées de
compatibilité reste couverte par `test_voice_composition.py`.

## Observabilité / contrat de test

Les corrélations contrôlées joignent `session`, item fournisseur, source Core
et output local. Les chemins normaux attendus sont l'admission directe, la
présentation conversationnelle et, pour Luna, `voice.hint.dispatched` puis une
consommation correspondant au final courant. Les révocations doivent produire
`voice.hint.revoked` ou `voice.hint.invalidated` sans texte privé. Une réponse
retirée avant son premier write ne doit laisser aucun octet au périphérique.
Aucun probe temporaire n'a été ajouté.

## Validation

Commande ciblée :

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_front_brain_composition_review.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Résultat final : **9 passed in 0.83s**.

Commande de régression adjacente (composition, Luna, sidecar, façade Realtime,
admission Core et protocole) :

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_front_brain_composition_review.py tests/unit/test_front_brain_sidecar.py tests/unit/test_front_brain_sidecar_review.py tests/unit/test_luna_front_brain_review.py tests/unit/test_realtime_frontend_adapter.py tests/unit/test_realtime_frontend_pipeline.py tests/unit/test_voice_turn_admission.py tests/unit/test_voice_admission_protocol.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Résultat intermédiaire : **132 passed in 5.91s**.

Gate final demandé, après raccordement lead et correction du finding :

```text
.venv/Scripts/python.exe -m pytest tests/integration/test_front_brain_composition_review.py tests/integration/test_simple_front_brain_composition.py tests/unit/test_voice_architecture_config.py tests/unit/test_voice_composition.py tests/unit/test_app.py -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Résultat actuel après ajout du cas Duplex versionné : **88 passed in 5.96s**.

Contrôles directs du nettoyage visuel :

```text
.venv/Scripts/python.exe -m pytest tests/unit/test_control_center_mvp.py::test_visual_signal_bus_tracks_heartbeat_and_clears_stale_visuals tests/unit/test_control_center_quality.py::test_voice_going_offline_clears_its_capture_report -q -W error -o asyncio_default_fixture_loop_scope=function --tb=short
```

Résultat : **2 passed in 0.73s**.

La preuve device reste une preuve de drain du tampon contrôlé, pas une mesure
acoustique humaine. Le test de job vérifie la séparation de propriété asyncio ;
le cycle de vie durable du `JobService` relève de Task11.
