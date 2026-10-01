# Vérifications humaines — Sessions, Contexts, enregistrements

Ordre conseillé : 0 (préparation), puis HV-REC-UI-001, HV-REC-AUDIO-001, HV-REC-SCREEN-001,
HV-REC-UI-002, et HV-REC-E2E-001 en dernier. Compter environ 30 minutes.

Tout ce qu'une machine peut vérifier l'a été (Slice 11, `EVIDENCE.md`) : reprise de la Session
après chaque redémarrage, Context dormant jamais écrit, capture qui continue pendant un
redémarrage du cerveau ou du Control Center, partiel réparé après une mort de Core,
requêtes par heure, nature, Session et Context, parité entre l'API, l'outil MCP du cerveau et le
rail, migration v4 → v7 et retour arrière. Ce qui suit ne demande que ce qu'une machine ne sait
pas juger : écouter, regarder, lire, et dire si c'est compréhensible.

## 0. Préparation

### 0.1 Choisir où tester

Deux façons de faire. Elles ne touchent pas les mêmes données.

| | A. Fusionner la branche dans votre Jarvis habituel | B. Lancer la branche à côté, sur ses propres données |
| --- | --- | --- |
| Données | votre vraie base, vos vraies Sessions | une base neuve, propre au dossier `C:\Projects\jarvis\bsc` (`~/.jarvis/instances/bsc-…`) |
| Base | migrée de v4 en v7 au premier démarrage ; copie automatique `jarvis.sqlite3.v4.bak` à côté | votre vraie base n'est pas ouverte |
| Retour arrière | le `main` d'avant cette branche **refuse** une base v7 (il s'arrête, sans la modifier) : pour revenir, restaurer `jarvis.sqlite3.v4.bak` (procédure dans `docs/session-context-capture.md`, *Schema migration and rollback*) ; ce qui a été écrit depuis la migration reste dans la base mise de côté | rien à défaire : arrêter, relancer votre Jarvis habituel |
| Session « existante » de HV-REC-E2E-001 | la vôtre, avec son historique | à créer : démarrer, dire une phrase au cerveau, arrêter, relancer |
| Ports | ceux de toujours | les mêmes : **arrêter d'abord** votre Jarvis habituel |

Dans les deux cas, la migration a été répétée sur une copie fabriquée par le `main` actuel :
même Session, même conversation, un Context « adopté », une seule copie `.v4.bak`.

### 0.2 Installer l'enregistrement d'écran (ffmpeg)

- Option A, depuis `C:\Projects\jarvis\jarvis` :
  `.\.venv\Scripts\python.exe -m pip install -e ".[capture]"`
