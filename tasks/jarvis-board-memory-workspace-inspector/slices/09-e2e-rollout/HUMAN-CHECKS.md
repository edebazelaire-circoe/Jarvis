# Vérifications humaines : Sessions & Boards, liste des Boards

Il y a deux vérifications : **HV-WS-UI-001** (le gestionnaire « Sessions & Boards ») et
**HV-WS-UI-002** (la liste rapide des Boards). Elles se font sur **votre Jarvis habituel**,
après la fusion de la branche `task/jarvis-board-memory-workspace-inspector` dans `main`.
Comptez environ 25 minutes.

Une machine a déjà vérifié tout ce qu'elle pouvait vérifier (`EVIDENCE.md` de cette Slice et
des Slices 07 et 08) :

- la migration v7 → v8 sur une base fabriquée par l'ancien code, et le retour arrière ;
- la mémoire d'un Board qui survit à un redémarrage ;
- un tour qui ne reçoit que la mémoire de son Board ;
- une inspection qui n'active rien ;
- les mêmes codes d'erreur par l'écran et par les outils de Jarvis ;
- les évasions de chemin refusées ;
- un Board archivé en lecture seule ;
- un sous-agent réel qui lit un Board archivé sans l'ouvrir.

Il vous reste ce qu'une machine ne sait pas juger : **est-ce compréhensible, et est-ce
agréable au quotidien ?**

## 0. Avant de commencer : la base change de version

### 0.1 Ce qui va se passer au redémarrage

Au premier démarrage du nouveau code, Core fait deux choses, dans cet ordre :

1. il copie votre base en `jarvis.sqlite3.v7.bak`, dans le même dossier ;
2. il fait passer `jarvis.sqlite3` de la version 7 à la version 8.

Le passage en v8 ajoute seulement la table des liens Board-artefact. Aucune ligne existante
n'est réécrite. Votre Session ouverte est reprise.