- Option B : `C:\Projects\jarvis\jarvis\.venv\Scripts\python.exe -m pip install imageio-ffmpeg==0.6.0`
  (pas `-e ".[capture]"` depuis `bsc` : cela redirigerait l'installation du venv vers `bsc`).

Environ 85 Mo. Sans cela, l'enregistrement d'écran est refusé avec la commande d'installation
dans la note ; la capture d'écran et l'audio marchent quand même.

### 0.3 Lancer

- Option A : comme d'habitude.
- Option B : dans PowerShell, depuis `C:\Projects\jarvis\bsc` :
  `$env:PYTHONPATH="C:\Projects\jarvis\bsc"` puis
  `C:\Projects\jarvis\jarvis\.venv\Scripts\python.exe scripts\supervisor_v2.py`.

Il faut une clé OpenAI dans les réglages du Control Center pour la transcription (déjà le cas en
option A si la voix marche avec OpenAI). Option B : les réglages du Control Center lancé depuis
`bsc` sont dans `C:\Projects\jarvis\bsc\runtime`, vides au départ : y saisir la clé OpenAI
(onglet Config) avant HV-REC-AUDIO-001 ; sans clé, la transcription attend
(`transcription_unavailable`) et l'enregistrement, lui, se fait.

### 0.4 À savoir avant de juger

- **Écart V1 accepté** : la zone sûre de la scène ignore la colonne de gauche. À 1280 × 720, la
  colonne (contrôle Bare Hands, palette, rail de capture) descend jusqu'à y 541 px, et la scène
  peut encore y poser du contenu. Les gestes, eux, s'arrêtent contre le rail. Vous décidez si
  cela bloque la recette (`Issues/scene-safe-area-left-column.md`).
- **Limites connues de la V1** :
  - Codex n'a pas les outils de capture (seul le cerveau Claude les a) ;
  - pas de capture d'une seule fenêtre : écran entier seulement (`display1` = principal) ;
  - pas de caméra (prévue plus tard, sans migration) ;
  - les enregistrements d'écran ne sont pas décrits image par image : ils entrent dans le
    résumé comme une ligne (durée, état) ; seules les captures d'écran sont décrites ;
  - coût : transcription ≈ 0,003 $ par minute de parole ; résumé du Context ≈ 0,05 à 0,10 $ par
    heure d'enregistrement ; une description par capture d'écran ;
  - une transcription lue ou citée par le cerveau apparaît dans `runtime\trace.jsonl` comme
    toute réponse du cerveau (`Issues/trace-agent-event-room-text.md`) ;
  - un disque lent peut figer quelques secondes le Control Center (« état inconnu » sur le rail,
    puis retour) : `Issues/runtime-journal-sync-append.md`.
- **Où sont les fichiers** : dossier de données (`docs/local-data.md`), sous-dossier
  `artifacts\<identifiant>\` : `source.wav`, `screenshot.png`, `screen.mp4`,
  `transcript.txt`. Le résumé du Context : `sessions\<session>\contexts\<context>\summary.md`.
  Pour trouver un identifiant, demandez au cerveau (« retrouve la dernière capture d'écran ») :
  il répond avec l'identifiant `jart_…`.

## HV-REC-UI-001 — Le rail de capture à gauche

1. Ouvrir le Control Center, fenêtre normale (environ 1440 × 900).
2. Regarder la colonne de gauche : sous la palette Bare Hands (pointeur, main, sélection), un
   bloc séparé par un trait, légendé `CAPTURE`, avec trois boutons : appareil photo (capture
   d'écran), micro (audio), écran (enregistrement d'écran).
3. Survoler chaque bouton : l'infobulle dit ce qu'il fait.
4. Couper Bare Hands (son interrupteur habituel), puis le rallumer : le rail reste utilisable
   dans les deux cas.
5. Réduire la fenêtre (étroite et basse, par exemple 800 × 600) : le rail passe à côté de la
   colonne s'il manque de place ; il ne couvre ni le bouton de mode, ni le dock, ni la barre du
   haut.
6. Cliquer le micro : une attente avec un compteur de secondes, puis le bouton reste un micro
   avec une **pastille carrée** (arrêt) en haut à droite, une barre latérale et un chronomètre ;
   la légende passe à `REC 1`. Cliquer la pastille : retour au repos.

Attendu : les commandes de capture se lisent comme faisant partie de la colonne, mais distinctes
des outils Bare Hands ; l'état actif se comprend sans la couleur (pastille, chronomètre, `REC`) ;
le rail ne gêne rien d'important. Dire aussi si l'écart de zone sûre (0.4) vous gêne.

## HV-REC-AUDIO-001 — Enregistrement du micro et transcription

1. Cliquer le micro du rail. Vérifier que l'enregistrement se voit (pastille, chronomètre).
2. Parler au moins 30 secondes **avec des pauses** de 1 à 2 secondes (par exemple : dire trois
   phrases numérotées, « premier point… », « deuxième point… », « troisième point… »).
3. Cliquer la pastille d'arrêt. Le bouton revient au repos ; aucune note d'erreur.
4. Demander au cerveau : « Lis-moi mot pour mot ce que je viens de dire, avec le minutage ».
5. Ouvrir le dossier de l'enregistrement (identifiant donné par le cerveau, ou le plus récent de
   `artifacts\`) et écouter `source.wav` en entier. Ouvrir `transcript.txt` à côté de lui
   (dossier `<identifiant>_transcript`).

Attendu : le fichier s'écoute jusqu'au bout ; les phrases sont dans l'ordre, et leurs minutes
correspondent à peu près au moment où elles ont été dites ; les silences ne produisent pas de
texte. Si quelque chose manque, le cerveau ou la note du rail doit le dire (partiel, trou) : rien
ne doit manquer sans être signalé.

## HV-REC-SCREEN-001 — Capture d'écran et enregistrement d'écran réels

1. Cliquer l'appareil photo du rail. Une coche apparaît deux secondes.
2. Cliquer l'écran du rail. Pendant au moins 20 secondes, changer visiblement ce qui est à
   l'écran principal (ouvrir une fenêtre, en déplacer une, faire défiler une page).
3. Cliquer la pastille d'arrêt de l'écran.
4. Ouvrir `screenshot.png` et `screen.mp4` (identifiants donnés par le cerveau : « quelles
   preuves viennent d'être créées ? »).

Attendu : la capture montre l'écran principal entier, net, à sa vraie taille ; la vidéo se lit
d'un bout à l'autre et montre les changements (5 images par seconde : fluide sans plus) ; les
deux fichiers sont dans `artifacts\`, pas dans `runtime\scene-captures\`. Si une erreur
s'affiche (écran verrouillé, ffmpeg absent), la note doit se comprendre.

## HV-REC-UI-002 — Deux enregistrements ensemble

1. Cliquer le micro, puis l'écran : deux boutons actifs, chacun avec son icône et sa pastille,
   légende `REC 2`.
2. Pendant ce temps, cliquer l'appareil photo : la capture se prend, les deux enregistrements
   continuent.
3. Arrêter l'écran seul : le micro continue (sa pastille et son chronomètre restent). Légende
   `REC 1`.
4. Arrêter le micro.

Attendu : les deux tournent ensemble, la capture d'écran est une action à part, arrêter l'un
n'arrête pas l'autre, et aucun bouton ne reste « actif » après son arrêt.

## HV-REC-E2E-001 — Continuité pendant un redémarrage du cerveau

1. Reprendre une Session existante : simplement démarrer Jarvis (option A : votre Session
   d'avant ; option B : voir 0.1). Demander au cerveau « Dans quelle session et quel contexte
   sommes-nous ? » et noter sa réponse.
2. Démarrer l'audio et l'écran depuis le rail, prendre une capture d'écran.
3. Parler une vingtaine de secondes (quelques phrases repérables).
4. Redémarrer **seulement le cerveau** : dans le Control Center, carte du brain, clic droit →
   « Redémarrer ». (Ne pas utiliser « nouvelle conversation » des réglages de scène : elle ouvre
   une nouvelle Session.) Pendant ce temps, le rail garde ses deux chronomètres qui avancent.
5. Après le redémarrage, demander : « Qu'est-ce qui s'est dit depuis le début de
   l'enregistrement, et qu'est-ce qui tourne en ce moment ? »
6. Arrêter l'écran (garder l'audio quelques secondes de plus), puis l'audio.
7. Demander : « Retrouve les preuves créées depuis 10 minutes : leur nature et leur heure. »,
   puis « Lis-moi la transcription à partir de la dixième seconde. »
8. Redemander « Dans quelle session et quel contexte sommes-nous ? ».

Attendu : même Session et même Context qu'au point 1 ; les enregistrements n'ont pas été coupés
par le redémarrage (aucun « interrompu » sur le rail, fichiers complets) ; le cerveau redémarré
sait ce qui tourne et ce qui s'est dit récemment sans relire toute la transcription ; les preuves
sont retrouvées par heure et par nature, rattachées à cette Session ; aucun bouton du rail ne
reste dans un état faux.

## Après les vérifications

Supprimer les enregistrements de test si vous ne voulez pas les garder (ils ne s'effacent jamais
seuls ; l'interface n'a pas encore de bouton de suppression en V1) : demander au cerveau leurs
identifiants `jart_…`, puis, dans PowerShell, pour chacun :
`Invoke-RestMethod -Method Delete "http://127.0.0.1:17654/api/artifacts/<identifiant>?cascade=true"`
(l'enregistrement, sa transcription et ses segments partent ensemble). Une transcription encore
en attente bloque la suppression : l'abandonner d'abord avec
`Invoke-RestMethod -Method Post "http://127.0.0.1:17654/api/captures/<jcap_…>/transcription/abandon"`.
Option B : arrêter, puis relancer votre Jarvis habituel.