Le dossier de la base est le sous-dossier `state` de vos données :
`%USERPROFILE%\.jarvis\instances\jarvis-<empreinte>\data\state\`
(voir `docs/local-data.md`).

**Sens unique.** Une fois la base en v8, le Jarvis d'avant cette branche refuse de
démarrer sur elle. Il affiche `Jarvis: state DB schema 8 is newer than supported 7` et ne
modifie pas la base. Cela a été mesuré sur une copie.

### 0.2 Prudence conseillée, avant le redémarrage

1. Arrêtez votre Jarvis, depuis là où vous le lancez d'habitude (ProjectPane).
2. Copiez le dossier `state` ailleurs, par exemple sur le Bureau.

La copie automatique `.v7.bak` suffit en principe. Cette copie-ci couvre aussi les fichiers
`-wal`/`-shm` et les autres bases.

### 0.3 Lancer

1. Mettez `C:\Projects\jarvis\jarvis` à jour sur `main` fusionné.
2. Relancez Jarvis comme d'habitude.

Rien d'autre à installer.

Pour vérifier la migration, ouvrez le dossier `state` :

- `jarvis.sqlite3.v7.bak` doit exister, daté de ce démarrage ;
- votre conversation en cours doit être la même qu'avant.

### 0.4 Revenir en arrière (seulement si vous rejetez la recette)

1. Arrêtez Jarvis.
2. Dans `state`, déplacez `jarvis.sqlite3`, `jarvis.sqlite3-wal` et `jarvis.sqlite3-shm`
   (s'ils existent) dans un dossier à part. Ne les supprimez pas.
3. Copiez `jarvis.sqlite3.v7.bak` en `jarvis.sqlite3`.
4. Remettez le code d'avant la fusion, puis relancez. La même Session reprend : c'est mesuré.

Ce qui a été écrit depuis la migration reste dans la base mise de côté :

- les liens Board-artefact ;
- les natures de Board ;
- les lignes du journal.

Les dossiers de mémoire `boards\` restent sur le disque. L'ancien code ne les lit pas.

Avant de refaire une migration plus tard, renommez d'abord l'ancienne copie
(`jarvis.sqlite3.v7.bak` → `jarvis.sqlite3.v7.before-rollback.bak`). Sinon, aucune nouvelle
copie ne sera faite.

### 0.5 Préparer de quoi regarder (5 minutes)

Les deux vérifications ont besoin de plusieurs Boards, de fichiers de mémoire et d'au moins
deux Sessions. Si vous ne les avez pas encore, préparez-les ainsi :

1. Par le bouton **Board** en haut de l'écran, créez :
   - « Recette A », nature **Générique** ;
   - « Recette B », nature **Réunion** ;
   - « Recette C », nature **Présentation**.
2. Basculez sur « Recette B ». Dites ou écrivez à Jarvis :
   « Note dans la mémoire de ce Board, fichier summary.md : décision de recette, code
   RECETTE-1. »
3. Revenez sur votre Board habituel. En bas de la liste du bouton Board, cliquez
   « Nouvelle session » : une deuxième Session s'ouvre, sur le même Board.
4. Archivez « Recette C » (icône boîte de sa ligne, puis confirmer).

## HV-WS-UI-001 : le gestionnaire « Sessions & Boards » est-il compréhensible ?

Les écrans attendus sont ceux de la Slice 07 :
`slices/07-deep-workspace-manager-ui/evidence/01-overview.png` à `16-*.png`. Le tableau de
`slices/07-deep-workspace-manager-ui/EVIDENCE.md` dit ce que montre chaque capture. Ils ont
été pris sur des données de test : vos titres et vos nombres seront différents.

1. Dans le **dock** (la barre de boutons ERR TRC LAB CNV SET MCP AGT…), cliquez **WSP**.
   La vue plein écran « Sessions & Boards » s'ouvre (`01-overview.png`).
2. **Vue d'ensemble**. Regardez si vous comprenez :
   - quelle est la Session courante ;
   - quel Board est actif, et où vit sa mémoire (`boards/<id>/memory`) ;
   - quel Context est actif ;
   - quel agent parle (la liaison au premier plan).
3. **Sessions** (`02-sessions.png`) :
   - dépliez la Session close de l'étape 0.5 ;
   - retrouvez-y les Boards qu'elle a visités, leurs liaisons et ses Contexts ;
   - retrouvez son journal, avec l'écriture `board.memory.written` faite sur « Recette B »
     (`10-session-ledger.png`).
4. **Boards** (`03-boards.png`) :
   - tous les Boards apparaissent, « Recette C » archivé compris ;
   - chacun porte sa nature ;
   - le Board actif est marqué.
5. **Relations** (`04-relations-session.png`, `05-relations-board.png`). Pour « Recette B »,
   suivez :
   - Board → mémoire ;
   - Board → artefacts ;
   - Board → Sessions → liaisons.

   Est-il clair quel fichier appartient à quel Board, et quel Board à quelle Session ?
6. **Mémoire** (`06-memory-read.png` à `09-memory-deleted.png`) :
   1. Sur « Recette B », ouvrez `summary.md` : vous lisez « RECETTE-1 ».
   2. Créez un fichier `notes/essai.md`.
   3. Renommez-le.
   4. Supprimez-le. Avant de valider, regardez la confirmation : elle est **rouge**, dans le
      panneau, à côté de la ligne ; elle nomme le chemin et le Board et dit « pas de
      corbeille » (`08-memory-confirm-delete.png`). Validez.
7. **Board archivé** : ouvrez la mémoire de « Recette C ». Vous devez voir un bandeau
   « lecture seule » et aucune commande d'écriture (`11-memory-archived-read-only.png`).
8. **Artefacts** (`12-artifacts-provenance.png`) : si vous avez des captures ou des
   transcriptions, ouvrez-en une et lisez sa provenance et les Boards liés.
9. Appuyez sur Échap pour fermer.

**Réussi** si les quatre points sont vrais :

- vous pouvez dire, **sans lire de code**, quel est le Board actif et lesquels sont anciens
  ou archivés ;
- vous pouvez dire à quel Board appartient chaque fichier de mémoire, et comment Session,
  Board, liaison et artefact sont reliés ;
- la suppression d'un fichier ne peut pas se confondre avec une action ordinaire ;
- ouvrir cette vue n'a changé ni le Board actif ni la voix. Le bouton Board du haut
  affiche le même titre avant et après.

**Échoué** si l'un de ces points est faux, ou si un refus s'affiche sans phrase ni code.
Notez alors le mot ou l'écran qui vous a perdu : c'est le retour utile.

## HV-WS-UI-002 : la liste rapide des Boards est-elle simple au quotidien ?

Les écrans attendus sont ceux de la Slice 08 :
`slices/08-quick-board-browser/evidence/01-list.png` à `10-short-height.png`, décrits dans
son `EVIDENCE.md`.

1. Cliquez le bouton **Board**, en haut de l'écran : celui qui affiche le titre du Board
   actif. La liste s'ouvre (`01-list.png`). Pour chaque ligne, regardez :
   - le titre ;
   - la nature ;
   - « ouvert il y a … » ou « jamais ouvert » ;
   - pour le Board actif : le point plein, le cadre et « Actif ».

   Le Board actif se repère-t-il d'un coup d'œil ?
2. **Basculer entre trois Boards** : cliquez « Recette A », puis « Recette B », puis votre
   Board habituel. À chaque fois :
   - le bouton du haut compte les secondes (« Bascule · N s ») ;
   - il ne prend le nouveau titre qu'une fois le serveur d'accord (`09-switched-to-a.png`) ;
   - Jarvis répond sur le bon Board. Demandez-lui par exemple « sur quel Board sommes-nous ? ».
3. **Créer** : « Nouveau Board », un titre, une nature, « Créer » (`02-created-meeting.png`).
   Le Board créé n'est **pas** ouvert : c'est voulu.
4. **Renommer et changer la nature** : le crayon d'une ligne, puis « Enregistrer »
   (`03-edit-kind.png`, `04-kind-changed.png`). Changer la nature ne démarre ni réunion ni
   présentation.
5. **Archivés** : le filtre « En service / Archivés ».
   - « Recette C » y est, sans bascule possible (`05-archived.png`) ;
   - seule l'action « Inspecter » reste.
6. **Atteindre le gestionnaire** : sur une ligne, l'icône flèche « ouvrir ailleurs »
   (« Inspecter ») ouvre « Sessions & Boards » directement sur ce Board, sa ligne dépliée
   (`06-inspect-archived.png`, `07-inspect-meeting.png`). Échap rend la main au bouton Board.

**Réussi** si les quatre points sont vrais :

- vous identifiez le Board actif ;
- vous basculez entre trois Boards, créez et renommez un Board, et atteignez le
  gestionnaire, **sans hésiter** ;
- la liste reste un geste léger de tous les jours, qui ne ressemble pas à l'outil de
  diagnostic WSP ;
- la voix et la conversation suivent le Board choisi, et seulement lui.

**Échoué** dans l'un de ces cas :

- une bascule affiche un titre que le serveur n'a pas confirmé ;
- une action reste sans retour ;
- la liste vous paraît être un second gestionnaire.

## Après la recette

Dites à l'agent, pour chacune, « HV-WS-UI-001 réussi / échoué : … » et
« HV-WS-UI-002 réussi / échoué : … », avec les mots qui vous ont gêné. Vous pouvez laisser
les Boards « Recette » archivés (il n'existe pas de suppression de Board en V1) ; leurs
dossiers de mémoire restent sur le disque.
